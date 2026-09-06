#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import shlex
import stat
from datetime import UTC, datetime
from pathlib import Path

import yaml

try:
    from scripts.engineering_ssh_key import PublicKeyError, parse_public_key
except ModuleNotFoundError:
    from engineering_ssh_key import PublicKeyError, parse_public_key

PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
GITHUB_TOKEN = re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")
TOKEN_ASSIGNMENT = re.compile(
    rb"(?:api[-_]?key|secret[-_]?key|access[-_]?token)\s*[:=]\s*[^\s#]{8,}",
    re.IGNORECASE,
)
WIFI_CONFIG_SECRET = re.compile(
    rb"^[ \t]*(?:wifi_password|wifi-password|wifi[ \t]+password|psk)[ \t]*[:=][ \t]*"
    rb"(?:\"(?:\\.|[^\"\\\r\n])+\"|'(?:\\.|[^'\\\r\n])+'|[^\s#]+)[ \t]*(?:#.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
WIFI_SOURCE_LITERAL = re.compile(
    rb"\b(?:wifiPassword|psk|password)\b[ \t]*[:=][ \t]*"
    rb"(?:\"(?:\\.|[^\"\\\r\n])+\"|'(?:\\.|[^'\\\r\n])+')",
    re.IGNORECASE,
)
LINUX_HOME_PREFIX = rb"/ho" + rb"me/"
MAC_HOME_PREFIX = rb"/Us" + rb"ers/"
WINDOWS_HOME_PREFIX = rb"[A-Za-z]:\\Us" + rb"ers\\"
HOME_PATH = re.compile(
    rb"(?:"
    + LINUX_HOME_PREFIX
    + rb"[^/\s]+|"
    + MAC_HOME_PREFIX
    + rb"[^/\s]+|"
    + WINDOWS_HOME_PREFIX
    + rb"[^\\\s]+)[/\\]"
)
SHADOW_PASSWORD_HASH = re.compile(r"^\$[^$:\s]+\$(?:[^$:\s]+\$)+[^$:\s]+$")
ALLOWED_NM_PROFILE = "rave-setup.nmconnection"
ENGINEERING_SSH_ARTIFACTS = (
    "etc/ssh/sshd_config.d/90-rave-ethernet.conf",
    "etc/sudoers.d/90-rave-engineering-ssh",
    "etc/systemd/system/ssh.service.d/90-rave-hostkeys.conf",
    "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf",
    "home/pi/.ssh/authorized_keys",
    "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service",
)


class VerificationError(RuntimeError):
    pass


def contains_wifi_credential(data: bytes) -> bool:
    return WIFI_CONFIG_SECRET.search(data) is not None or WIFI_SOURCE_LITERAL.search(data) is not None


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def partition_size_mib(value: object, name: str) -> int:
    require(isinstance(value, str), f"{name} partition size must use explicit M or G units")
    match = re.fullmatch(r"([1-9][0-9]*)([MG])", value)
    require(match is not None, f"{name} partition size must use explicit M or G units")
    amount = int(match.group(1))
    return amount if match.group(2) == "M" else amount * 1024


def verify_image_configuration(path: Path) -> dict[str, object]:
    require(path.is_file(), "RAVE OS image configuration is missing")
    try:
        configuration = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise VerificationError(f"RAVE OS image configuration is invalid YAML: {error}") from error
    require(isinstance(configuration, dict), "RAVE OS image configuration is not a mapping")
    image = configuration.get("image")
    require(isinstance(image, dict), "RAVE OS image configuration has no image section")
    require(image.get("layer") == "image-rpios", "RAVE OS must retain the single-system image layer")
    require(
        not ({"system_part_size", "data_part_size"} & image.keys()),
        "A/B or persistent-data partition settings require a separate architecture review",
    )
    boot_mib = partition_size_mib(image.get("boot_part_size"), "boot")
    system_mib = partition_size_mib(image.get("root_part_size"), "system")
    require(boot_mib == 512, "boot partition must be exactly 512 MiB")
    require(system_mib >= 12 * 1024, "system partition must be at least 12 GiB")
    return {
        "architecture": "single-system-mbr",
        "boot_partition_mib": boot_mib,
        "system_partition_mib": system_mib,
        "boot_filesystem_label": "BOOT",
        "system_filesystem_label": "ROOT",
        "boot_device_alias": "/dev/disk/by-slot/boot",
        "system_device_alias": "/dev/disk/by-slot/system",
        "persistent_data_partition": False,
        "automatic_expansion": True,
    }


def has_usable_shadow_password(password: str) -> bool:
    return SHADOW_PASSWORD_HASH.fullmatch(password) is not None


def verify_shadow_account_password(account: str, password: str) -> None:
    if account == "pi":
        require(
            has_usable_shadow_password(password),
            "pi must have a usable local console password",
        )
        return
    require(
        password.startswith(("!", "*")),
        f"account has usable credentials: {account}",
    )


def systemd_directives(text: str, section: str, key: str) -> list[str]:
    """Extract active unit directives after systemd has validated the unit syntax."""
    current_section = ""
    values: list[str] = []
    logical_line = ""
    for raw_line in text.splitlines():
        line = f"{logical_line}{raw_line.lstrip() if logical_line else raw_line}"
        if line.rstrip().endswith("\\"):
            logical_line = f"{line.rstrip()[:-1]} "
            continue
        logical_line = ""
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1]
            continue
        if current_section != section or "=" not in stripped:
            continue
        directive, value = stripped.split("=", 1)
        if directive.strip() == key:
            values.append(value.strip())
    require(not logical_line, f"unterminated systemd continuation in [{section}] {key}")
    return values


def effective_systemd_list(texts: tuple[str, ...], section: str, key: str) -> list[str]:
    values: list[str] = []
    for text in texts:
        for value in systemd_directives(text, section, key):
            if value:
                values.append(value)
            else:
                values.clear()
    return values


def effective_systemd_words(texts: tuple[str, ...], section: str, key: str) -> list[str]:
    values: list[str] = []
    for text in texts:
        for value in systemd_directives(text, section, key):
            if not value:
                values.clear()
            else:
                values.extend(shlex.split(value))
    return values


def effective_systemd_scalar(texts: tuple[str, ...], section: str, key: str) -> str | None:
    values = [value for text in texts for value in systemd_directives(text, section, key)]
    return values[-1] if values else None


def read_ini(path: Path, description: str) -> configparser.ConfigParser:
    profile = configparser.ConfigParser(interpolation=None)
    try:
        loaded = profile.read(path, encoding="utf-8")
    except configparser.Error as error:
        raise VerificationError(f"invalid {description} structure: {error}") from error
    require(loaded == [str(path)], f"{description} could not be read")
    return profile


def target_accounts(rootfs: Path) -> tuple[int, int]:
    passwd = (rootfs / "etc/passwd").read_text(encoding="utf-8")
    group = (rootfs / "etc/group").read_text(encoding="utf-8")
    rave_line = next((line for line in passwd.splitlines() if line.startswith("rave:")), "")
    group_line = next((line for line in group.splitlines() if line.startswith("rave:")), "")
    require(bool(rave_line), "missing rave user")
    require(bool(group_line), "missing rave group")
    fields = rave_line.split(":")
    require(fields[5:] == ["/var/lib/rave", "/usr/sbin/nologin"], "invalid rave account contract")
    return int(fields[2]), int(group_line.split(":")[2])


def iter_sensitive_files(rootfs: Path):
    roots = [rootfs / name for name in ("etc", "opt/rave", "var/lib/rave", "var/log/rave", "root", "home")]
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024:
                yield path


def verify_clone_safety(rootfs: Path) -> None:
    machine_id = rootfs / "etc/machine-id"
    require(machine_id.is_file() and machine_id.stat().st_size == 0, "machine-id is initialized")
    require(not (rootfs / "var/lib/dbus/machine-id").exists(), "D-Bus machine-id is cloned")
    require(not list((rootfs / "etc/ssh").glob("ssh_host_*")), "SSH host key is present")
    allowed_authorized_keys = rootfs / "home/pi/.ssh/authorized_keys"
    for base in (rootfs / "root", rootfs / "home"):
        if base.exists():
            unexpected_authorized_keys = [
                path
                for path in base.rglob("authorized_keys")
                if path != allowed_authorized_keys and path.stat().st_size
            ]
            require(not unexpected_authorized_keys, "unreviewed SSH authorized key is present")
            require(
                not any(
                    next(base.rglob(name), None) is not None
                    for name in ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
                ),
                "developer SSH private key is present",
            )
    nm = rootfs / "etc/NetworkManager/system-connections"
    profiles = sorted(path.name for path in nm.iterdir()) if nm.exists() else []
    require(profiles in ([], [ALLOWED_NM_PROFILE]), f"unexpected NetworkManager profiles: {profiles}")
    for relative in ("var/lib/rave/identity", "var/lib/rave/pairing", "var/lib/rave/session"):
        require(not (rootfs / relative).exists(), f"cloned RAVE state present: /{relative}")
    shadow = (rootfs / "etc/shadow").read_text(encoding="utf-8")
    for line in shadow.splitlines():
        account, password, *_ = line.split(":")
        verify_shadow_account_password(account, password)
    require(re.search(r"^pi:", shadow, re.MULTILINE) is not None, "pi shadow entry is missing")
    require(not any((rootfs / "var/log/rave").iterdir()), "RAVE logs are not empty")
    for relative in ("var/log", "var/cache"):
        base = rootfs / relative
        require(not any(path.is_file() for path in base.rglob("*")), f"carried files present in /{relative}")

    denylist = [value for value in os.environ.get("RAVE_ARTIFACT_DENYLIST", "").splitlines() if len(value) >= 5]
    violations: list[str] = []
    for path in iter_sensitive_files(rootfs):
        data = path.read_bytes()
        relative = "/" + str(path.relative_to(rootfs))
        if PRIVATE_KEY_MARKER.search(data):
            violations.append(f"private-key marker in {relative}")
        if GITHUB_TOKEN.search(data) or TOKEN_ASSIGNMENT.search(data):
            violations.append(f"token or credential in {relative}")
        if contains_wifi_credential(data):
            violations.append(f"Wi-Fi credential in {relative}")
        if path.name not in {"passwd", "passwd-"} and HOME_PATH.search(data):
            violations.append(f"developer home path in {relative}")
        for value in denylist:
            if value.encode() in data:
                violations.append(f"injected build identity in {relative}")
    require(not violations, "; ".join(violations[:20]))


def verify_gate2b_us_regulatory_domain(rootfs: Path) -> None:
    regulatory = (rootfs / "etc/modprobe.d/cfg80211_regdomain.conf").read_text(
        encoding="utf-8"
    )
    require(
        regulatory.strip() == "options cfg80211 ieee80211_regdom=US",
        "Wi-Fi regulatory domain is not explicitly US",
    )
    require("ieee80211_regdom=GB" not in regulatory, "Wi-Fi regulatory domain fell back to GB")


def unit_dropins(rootfs: Path, unit: str) -> list[Path]:
    paths: list[Path] = []
    for base in (rootfs / "usr/lib/systemd/system", rootfs / "etc/systemd/system"):
        directory = base / f"{unit}.d"
        if directory.is_dir():
            paths.extend(sorted(directory.glob("*.conf")))
    return paths


def verify_management_profile(profile_path: Path) -> str:
    require(profile_path.is_file(), "RAVE-Setup profile is missing")
    require(stat.S_IMODE(profile_path.stat().st_mode) == 0o600, "RAVE-Setup profile permissions are unsafe")
    profile = read_ini(profile_path, "NetworkManager keyfile")
    require(profile.get("connection", "id") == "RAVE-Setup", "wrong provisioning profile id")
    require(
        profile.get("connection", "uuid") == "0fc02a7e-795a-4e05-8952-9ea47f31f695",
        "wrong provisioning profile UUID",
    )
    require(profile.get("connection", "type") == "wifi", "provisioning profile is not Wi-Fi")
    require(profile.get("connection", "interface-name") == "wlan0", "AP is not scoped to wlan0")
    require(
        not profile.getboolean("connection", "autoconnect", fallback=True),
        "AP profile autoconnect may race the canonical network state service",
    )
    require(
        profile.getint("connection", "autoconnect-priority") == 100,
        "AP autoconnect priority changed",
    )
    require(
        profile.getint("connection", "wait-device-timeout") == 15000,
        "AP device wait is not explicitly bounded to 15000 ms",
    )
    require(profile.get("wifi", "ssid") == "RAVE-Setup", "wrong provisioning SSID")
    require(profile.get("wifi", "mode") == "ap", "provisioning profile is not an AP")
    require(profile.get("ipv4", "method") == "manual", "AP must use manual IPv4")
    require(profile.get("ipv4", "address1") == "192.168.77.1/24", "wrong management address/subnet")
    require(profile.getboolean("ipv4", "never-default"), "AP may install a default route")
    require(not profile.getboolean("ipv4", "may-fail"), "AP IPv4 configuration is optional")
    require(
        not profile.has_option("ipv4", "gateway"),
        "AP keyfile contains a gateway property; an empty gateway is invalid on the target",
    )
    route_options = sorted(option for option, _ in profile.items("ipv4") if option.startswith("route"))
    require(not route_options, f"AP keyfile contains explicit IPv4 route settings: {route_options}")
    require(not profile.has_option("ipv4", "dns"), "AP keyfile configures IPv4 DNS servers")
    require(not profile.get("ipv4", "dns-search", fallback=""), "AP keyfile configures DNS search domains")
    require(profile.get("ipv6", "method") == "disabled", "AP IPv6 is not disabled")
    require(not profile.has_section("wifi-security"), "provisioning profile contains Wi-Fi security material")
    profile_text = profile_path.read_text(encoding="utf-8")
    require("method=shared" not in profile_text, "NetworkManager shared/NAT mode is forbidden")
    require("bridge" not in profile_text.lower(), "management profile configures a bridge")
    return profile_text


def verify_dnsmasq_configuration(path: Path) -> str:
    require(path.is_file(), "RAVE dnsmasq configuration is missing")
    text = path.read_text(encoding="utf-8")
    directives: dict[str, list[str | None]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            parsed_value: str | None = value.strip()
        else:
            key, parsed_value = line, None
        directives.setdefault(key.strip(), []).append(parsed_value)

    require("log-dhcp" not in directives, "verbose or invalid log-dhcp directive is configured")
    expected_keys = {
        "interface",
        "listen-address",
        "bind-interfaces",
        "port",
        "dhcp-range",
        "dhcp-option",
        "dhcp-leasefile",
    }
    require(set(directives) == expected_keys, f"unexpected dnsmasq directives: {sorted(set(directives) - expected_keys)}")
    require(directives["interface"] == ["wlan0"], "DHCP is not restricted to wlan0")
    require(directives["listen-address"] == ["192.168.77.1"], "DHCP has the wrong listen address")
    require(directives["bind-interfaces"] == [None], "dnsmasq interface binding is not flag-style and exclusive")
    require(directives["port"] == ["0"], "dnsmasq DNS service is not disabled")
    require(
        directives["dhcp-range"]
        == ["192.168.77.100,192.168.77.199,255.255.255.0,12h"],
        "management DHCP range changed",
    )
    require(directives["dhcp-option"] == ["3", "6"], "DHCP advertises a router or DNS server")
    require(
        directives["dhcp-leasefile"] == ["/var/lib/misc/dnsmasq.leases"],
        "DHCP lease database path changed",
    )
    require("eth0" not in text, "DHCP listens on runtime Ethernet")
    return text


def verify_dhcp_service(rootfs: Path, unit_path: Path) -> str:
    require(unit_path.is_file(), "RAVE DHCP service is missing")
    dropins = unit_dropins(rootfs, "rave-management-dhcp.service")
    require(not dropins, f"unexpected DHCP service drop-ins obscure the canonical sandbox: {dropins}")
    unit = unit_path.read_text(encoding="utf-8")
    texts = (unit,)
    require(
        effective_systemd_scalar(texts, "Service", "ProtectSystem") == "strict",
        "DHCP must retain ProtectSystem=strict",
    )
    require(
        effective_systemd_words(texts, "Service", "ReadWritePaths") == ["/var/lib/misc"],
        "DHCP writable paths must be exactly /var/lib/misc",
    )
    exec_starts = systemd_directives(unit, "Service", "ExecStart")
    require(len(exec_starts) == 1, "DHCP service must have one canonical ExecStart")
    command = shlex.split(exec_starts[0])
    require(command and command[0] == "/usr/sbin/dnsmasq", "DHCP service does not execute dnsmasq")
    require(
        "--conf-file=/etc/rave/network/dnsmasq.conf" in command
        and "--no-hosts" in command
        and "--no-resolv" in command,
        "DHCP service does not use only the product configuration",
    )
    lease_directory = rootfs / "var/lib/misc"
    require(lease_directory.is_dir() and not lease_directory.is_symlink(), "DHCP lease directory is missing or unsafe")
    lease_stat = lease_directory.stat()
    require(
        (stat.S_IMODE(lease_stat.st_mode), lease_stat.st_uid, lease_stat.st_gid) == (0o755, 0, 0),
        "DHCP lease directory must be root-owned mode 0755",
    )
    require(
        not (lease_directory / "dnsmasq.leases").exists(),
        "generic image carries a DHCP lease database",
    )
    return unit


def verify_web_service(rootfs: Path, unit_path: Path, socket_path: Path) -> tuple[str, str]:
    require(unit_path.is_file(), "rave-webd service is missing")
    require(socket_path.is_file(), "rave-webd socket is missing")
    dropins = unit_dropins(rootfs, "rave-webd.service")
    require(not dropins, f"unexpected rave-webd drop-ins obscure listener policy: {dropins}")
    socket_dropins = unit_dropins(rootfs, "rave-webd.socket")
    require(
        not socket_dropins,
        f"unexpected rave-webd socket drop-ins obscure listener policy: {socket_dropins}",
    )
    unit = unit_path.read_text(encoding="utf-8")
    socket_unit = socket_path.read_text(encoding="utf-8")
    exec_starts = systemd_directives(unit, "Service", "ExecStart")
    require(len(exec_starts) == 1, "rave-webd must have one canonical ExecStart")
    command = shlex.split(exec_starts[0])
    require(command.count("--fd") == 1, "rave-webd must consume exactly one inherited socket")
    fd_index = command.index("--fd")
    require(command[fd_index + 1] == "3", "rave-webd inherited socket descriptor changed")
    require(
        not {"--host", "--port", "--uds"}.intersection(command),
        "rave-webd may not create an additional listener",
    )
    socket_texts = (socket_unit,)
    socket_dependencies = {
        target
        for directive in ("Requires", "Wants", "After", "Before", "PartOf")
        for target in effective_systemd_words(socket_texts, "Unit", directive)
    }
    require(
        "NetworkManager.service" not in socket_dependencies,
        "rave-webd socket creates a NetworkManager/sockets.target ordering cycle",
    )
    require(
        effective_systemd_list(socket_texts, "Socket", "ListenStream") == ["8080"],
        "rave-webd socket port changed",
    )
    require(
        effective_systemd_scalar(socket_texts, "Socket", "BindToDevice") == "wlan0",
        "rave-webd socket is not bound exclusively to wlan0",
    )
    require(
        effective_systemd_scalar(socket_texts, "Socket", "Service") == "rave-webd.service",
        "rave-webd socket activates an unexpected service",
    )
    require("RAVE_PROVIDER=pi" in systemd_directives(unit, "Service", "Environment"), "rave-webd does not explicitly select the Pi provider")
    require(
        effective_systemd_scalar((unit,), "Service", "User") == "rave"
        and effective_systemd_scalar((unit,), "Service", "Group") == "rave",
        "rave-webd service identity changed",
    )
    require(effective_systemd_scalar((unit,), "Service", "NoNewPrivileges") == "true", "rave-webd privilege boundary changed")
    require(
        effective_systemd_scalar((unit,), "Service", "ProtectClock") == "true",
        "rave-webd may alter the appliance clock",
    )
    require(
        effective_systemd_scalar((unit,), "Service", "RestrictAddressFamilies") == "AF_UNIX",
        "rave-webd may create non-local network sockets",
    )
    require(not systemd_directives(unit, "Service", "RuntimeDirectory"), "rave-webd owns a shared runtime directory")
    require(
        effective_systemd_words((unit,), "Unit", "Requires") == ["rave-webd.socket"],
        "rave-webd service does not require only its socket boundary",
    )
    socket_enablement = rootfs / "etc/systemd/system/sockets.target.wants/rave-webd.socket"
    require(socket_enablement.is_symlink(), "rave-webd socket is not enabled at boot")
    require(
        os.readlink(socket_enablement) == "/usr/lib/systemd/system/rave-webd.socket",
        "unexpected rave-webd socket enablement target",
    )
    return unit, socket_unit


def verify_mdns_discovery(rootfs: Path, package_status: str) -> str:
    stanza = next(
        (
            block
            for block in package_status.split("\n\n")
            if block.startswith("Package: avahi-daemon\n")
        ),
        "",
    )
    require("Status: install ok installed\n" in f"{stanza}\n", "missing mDNS responder package")
    require((rootfs / "usr/sbin/avahi-daemon").is_file(), "Avahi responder binary is missing")

    policy_path = rootfs / "etc/rave/avahi-daemon.conf"
    require(policy_path.is_file() and not policy_path.is_symlink(), "Avahi policy is missing")
    policy = read_ini(policy_path, "Avahi mDNS policy")
    require(policy.get("server", "host-name", fallback="") == "rave-pi", "mDNS hostname changed")
    require(policy.get("server", "domain-name", fallback="") == "local", "mDNS domain changed")
    require(
        policy.get("server", "allow-interfaces", fallback="") == "wlan0",
        "mDNS is not scoped exclusively to wlan0",
    )
    require(policy.getboolean("publish", "publish-addresses", fallback=False), "mDNS address publication is disabled")
    require(not policy.getboolean("reflector", "enable-reflector", fallback=True), "mDNS reflection is enabled")

    service_path = rootfs / "usr/lib/systemd/system/avahi-daemon.service"
    require(service_path.is_file(), "Avahi responder service is missing")
    dropins = unit_dropins(rootfs, "avahi-daemon.service")
    require(len(dropins) == 1, f"unexpected Avahi service drop-ins: {dropins}")
    service_texts = (
        service_path.read_text(encoding="utf-8"),
        dropins[0].read_text(encoding="utf-8"),
    )
    require(
        effective_systemd_list(service_texts, "Service", "ExecStart")
        == ["/usr/sbin/avahi-daemon -s -f /etc/rave/avahi-daemon.conf"],
        "Avahi responder does not use the RAVE management-only policy",
    )

    service_want = rootfs / "etc/systemd/system/multi-user.target.wants/avahi-daemon.service"
    socket_want = rootfs / "etc/systemd/system/sockets.target.wants/avahi-daemon.socket"
    require(service_want.is_symlink(), "Avahi responder service is not enabled")
    require(socket_want.is_symlink(), "Avahi responder socket is not enabled")
    require(
        os.readlink(service_want) == "/usr/lib/systemd/system/avahi-daemon.service"
        and os.readlink(socket_want) == "/usr/lib/systemd/system/avahi-daemon.socket",
        "unexpected Avahi enablement target",
    )
    return policy_path.read_text(encoding="utf-8")


def verify_networkd_service(rootfs: Path, unit_path: Path) -> str:
    require(unit_path.is_file(), "rave-networkd service is missing")
    require(not unit_dropins(rootfs, "rave-networkd.service"), "rave-networkd has unexpected drop-ins")
    unit = unit_path.read_text(encoding="utf-8")
    texts = (unit,)
    require(
        effective_systemd_scalar(texts, "Service", "User") == "root"
        and effective_systemd_scalar(texts, "Service", "Group") == "rave",
        "rave-networkd service identity changed",
    )
    require(
        systemd_directives(unit, "Service", "ExecStart")
        == ["/usr/bin/python3 -m rave_networkd"],
        "rave-networkd does not execute only the canonical daemon",
    )
    required_scalars = {
        "NoNewPrivileges": "true",
        "ProtectSystem": "strict",
        "ProtectClock": "true",
        "PrivateDevices": "true",
        "RestrictAddressFamilies": "AF_UNIX",
        "LimitCORE": "0",
    }
    for directive, expected in required_scalars.items():
        require(
            effective_systemd_scalar(texts, "Service", directive) == expected,
            f"rave-networkd hardening changed: {directive}",
        )
    require(
        effective_systemd_words(texts, "Service", "ReadWritePaths") == ["/run/rave"],
        "rave-networkd writable paths are not restricted to /run/rave",
    )
    require(
        effective_systemd_words(texts, "Service", "CapabilityBoundingSet") == [],
        "rave-networkd has ambient Linux capabilities",
    )
    source = rootfs / "opt/rave/management/rave_networkd/backend.py"
    require(source.is_file(), "rave-networkd backend is missing")
    backend = source.read_text(encoding="utf-8")
    for expected in (
        'INTERFACE = "wlan0"',
        'PROVISIONING_PROFILE = "RAVE-Setup"',
        'SAVED_PROFILE = "RAVE-Management"',
        'PREVIOUS_PROFILE = "RAVE-Management-Previous"',
        "run_with_secret",
        "os.memfd_create",
        'SYSTEMCTL = "/usr/bin/systemctl"',
    ):
        require(expected in backend, f"rave-networkd fixed operation contract changed: {expected}")
    require(
        "shell=true" not in backend.lower(),
        "rave-networkd contains forbidden behavior: shell=True",
    )
    for forbidden in ("eth0", "ip_forward", "masquerade"):
        require(forbidden not in backend.lower(), f"rave-networkd contains forbidden behavior: {forbidden}")
    require(
        re.search(r'"connection\.autoconnect",\s*"no"', backend) is not None
        and re.search(r'"connection\.autoconnect",\s*"yes"', backend) is None
        and "connection.autoconnect-retries" not in backend,
        "rave-networkd does not exclusively own management profile activation",
    )
    server = (rootfs / "opt/rave/management/rave_networkd/server.py").read_text(
        encoding="utf-8"
    )
    client = (rootfs / "opt/rave/management/rave_network_ipc/client.py").read_text(
        encoding="utf-8"
    )
    require(
        "SO_PEERCRED" in server and "peer_not_authorized" in server,
        "rave-networkd does not authenticate the local client peer",
    )
    require(
        "SO_PEERCRED" in client and "expected_server_uid: int = 0" in client,
        "rave-webd IPC client does not authenticate the root server peer",
    )
    return unit


def verify_management_install_ownership(rootfs: Path) -> None:
    tmpfiles = rootfs / "usr/lib/tmpfiles.d/rave.conf"
    require(
        tmpfiles.read_text(encoding="utf-8") == "d /run/rave 0750 root rave -\n",
        "RAVE runtime socket directory policy changed",
    )
    for relative in ("opt/rave/management", "opt/rave/web/rave_web"):
        base = rootfs / relative
        require(base.is_dir() and not base.is_symlink(), f"missing installed tree: /{relative}")
        for path in (base, *base.rglob("*")):
            require(not path.is_symlink(), f"installed management tree contains symlink: {path}")
            info = path.stat()
            require(
                (info.st_uid, info.st_gid) == (0, 0),
                f"installed management asset is not root-owned: {path}",
            )
            require(
                stat.S_IMODE(info.st_mode) & 0o022 == 0,
                f"installed management asset is group/world-writable: {path}",
            )


def verify_timekeeping(rootfs: Path) -> None:
    localtime = rootfs / "etc/localtime"
    require(localtime.is_symlink(), "RAVE OS timezone is not represented by a zoneinfo link")
    require(
        os.readlink(localtime) == "/usr/share/zoneinfo/Etc/UTC",
        "RAVE OS appliance timezone is not Etc/UTC",
    )
    package_status = (rootfs / "var/lib/dpkg/status").read_text(encoding="utf-8")
    stanza = next(
        (
            block
            for block in package_status.split("\n\n")
            if block.startswith("Package: systemd-timesyncd\n")
        ),
        "",
    )
    require("Status: install ok installed\n" in f"{stanza}\n", "systemd-timesyncd is missing")
    enabled = rootfs / "etc/systemd/system/sysinit.target.wants/systemd-timesyncd.service"
    require(enabled.is_symlink(), "systemd-timesyncd is not enabled")
    clock = rootfs / "var/lib/systemd/timesync/clock"
    require(clock.is_file(), "systemd last-known clock state is missing")


def verify_runtime_ethernet_configuration(rootfs: Path) -> tuple[str, str]:
    network_path = rootfs / "etc/systemd/network/10-rave-ethernet.network"
    require(network_path.is_file(), "RAVE runtime Ethernet networkd policy is missing")
    network_dropins = [
        path
        for base in (rootfs / "usr/lib/systemd/network", rootfs / "etc/systemd/network")
        if (directory := base / "10-rave-ethernet.network.d").is_dir()
        for path in sorted(directory.glob("*.conf"))
    ]
    require(not network_dropins, f"runtime Ethernet policy has unexpected drop-ins: {network_dropins}")
    etc_networks = sorted((rootfs / "etc/systemd/network").glob("*.network"))
    require(
        etc_networks == [network_path],
        f"unexpected administrator networkd policies may overlap runtime Ethernet: {etc_networks}",
    )
    network = read_ini(network_path, "systemd-networkd policy")
    require(network.sections() == ["Match", "Network"], "runtime Ethernet has unexpected sections")
    require(network.get("Match", "Name") == "eth0", "runtime Ethernet policy does not match eth0")
    expected_network = {
        "address": "10.77.0.1/24",
        "dhcp": "no",
        "linklocaladdressing": "no",
        "defaultrouteondevice": "no",
        "ipmasquerade": "no",
        "ipv6acceptra": "no",
    }
    actual_network = dict(network.items("Network"))
    require(actual_network == expected_network, f"runtime Ethernet policy changed: {actual_network}")
    network_text = network_path.read_text(encoding="utf-8")
    require("wlan0" not in network_text, "runtime Ethernet policy depends on management Wi-Fi")

    unmanaged_path = rootfs / "etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf"
    require(unmanaged_path.is_file(), "NetworkManager runtime exclusion is missing")
    unmanaged = read_ini(unmanaged_path, "NetworkManager configuration")
    require(
        unmanaged.sections() == ["keyfile"]
        and dict(unmanaged.items("keyfile")) == {"unmanaged-devices": "interface-name:eth0"},
        "NetworkManager may own runtime Ethernet",
    )
    for base in (rootfs / "usr/lib/NetworkManager/conf.d", rootfs / "etc/NetworkManager/conf.d"):
        if not base.is_dir():
            continue
        for path in base.glob("*.conf"):
            if path == unmanaged_path:
                continue
            require(
                "eth0" not in path.read_text(encoding="utf-8"),
                f"another NetworkManager configuration references eth0: {path}",
            )
    return network_text, unmanaged_path.read_text(encoding="utf-8")


def verify_engineering_ethernet_ssh(rootfs: Path) -> str:
    machine_id = rootfs / "etc/machine-id"
    require(
        machine_id.is_file() and machine_id.stat().st_size == 0,
        "engineering SSH host-key contract expects the clone-safe empty machine-id",
    )
    package_status = (rootfs / "var/lib/dpkg/status").read_text(encoding="utf-8")
    for package in ("openssh-server", "sudo"):
        stanza = next(
            (block for block in package_status.split("\n\n") if block.startswith(f"Package: {package}\n")),
            "",
        )
        require(
            "Status: install ok installed\n" in f"{stanza}\n",
            f"missing engineering SSH package: {package}",
        )

    socket_unit = rootfs / "usr/lib/systemd/system/ssh.socket"
    ssh_service = rootfs / "usr/lib/systemd/system/ssh.service"
    keygen_unit = rootfs / "usr/lib/systemd/system/sshd-keygen.service"
    rave_hostkeys_unit = rootfs / "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service"
    require(socket_unit.is_file(), "openssh-server ssh.socket is missing")
    require(ssh_service.is_file(), "openssh-server ssh.service is missing")
    require(keygen_unit.is_file(), "Debian first-boot SSH host-key generator is missing")
    require(rave_hostkeys_unit.is_file(), "RAVE engineering SSH host-key service is missing")
    require((rootfs / "usr/sbin/sshd").is_file(), "openssh-server daemon binary is missing")
    require((rootfs / "usr/bin/sudo").is_file(), "sudo executable is missing")
    service_dropin_path = rootfs / "etc/systemd/system/ssh.service.d/90-rave-hostkeys.conf"
    service_dropins = unit_dropins(rootfs, "ssh.service")
    require(
        service_dropins == [service_dropin_path],
        f"unexpected ssh.service drop-ins obscure the engineering SSH contract: {service_dropins}",
    )
    hostkey_dropins = unit_dropins(rootfs, "rave-engineering-ssh-hostkeys.service")
    require(
        not hostkey_dropins,
        f"unexpected rave-engineering-ssh-hostkeys.service drop-ins obscure the engineering SSH contract: {hostkey_dropins}",
    )
    service_dropin = service_dropin_path.read_text(encoding="utf-8")
    require(
        effective_systemd_words((service_dropin,), "Unit", "Requires")
        == ["rave-engineering-ssh-hostkeys.service"],
        "ssh.service does not require RAVE engineering host-key generation",
    )
    require(
        effective_systemd_words((service_dropin,), "Unit", "After")
        == ["rave-engineering-ssh-hostkeys.service"],
        "ssh.service is not ordered after RAVE engineering host-key generation",
    )

    socket_dropin_path = rootfs / "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf"
    require(socket_dropin_path.is_file(), "engineering SSH socket override is missing")
    socket_dropins = unit_dropins(rootfs, "ssh.socket")
    require(
        socket_dropins == [socket_dropin_path],
        f"unexpected SSH socket drop-ins obscure listener policy: {socket_dropins}",
    )
    socket_dropin = socket_dropin_path.read_text(encoding="utf-8")
    require(
        "rave-engineering-ssh-hostkeys.service" not in socket_dropin,
        "ssh.socket incorrectly depends on the normal host-key service",
    )
    socket_unit_text = socket_unit.read_text(encoding="utf-8")
    socket_texts = (socket_unit_text, socket_dropin)
    listen_streams = effective_systemd_list(socket_texts, "Socket", "ListenStream")
    require(
        listen_streams == ["10.77.0.1:22"],
        "engineering SSH socket does not reset the wildcard and bind only 10.77.0.1:22",
    )
    require(
        effective_systemd_scalar(socket_texts, "Socket", "FreeBind") == "yes",
        "engineering SSH socket is missing FreeBind=yes",
    )
    bind_to_device = effective_systemd_scalar(socket_texts, "Socket", "BindToDevice")
    require(
        bind_to_device in (None, ""),
        "engineering SSH socket has device-lifetime coupling through BindToDevice",
    )

    socket_enablement = rootfs / "etc/systemd/system/sockets.target.wants/ssh.socket"
    require(socket_enablement.is_symlink(), "ssh.socket is not enabled at boot")
    require(os.readlink(socket_enablement) == "/usr/lib/systemd/system/ssh.socket", "unexpected ssh.socket enablement target")
    enabled_direct_services = sorted(
        str(path.relative_to(rootfs))
        for wants_dir in (rootfs / "etc/systemd/system").glob("*.target.wants")
        for path in wants_dir.iterdir()
        if path.is_symlink()
        and Path(os.readlink(path)).name in {"ssh.service", "sshd.service"}
    )
    require(
        not enabled_direct_services,
        f"ssh.service is directly enabled for normal boot: {enabled_direct_services}",
    )
    enabled_ssh_sockets = sorted(
        path.name
        for wants_dir in (rootfs / "etc/systemd/system").glob("*.target.wants")
        for path in wants_dir.glob("ssh*.socket")
        if path.is_symlink()
    )
    require(enabled_ssh_sockets == ["ssh.socket"], f"unexpected enabled SSH sockets: {enabled_ssh_sockets}")

    for relative in (
        "etc/systemd/system/ssh.socket.wants/sshd-keygen.service",
        "etc/systemd/system/ssh.service.wants/sshd-keygen.service",
    ):
        keygen_want = rootfs / relative
        require(
            not keygen_want.exists() and not keygen_want.is_symlink(),
            "SSH has a competing conditional host-key generator",
        )
    keygen = keygen_unit.read_text(encoding="utf-8")
    for expected in (
        "ConditionFirstBoot=yes",
        "ConditionPathIsReadWrite=/etc/ssh",
        "Before=ssh.service sshd.service sshd@.service",
        "ExecStart=ssh-keygen -A",
        "WantedBy=ssh.service sshd.service sshd@.service ssh.socket",
    ):
        require(expected in keygen, f"invalid Debian first-boot SSH host-key contract: {expected}")
    rave_hostkeys = rave_hostkeys_unit.read_text(encoding="utf-8")
    for expected in (
        "Before=ssh.service",
        "Type=oneshot",
        "ExecStart=/usr/bin/ssh-keygen -A",
        "RemainAfterExit=yes",
    ):
        require(expected in rave_hostkeys.splitlines(), f"invalid RAVE SSH host-key service: {expected}")
    active_rave_hostkey_lines = (
        line.strip()
        for line in rave_hostkeys.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    require(
        not any(line.startswith("Condition") for line in active_rave_hostkey_lines),
        "RAVE SSH host-key generation must not be conditionally skipped",
    )
    require(
        "ExecStartPre=/usr/sbin/sshd -t" in ssh_service.read_text(encoding="utf-8"),
        "socket-activated ssh.service does not validate host keys before starting",
    )
    require(not list((rootfs / "etc/ssh").glob("ssh_host_*")), "SSH host private key is baked into image")

    policy_path = rootfs / "etc/ssh/sshd_config.d/90-rave-ethernet.conf"
    require(policy_path.is_file(), "engineering sshd policy is missing")
    policy = policy_path.read_text(encoding="utf-8")
    main_sshd_config = (rootfs / "etc/ssh/sshd_config").read_text(encoding="utf-8")
    require(
        "Include /etc/ssh/sshd_config.d/*.conf" in main_sshd_config.splitlines(),
        "sshd does not include the engineering policy drop-in",
    )
    required_policy = (
        "PubkeyAuthentication yes",
        "PasswordAuthentication no",
        "KbdInteractiveAuthentication no",
        "ChallengeResponseAuthentication no",
        "PermitEmptyPasswords no",
        "PermitRootLogin no",
        "AllowUsers pi",
        "AllowTcpForwarding no",
        "GatewayPorts no",
        "X11Forwarding no",
        "PermitTunnel no",
        "AllowAgentForwarding no",
    )
    for expected in required_policy:
        require(expected in policy.splitlines(), f"missing engineering sshd policy: {expected}")
    for forbidden in (
        "PasswordAuthentication yes",
        "KbdInteractiveAuthentication yes",
        "ChallengeResponseAuthentication yes",
        "PermitRootLogin yes",
        "AllowUsers root",
    ):
        require(forbidden not in policy, f"unsafe engineering sshd policy: {forbidden}")
    sshd_config_paths = [rootfs / "etc/ssh/sshd_config"]
    sshd_config_paths.extend(sorted((rootfs / "etc/ssh/sshd_config.d").glob("*.conf")))
    sshd_configuration = "\n".join(
        path.read_text(encoding="utf-8") for path in sshd_config_paths if path.is_file()
    )
    active_sshd_lines = [
        line.strip()
        for line in sshd_configuration.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    for line in active_sshd_lines:
        normalized = " ".join(line.split()).lower()
        require(
            not normalized.startswith("listenaddress "),
            f"sshd listener policy must remain owned exclusively by ssh.socket: {line}",
        )

    passwd = {
        fields[0]: fields
        for line in (rootfs / "etc/passwd").read_text(encoding="utf-8").splitlines()
        if len(fields := line.split(":")) >= 7
    }
    shadow = {
        fields[0]: fields[1]
        for line in (rootfs / "etc/shadow").read_text(encoding="utf-8").splitlines()
        if len(fields := line.split(":")) >= 2
    }
    require("pi" in passwd and "pi" in shadow, "pi engineering account is missing")
    require(
        has_usable_shadow_password(shadow["pi"]),
        "pi must have a usable local console password",
    )
    require(passwd["pi"][6] not in {"/usr/sbin/nologin", "/bin/false"}, "pi has no administrative shell")

    key_path = rootfs / "home/pi/.ssh/authorized_keys"
    require(key_path.is_file() and not key_path.is_symlink(), "pi authorized_keys is missing")
    try:
        engineering_key = parse_public_key(key_path.read_text(encoding="utf-8"))
    except PublicKeyError as error:
        raise VerificationError(f"invalid pi engineering authorized key: {error}") from error
    pi_uid, pi_gid = int(passwd["pi"][2]), int(passwd["pi"][3])
    ssh_dir_stat = key_path.parent.stat()
    key_stat = key_path.stat()
    require(
        (stat.S_IMODE(ssh_dir_stat.st_mode), ssh_dir_stat.st_uid, ssh_dir_stat.st_gid)
        == (0o700, pi_uid, pi_gid),
        "wrong pi .ssh mode/ownership",
    )
    require(
        (stat.S_IMODE(key_stat.st_mode), key_stat.st_uid, key_stat.st_gid)
        == (0o600, pi_uid, pi_gid),
        "wrong pi authorized_keys mode/ownership",
    )

    sudoers_path = rootfs / "etc/sudoers.d/90-rave-engineering-ssh"
    require(sudoers_path.is_file() and not sudoers_path.is_symlink(), "engineering sudoers file is missing")
    require(
        sudoers_path.read_text(encoding="utf-8").strip() == "pi ALL=(ALL:ALL) NOPASSWD: ALL",
        "engineering sudoers policy is not exact",
    )
    sudoers_stat = sudoers_path.stat()
    require(
        (stat.S_IMODE(sudoers_stat.st_mode), sudoers_stat.st_uid, sudoers_stat.st_gid)
        == (0o440, 0, 0),
        "wrong engineering sudoers mode/ownership",
    )
    require(
        not (rootfs / "etc/sudoers.d/010_rpi-nopasswd").exists(),
        "builder-generated generic sudo policy is present",
    )
    groups = {
        fields[0]: fields
        for line in (rootfs / "etc/group").read_text(encoding="utf-8").splitlines()
        if len(fields := line.split(":")) >= 4
    }
    require("sudo" in groups, "sudo group is missing")
    sudo_members = {member for member in groups["sudo"][3].split(",") if member}
    require("pi" not in sudo_members, "pi retains generic sudo-group membership")
    require(int(passwd["pi"][3]) != int(groups["sudo"][2]), "sudo is pi's primary group")

    dependency_units = {
        "ssh.socket": socket_texts,
        "ssh.service": (ssh_service.read_text(encoding="utf-8"), service_dropin),
        "rave-engineering-ssh-hostkeys.service": (rave_hostkeys,),
    }
    forbidden_dependencies = {
        "rave-wifi-init.service",
        "rave-networkd.service",
        "rave-management-dhcp.service",
        "rave-webd.socket",
        "rave-webd.service",
        "NetworkManager.service",
        "NetworkManager-wait-online.service",
        "network-online.target",
    }
    for unit_name, texts in dependency_units.items():
        dependency_targets = {
            target
            for directive in ("Requires", "Wants", "After", "Before", "BindsTo", "PartOf")
            for target in effective_systemd_words(texts, "Unit", directive)
        }
        forbidden = sorted(dependency_targets.intersection(forbidden_dependencies))
        require(not forbidden, f"{unit_name} depends on the management stack: {forbidden}")
        device_dependencies = sorted(target for target in dependency_targets if target.endswith(".device"))
        require(
            not device_dependencies,
            f"{unit_name} has a device-lifetime dependency: {device_dependencies}",
        )
    return engineering_key.fingerprint


def verify_publishable_image_has_no_engineering_ssh(rootfs: Path) -> None:
    present = [relative for relative in ENGINEERING_SSH_ARTIFACTS if (rootfs / relative).exists()]
    require(
        not present,
        f"publishable image contains non-publishable Gate 2B engineering SSH assets: {present}",
    )


def verify_hailo_stack(rootfs: Path) -> None:
    kernel = "6.18.39+rpt-rpi-2712"
    kernel_version = "1:6.18.39-1+rpt1"
    version = "4.23.0"
    contract = {
        "RAVE_HAILO_ACCELERATOR": "HAILO8",
        "RAVE_HAILO_KERNEL_RELEASE": kernel,
        "RAVE_HAILO_KERNEL_PACKAGE_VERSION": kernel_version,
        "RAVE_HAILORT_VERSION": version,
        "RAVE_HAILO_PCIE_DRIVER_VERSION": version,
        "RAVE_HAILO_IMAGE_CONTRACT": "M2A",
    }
    compatibility = rootfs / "etc/rave/compatibility"
    require(not (compatibility / "HAILO_STACK_NOT_INTEGRATED").exists(),
            "obsolete Hailo placeholder remains")
    env = compatibility / "hailo-stack.env"
    require(env.is_file(), "missing Hailo compatibility contract")
    require(sorted(env.read_text().splitlines()) == sorted(f"{k}={v}" for k, v in contract.items()),
            "Hailo compatibility contract mismatch")
    status = rootfs / "var/lib/dpkg/status"
    require(status.is_file(), "missing package status for Hailo verification")
    packages = {}
    for block in status.read_text().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines()
                      if line and not line[0].isspace() and ": " in line)
        if "Package" in fields:
            packages[fields["Package"]] = fields
    for name, expected in {
        "linux-image-rpi-2712": kernel_version,
        "linux-headers-rpi-2712": kernel_version,
        f"linux-image-{kernel}": kernel_version,
        f"linux-headers-{kernel}": kernel_version,
        "hailort": version,
        "hailort-pcie-driver": version,
    }.items():
        fields = packages.get(name, {})
        require(fields.get("Status") == "install ok installed"
                and fields.get("Version") == expected,
                f"Hailo pinned package missing or mismatched: {name}")
        expected_arch = "all" if name == "hailort-pcie-driver" else "arm64"
        require(fields.get("Architecture") == expected_arch,
                f"Hailo package architecture mismatch: {name}")
    forbidden = ("dkms", "hailo-dkms", "hailo-all", "python3-hailort", "hailo-tappas",
                 "tappas", "hailo-model-zoo", "hailo-dataflow-compiler")
    for name, fields in packages.items():
        if fields.get("Status", "").endswith(" not-installed"):
            continue
        require(not any(name == item or name.startswith(item + "-") for item in forbidden),
                f"forbidden M2A package: {name}")
    modules = rootfs / f"lib/modules/{kernel}"
    matches = list(modules.rglob("hailo_pci.ko*"))
    expected_dir = modules / "kernel/drivers/misc"
    require(len(matches) == 1 and matches[0].parent == expected_dir
            and matches[0].is_file() and matches[0].stat().st_size > 0,
            "Hailo target module missing, empty, misplaced, or duplicated")
    dependencies = modules / "modules.dep"
    require(dependencies.is_file(), "missing Hailo target modules.dep")
    relative = matches[0].relative_to(modules).as_posix()
    require(any(line.startswith(relative + ":") for line in dependencies.read_text().splitlines()),
            "Hailo target module absent from modules.dep")
    firmware = rootfs / "lib/firmware/hailo"
    link = firmware / "hailo8_fw.bin"
    require(link.is_symlink() and os.readlink(link) == f"hailo8_fw.{version}.bin"
            and link.is_file() and link.stat().st_size > 0,
            "Hailo firmware link missing or mismatched")
    for relative in ("lib/udev/rules.d/51-hailo-udev.rules", "etc/modprobe.d/hailo_pci.conf"):
        path = rootfs / relative
        require(path.is_file() and path.stat().st_size > 0, f"missing Hailo configuration: {relative}")
    postinst = rootfs / "var/lib/dpkg/info/hailort-pcie-driver.postinst"
    require(postinst.is_file() and sha256(postinst)
            == "14ca5b281added9363b9a71db27bad0f7e91933cf70c78045a1bcaf48c0d785b",
            "Hailo vendor postinst was not restored")


def verify_model_store(rootfs: Path) -> None:
    store = rootfs / "opt/rave/models"
    require(store.exists(), "missing model store: /opt/rave/models")
    info = store.lstat()
    require(stat.S_ISDIR(info.st_mode), "model store must be a real directory")
    actual = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)
    require(actual == (0o755, 0, 0), "model store must be root-owned mode 0755")
    require(not any(store.iterdir()), "image model store must be empty")


def verify_rootfs(rootfs: Path) -> dict[str, object]:
    rootfs = rootfs.resolve(strict=True)
    require(rootfs != Path("/"), "refusing to verify host root")
    require((rootfs / "etc").is_dir() and (rootfs / "var").is_dir(), "implausible rootfs")
    verify_clone_safety(rootfs)
    verify_gate2b_us_regulatory_domain(rootfs)
    verify_timekeeping(rootfs)
    verify_hailo_stack(rootfs)
    verify_model_store(rootfs)
    engineering_key_fingerprint = verify_engineering_ethernet_ssh(rootfs)

    rave_uid, rave_gid = target_accounts(rootfs)
    required_modes = {
        "opt/rave": (0o755, 0, 0),
        "etc/rave": (0o755, 0, 0),
        "var/lib/rave": (0o750, rave_uid, rave_gid),
        "var/log/rave": (0o750, rave_uid, rave_gid),
    }
    for relative, expected in required_modes.items():
        path = rootfs / relative
        require(path.is_dir(), f"missing directory: /{relative}")
        info = path.stat()
        actual = (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)
        require(actual == expected, f"wrong mode/ownership for /{relative}: {actual} != {expected}")
    verify_management_install_ownership(rootfs)

    required_files = (
        "usr/libexec/rave/rave-model",
        "usr/lib/tmpfiles.d/rave.conf",
        "usr/lib/systemd/system/rave-networkd.service",
        "usr/lib/systemd/system/rave-webd.socket",
        "usr/lib/systemd/system/rave-webd.service",
        "usr/lib/systemd/system/rave-management-dhcp.service",
        "usr/lib/systemd/system/avahi-daemon.service.d/90-rave-management.conf",
        "opt/rave/management/rave_network_ipc/client.py",
        "opt/rave/management/rave_network_ipc/protocol.py",
        "opt/rave/management/rave_network_ipc/state.py",
        "opt/rave/management/rave_networkd/backend.py",
        "opt/rave/management/rave_networkd/controller.py",
        "opt/rave/management/rave_networkd/server.py",
        "opt/rave/web/rave_web/app.py",
        "opt/rave/web/rave_web/static/index.html",
        "opt/rave/web/rave_web/static/app.css",
        "opt/rave/web/rave_web/static/app.js",
        "opt/rave/web/rave_web/static/navigation.js",
        "usr/share/doc/rave-web/THIRD_PARTY_NOTICES.md",
        "usr/libexec/rave/rave-grow-rootfs",
        "usr/lib/systemd/system/rave-grow-rootfs.service",
        "etc/NetworkManager/system-connections/rave-setup.nmconnection",
        "etc/rave/network/dnsmasq.conf",
        "etc/rave/avahi-daemon.conf",
        "etc/sysctl.d/90-rave-network-isolation.conf",
        "etc/systemd/network/10-rave-ethernet.network",
        "etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf",
        "etc/NetworkManager/conf.d/20-rave-wifi-backend.conf",
        "opt/rave/web/rave_web/providers.py",
        "opt/rave/runtime/PERCEPTION_NOT_INTEGRATED",
        "var/lib/rave/update/UPDATE_SERVICE_NOT_INTEGRATED",
    )
    for relative in required_files:
        require((rootfs / relative).is_file(), f"missing expected file: /{relative}")
    require(not (rootfs / "opt/rave/web/WEB_PACKAGE_NOT_INSTALLED").exists(), "web install marker remains")
    for obsolete in (
        "usr/lib/systemd/system/rave-wifi-init.service",
        "usr/libexec/rave/rave-wifi-init",
        "etc/systemd/system/NetworkManager-wait-online.service.d/10-rave-wifi-init.conf",
    ):
        require(not (rootfs / obsolete).exists(), f"obsolete Wi-Fi initializer remains: /{obsolete}")

    package_status = (rootfs / "var/lib/dpkg/status").read_text(encoding="utf-8")
    for package in (
        "python3-fastapi",
        "python3-pydantic",
        "python3-uvicorn",
        "network-manager",
        "wpasupplicant",
        "dnsmasq-base",
        "cloud-guest-utils",
        "e2fsprogs",
        "util-linux",
    ):
        stanza = next(
            (block for block in package_status.split("\n\n") if block.startswith(f"Package: {package}\n")),
            "",
        )
        require(
            "Status: install ok installed\n" in f"{stanza}\n",
            f"missing runtime package: {package}",
        )

    web_unit_path = rootfs / "usr/lib/systemd/system/rave-webd.service"
    socket_path = rootfs / "usr/lib/systemd/system/rave-webd.socket"
    web_unit, web_socket = verify_web_service(rootfs, web_unit_path, socket_path)
    mdns_policy = verify_mdns_discovery(rootfs, package_status)
    networkd_unit = verify_networkd_service(
        rootfs, rootfs / "usr/lib/systemd/system/rave-networkd.service"
    )
    wants = rootfs / "etc/systemd/system/multi-user.target.wants"
    for service in (
        "rave-grow-rootfs.service",
        "rave-networkd.service",
        "NetworkManager.service",
        "systemd-networkd.service",
    ):
        require((wants / service).is_symlink(), f"service is not enabled at boot: {service}")
    grow_script = (rootfs / "usr/libexec/rave/rave-grow-rootfs").read_text(encoding="utf-8")
    grow_unit = (rootfs / "usr/lib/systemd/system/rave-grow-rootfs.service").read_text(
        encoding="utf-8"
    )
    for contract in (
        "/dev/disk/by-slot/system",
        "/dev/disk/by-slot/boot",
        "growpart",
        "resize2fs",
        "COMPLETION_PATH.unlink(missing_ok=True)",
        "verify_expanded_geometry",
        "verify_filesystem_size",
    ):
        require(contract in grow_script, f"ROOT expansion contract changed: {contract}")
    require(
        effective_systemd_scalar((grow_unit,), "Service", "ProtectSystem") == "full",
        "ROOT expansion requires ProtectSystem=full for online resize2fs",
    )
    require(
        effective_systemd_words((grow_unit,), "Unit", "After")
        == ["local-fs.target", "systemd-udev-settle.service"],
        "ROOT expansion prerequisite ordering changed",
    )
    require(
        "ExecStart=/usr/libexec/rave/rave-grow-rootfs" in grow_unit
        and "Type=oneshot" in grow_unit
        and effective_systemd_words((grow_unit,), "Unit", "Before")
        == ["rave-networkd.service"],
        "ROOT expansion boot ordering changed",
    )
    require(
        not (wants / "rave-webd.service").exists()
        and not (wants / "rave-management-dhcp.service").exists(),
        "socket-activated web or state-owned DHCP is also directly enabled",
    )
    require(
        not (
            rootfs
            / "etc/systemd/system/network-online.target.wants/NetworkManager-wait-online.service"
        ).exists(),
        "management networking unnecessarily gates network-online",
    )
    dhcp_unit = verify_dhcp_service(
        rootfs, rootfs / "usr/lib/systemd/system/rave-management-dhcp.service"
    )
    for unit_text, name in (
        (dhcp_unit, "DHCP"),
        (web_unit, "web"),
        (web_socket, "web socket"),
        (networkd_unit, "network daemon"),
    ):
        require(
            "network-online.target" not in unit_text
            and "NetworkManager-wait-online.service" not in unit_text,
            f"{name} depends on global network-online state",
        )
    require(not (rootfs / "etc/systemd/network/02-wlan0.network").exists(), "systemd-networkd also owns wlan0")
    require(not (rootfs / "etc/systemd/network/01-eth0.network").exists(), "unreviewed generated eth0 policy remains")
    iwd_mask = rootfs / "etc/systemd/system/iwd.service"
    require(iwd_mask.is_symlink() and os.readlink(iwd_mask) == "/dev/null", "standalone iwd is not masked")
    verify_runtime_ethernet_configuration(rootfs)
    wifi_backend = (rootfs / "etc/NetworkManager/conf.d/20-rave-wifi-backend.conf").read_text(
        encoding="utf-8"
    )
    require("wifi.backend=wpa_supplicant" in wifi_backend, "NetworkManager Wi-Fi backend is not explicit")
    require((rootfs / "usr/sbin/wpa_supplicant").is_file(), "wpa_supplicant backend binary is missing")

    profile_path = rootfs / "etc/NetworkManager/system-connections/rave-setup.nmconnection"
    profile_text = verify_management_profile(profile_path)

    dnsmasq = verify_dnsmasq_configuration(rootfs / "etc/rave/network/dnsmasq.conf")

    sysctl = (rootfs / "etc/sysctl.d/90-rave-network-isolation.conf").read_text(encoding="utf-8")
    require("net.ipv4.ip_forward=0" in sysctl, "IPv4 forwarding is not disabled")
    require("net.ipv6.conf.all.forwarding=0" in sysctl, "IPv6 forwarding is not disabled")
    network_text = (
        f"{profile_text}\n{dnsmasq}\n{sysctl}\n{web_unit}\n{web_socket}\n{networkd_unit}\n{mdns_policy}"
    ).lower()
    for forbidden in ("masquerade", "snat", "dnat", "iptables", "nft ", "0.0.0.0"):
        require(forbidden not in network_text, f"forbidden management exposure/NAT setting: {forbidden}")

    return {
        "status": "pass",
        "rootfs": str(rootfs),
        "engineering_ethernet_ssh": "enabled_key_only",
        "engineering_ethernet_ssh_address": "10.77.0.1:22",
        "engineering_ethernet_ssh_publishable": False,
        "engineering_ssh_public_key_fingerprint": engineering_key_fingerprint,
        "limitations": {
            "physical_hailo_detection_and_inference": "requires clean-image Raspberry Pi validation",
            "physical_wifi_ap_operation": "requires Raspberry Pi hardware validation",
            "station_scan_connect_and_saved_profile": "requires Raspberry Pi hardware validation",
            "station_failure_ap_recovery": "requires Raspberry Pi hardware validation",
            "networkmanager_target_profile_load": "requires clean-image Raspberry Pi boot validation",
            "dhcp_runtime_lease_write": "requires clean-image Raspberry Pi boot validation",
            "ssh_listener_reboot_persistence": "requires five consecutive clean-image boot cycles",
            "rtc_and_timesync_runtime_behavior": "requires clean-image Raspberry Pi validation",
        },
        "checks": {
            "hailo_m2a_offline_stack": "pass",
            "rave_account": "pass",
            "filesystem_contract": "pass",
            "full_device_root_expansion": "pass_requires_first_boot_validation",
            "web_content": "pass",
            "management_interface_only_webd": "pass",
            "web_not_exposed_on_eth0": "pass",
            "management_boot_enablement": "pass",
            "typed_network_privilege_boundary": "pass",
            "bounded_station_to_ap_recovery": "pass",
            "single_wlan_owner": "pass",
            "networkmanager_wifi_backend": "pass",
            "isolated_runtime_ethernet": "pass",
            "provisioning_ap_profile": "pass",
            "bounded_dhcp": "pass",
            "dhcp_strict_sandbox_and_lease_state": "pass",
            "no_bridge_forwarding_or_nat": "pass",
            "pi_provider_selected": "pass",
            "machine_id_uninitialized": "pass",
            "ssh_host_keys_absent": "pass",
            "rave_host_keys_independent_of_systemd_first_boot": "pass",
            "engineering_ethernet_ssh": "pass_non_publishable",
            "ssh_without_device_lifetime_coupling": "pass",
            "ssh_management_dependency_isolation": "pass",
            "only_reviewed_network_profile": "pass",
            "rave_private_state_absent": "pass",
            "identity_and_secret_scan": "pass",
            "gate2b_us_regulatory_domain": "pass",
            "utc_and_truthful_timekeeping_contract": "pass",
        },
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_provenance(args: argparse.Namespace) -> None:
    artifact = args.artifact.resolve(strict=True)
    require(artifact.is_file() and artifact.stat().st_size > 0, "provenance artifact is empty")
    storage_layout = verify_image_configuration(args.image_configuration)
    record = {
        "schema_version": 1,
        "rave_repository_commit": args.rave_commit,
        "rave_worktree_dirty": args.rave_dirty == "true",
        "rpi_image_gen": {"tag": args.builder_tag, "commit": args.builder_commit},
        "builder_container": args.container_image,
        "target": {"platform": "raspberry-pi-5", "architecture": "arm64"},
        "configuration": args.configuration,
        "storage_layout": storage_layout,
        "engineering_ssh_public_key_fingerprint": args.engineering_ssh_public_key_fingerprint,
        "build_timestamp_utc": datetime.now(UTC).isoformat(),
        "artifact": {
            "filename": artifact.name,
            "size_bytes": artifact.stat().st_size,
            "sha256": sha256(artifact),
        },
        "reproducibility": {
            "builder_source_pinned": True,
            "container_base_pinned": True,
            "package_repositories_snapshot_pinned": False,
            "bit_for_bit_reproducibility_claimed": False,
        },
    }
    args.write_provenance.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", type=Path)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--verify-image-configuration", type=Path)
    parser.add_argument("--write-provenance", type=Path)
    parser.add_argument("--rave-commit")
    parser.add_argument("--rave-dirty", choices=("true", "false"))
    parser.add_argument("--builder-tag")
    parser.add_argument("--builder-commit")
    parser.add_argument("--container-image")
    parser.add_argument("--configuration")
    parser.add_argument("--image-configuration", type=Path)
    parser.add_argument("--engineering-ssh-public-key-fingerprint")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.verify_image_configuration:
            print(json.dumps(verify_image_configuration(args.verify_image_configuration), sort_keys=True))
            return 0
        if args.write_provenance:
            required = (
                args.artifact,
                args.rave_commit,
                args.rave_dirty,
                args.builder_tag,
                args.builder_commit,
                args.container_image,
                args.configuration,
                args.image_configuration,
                args.engineering_ssh_public_key_fingerprint,
            )
            require(all(required), "missing provenance argument")
            write_provenance(args)
            return 0
        require(args.rootfs is not None, "--rootfs is required for verification")
        require(args.artifact is not None, "--artifact is required for verification")
        require(args.artifact.is_file() and args.artifact.stat().st_size > 0, "missing image artifact")
        with args.artifact.open("rb") as artifact_stream:
            require(artifact_stream.read(4) == b"\x28\xb5\x2f\xfd", "artifact is not zstd data")
        report = verify_rootfs(args.rootfs)
        report["artifact"] = {
            "filename": args.artifact.name,
            "size_bytes": args.artifact.stat().st_size,
            "sha256": sha256(args.artifact),
        }
        if args.report:
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 0
    except (OSError, VerificationError) as error:
        print(f"artifact verification failed: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
