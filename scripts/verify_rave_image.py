#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path

PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
GITHUB_TOKEN = re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")
TOKEN_ASSIGNMENT = re.compile(
    rb"(?:api[-_]?key|secret[-_]?key|access[-_]?token)\s*[:=]\s*[^\s#]{8,}",
    re.IGNORECASE,
)
WIFI_SECRET = re.compile(
    rb"(?:^|\s)(?:wifi[-_ ]?password|psk)\s*[:=]\s*[^\s#]+", re.IGNORECASE
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
ALLOWED_NM_PROFILE = "rave-setup.nmconnection"


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


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
    for base in (rootfs / "root", rootfs / "home"):
        if base.exists():
            require(
                not any(path.stat().st_size for path in base.rglob("authorized_keys")),
                "developer SSH key is present",
            )
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
        require(password.startswith(("!", "*")), f"account has usable cloned credentials: {account}")
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
        if WIFI_SECRET.search(data):
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


def verify_rootfs(rootfs: Path) -> dict[str, object]:
    rootfs = rootfs.resolve(strict=True)
    require(rootfs != Path("/"), "refusing to verify host root")
    require((rootfs / "etc").is_dir() and (rootfs / "var").is_dir(), "implausible rootfs")
    verify_clone_safety(rootfs)
    verify_gate2b_us_regulatory_domain(rootfs)

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

    required_files = (
        "usr/lib/tmpfiles.d/rave.conf",
        "usr/lib/systemd/system/rave-webd.service",
        "usr/lib/systemd/system/rave-management-dhcp.service",
        "usr/lib/systemd/system/rave-wifi-init.service",
        "usr/libexec/rave/rave-wifi-init",
        "etc/systemd/system/NetworkManager-wait-online.service.d/10-rave-wifi-init.conf",
        "opt/rave/web/rave_web/app.py",
        "opt/rave/web/rave_web/static/index.html",
        "opt/rave/web/rave_web/static/app.css",
        "opt/rave/web/rave_web/static/app.js",
        "usr/share/doc/rave-web/THIRD_PARTY_NOTICES.md",
        "etc/NetworkManager/system-connections/rave-setup.nmconnection",
        "etc/rave/network/dnsmasq.conf",
        "etc/sysctl.d/90-rave-network-isolation.conf",
        "etc/systemd/network/10-rave-ethernet.network",
        "etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf",
        "etc/NetworkManager/conf.d/20-rave-wifi-backend.conf",
        "opt/rave/web/rave_web/providers.py",
        "etc/rave/compatibility/HAILO_STACK_NOT_INTEGRATED",
        "opt/rave/runtime/PERCEPTION_NOT_INTEGRATED",
        "var/lib/rave/update/UPDATE_SERVICE_NOT_INTEGRATED",
    )
    for relative in required_files:
        require((rootfs / relative).is_file(), f"missing expected file: /{relative}")
    require(not (rootfs / "opt/rave/web/WEB_PACKAGE_NOT_INSTALLED").exists(), "web install marker remains")

    package_status = (rootfs / "var/lib/dpkg/status").read_text(encoding="utf-8")
    for package in (
        "python3-fastapi",
        "python3-pydantic",
        "python3-uvicorn",
        "network-manager",
        "wpasupplicant",
        "dnsmasq-base",
    ):
        stanza = next(
            (block for block in package_status.split("\n\n") if block.startswith(f"Package: {package}\n")),
            "",
        )
        require(
            "Status: install ok installed\n" in f"{stanza}\n",
            f"missing runtime package: {package}",
        )

    unit = (rootfs / "usr/lib/systemd/system/rave-webd.service").read_text(encoding="utf-8")
    require("--host 192.168.77.1" in unit, "rave-webd is not bound to the management address")
    require("RAVE_PROVIDER=pi" in unit, "rave-webd does not explicitly select the Pi provider")
    require("--host 0.0.0.0" not in unit and "--host eth0" not in unit, "unsafe web exposure")
    require("User=rave" in unit and "Group=rave" in unit, "rave-webd service identity changed")
    require("NoNewPrivileges=true" in unit, "rave-webd privilege boundary changed")
    require("RuntimeDirectory=" not in unit, "rave-webd owns a shared runtime directory")
    wifi_init_path = rootfs / "usr/libexec/rave/rave-wifi-init"
    wifi_init_stat = wifi_init_path.stat()
    require(
        (stat.S_IMODE(wifi_init_stat.st_mode), wifi_init_stat.st_uid, wifi_init_stat.st_gid)
        == (0o755, 0, 0),
        "RAVE Wi-Fi initialization helper has unsafe mode/ownership",
    )
    wifi_init = wifi_init_path.read_text(encoding="utf-8")
    for expected in (
        "NMCLI=/usr/bin/nmcli",
        "IP=/usr/bin/ip",
        "INTERFACE=wlan0",
        "CONNECTION=RAVE-Setup",
        "ADDRESS=192.168.77.1/24",
        '"$NMCLI" --wait 10 radio wifi on',
        '"$NMCLI" --wait 2 -t -f WIFI general',
        '[ "$radio_state" = enabled ]',
        '"$NMCLI" --wait 20 connection up id "$CONNECTION" ifname "$INTERFACE"',
        '"$IP" -4 -o address show dev "$INTERFACE"',
        'while [ "$attempt" -lt 10 ]',
    ):
        require(expected in wifi_init, f"invalid RAVE Wi-Fi initialization contract: {expected}")
    for forbidden in ("rfkill", "while true", "0.0.0.0", "eth0"):
        require(forbidden not in wifi_init, f"forbidden RAVE Wi-Fi initialization behavior: {forbidden}")
    wifi_init_unit = (rootfs / "usr/lib/systemd/system/rave-wifi-init.service").read_text(
        encoding="utf-8"
    )
    for expected in (
        "Requires=NetworkManager.service",
        "After=NetworkManager.service",
        "Before=NetworkManager-wait-online.service",
        "ExecStart=/usr/libexec/rave/rave-wifi-init",
        "TimeoutStartSec=60s",
        "Type=oneshot",
    ):
        require(expected in wifi_init_unit, f"invalid RAVE Wi-Fi initialization unit: {expected}")
    nm_wait_dropin = (
        rootfs
        / "etc/systemd/system/NetworkManager-wait-online.service.d/10-rave-wifi-init.conf"
    ).read_text(encoding="utf-8")
    require(
        "Requires=rave-wifi-init.service" in nm_wait_dropin
        and "After=rave-wifi-init.service" in nm_wait_dropin,
        "NetworkManager wait-online does not require completed RAVE Wi-Fi initialization",
    )
    wants = rootfs / "etc/systemd/system/multi-user.target.wants"
    for service in (
        "rave-webd.service",
        "rave-management-dhcp.service",
        "NetworkManager.service",
        "systemd-networkd.service",
    ):
        require((wants / service).is_symlink(), f"service is not enabled at boot: {service}")
    require(
        (rootfs / "etc/systemd/system/network-online.target.wants/NetworkManager-wait-online.service").is_symlink(),
        "NetworkManager wait-online is not enabled",
    )
    nm_wait = (rootfs / "usr/lib/systemd/system/NetworkManager-wait-online.service").read_text(
        encoding="utf-8"
    )
    require("Requires=NetworkManager.service" in nm_wait, "NM wait-online does not require NetworkManager")
    require("Before=network-online.target" in nm_wait, "NM wait-online does not gate network-online")
    require("ExecStart=/usr/bin/nm-online -s -q" in nm_wait, "NM startup completion is not awaited")
    dhcp_unit = (rootfs / "usr/lib/systemd/system/rave-management-dhcp.service").read_text(
        encoding="utf-8"
    )
    for consumer_unit, name in ((dhcp_unit, "DHCP"), (unit, "web")):
        require("Wants=network-online.target" in consumer_unit, f"{name} does not pull network-online")
        require("After=network-online.target NetworkManager-wait-online.service" in consumer_unit, f"{name} starts before AP activation settles")
        require(
            "Requires=rave-wifi-init.service" in consumer_unit
            and "rave-wifi-init.service" in consumer_unit.split("After=", 1)[1].splitlines()[0],
            f"{name} can start without successful RAVE Wi-Fi initialization",
        )
    require("Before=rave-webd.service" in dhcp_unit, "DHCP is not ordered before the web service")
    require(not (rootfs / "etc/systemd/network/02-wlan0.network").exists(), "systemd-networkd also owns wlan0")
    require(not (rootfs / "etc/systemd/network/01-eth0.network").exists(), "unreviewed generated eth0 policy remains")
    iwd_mask = rootfs / "etc/systemd/system/iwd.service"
    require(iwd_mask.is_symlink() and os.readlink(iwd_mask) == "/dev/null", "standalone iwd is not masked")
    runtime_network = (rootfs / "etc/systemd/network/10-rave-ethernet.network").read_text(encoding="utf-8")
    for expected in ("Name=eth0", "Address=10.77.0.1/24", "DHCP=no", "IPMasquerade=no"):
        require(expected in runtime_network, f"invalid runtime Ethernet policy: {expected}")
    for forbidden in ("Gateway=", "DNS=", "DHCPServer=yes"):
        require(forbidden not in runtime_network, f"runtime Ethernet has forbidden setting: {forbidden}")
    nm_unmanaged = (rootfs / "etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf").read_text(encoding="utf-8")
    require("unmanaged-devices=interface-name:eth0" in nm_unmanaged, "NetworkManager may own runtime Ethernet")
    wifi_backend = (rootfs / "etc/NetworkManager/conf.d/20-rave-wifi-backend.conf").read_text(
        encoding="utf-8"
    )
    require("wifi.backend=wpa_supplicant" in wifi_backend, "NetworkManager Wi-Fi backend is not explicit")
    require((rootfs / "usr/sbin/wpa_supplicant").is_file(), "wpa_supplicant backend binary is missing")

    profile_path = rootfs / "etc/NetworkManager/system-connections/rave-setup.nmconnection"
    require(stat.S_IMODE(profile_path.stat().st_mode) == 0o600, "RAVE-Setup profile permissions are unsafe")
    profile = configparser.ConfigParser(interpolation=None)
    profile.read(profile_path, encoding="utf-8")
    require(profile.get("connection", "id") == "RAVE-Setup", "wrong provisioning profile id")
    require(profile.get("connection", "interface-name") == "wlan0", "AP is not scoped to wlan0")
    require(profile.getboolean("connection", "autoconnect"), "AP profile is not enabled")
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
    require(not profile.get("ipv4", "gateway", fallback=""), "AP gateway must be empty")
    require(profile.get("ipv6", "method") == "disabled", "AP IPv6 is not disabled")
    require(not profile.has_section("wifi-security"), "provisioning profile contains Wi-Fi security material")
    profile_text = profile_path.read_text(encoding="utf-8")
    require("method=shared" not in profile_text, "NetworkManager shared/NAT mode is forbidden")
    require("bridge" not in profile_text.lower(), "management profile configures a bridge")

    dnsmasq = (rootfs / "etc/rave/network/dnsmasq.conf").read_text(encoding="utf-8")
    for expected in (
        "interface=wlan0",
        "listen-address=192.168.77.1",
        "bind-interfaces",
        "port=0",
        "dhcp-range=192.168.77.100,192.168.77.199,255.255.255.0,12h",
        "dhcp-option=3",
        "dhcp-option=6",
    ):
        require(expected in dnsmasq.splitlines(), f"missing bounded DHCP setting: {expected}")
    require("eth0" not in dnsmasq, "DHCP listens on runtime Ethernet")

    sysctl = (rootfs / "etc/sysctl.d/90-rave-network-isolation.conf").read_text(encoding="utf-8")
    require("net.ipv4.ip_forward=0" in sysctl, "IPv4 forwarding is not disabled")
    require("net.ipv6.conf.all.forwarding=0" in sysctl, "IPv6 forwarding is not disabled")
    network_text = f"{profile_text}\n{dnsmasq}\n{sysctl}\n{unit}".lower()
    for forbidden in ("masquerade", "snat", "dnat", "iptables", "nft ", "0.0.0.0"):
        require(forbidden not in network_text, f"forbidden management exposure/NAT setting: {forbidden}")

    return {
        "status": "pass",
        "rootfs": str(rootfs),
        "limitations": {
            "physical_wifi_ap_operation": "requires Raspberry Pi hardware validation",
        },
        "checks": {
            "rave_account": "pass",
            "filesystem_contract": "pass",
            "web_content": "pass",
            "management_address_only_webd": "pass",
            "web_not_exposed_on_eth0": "pass",
            "management_boot_enablement": "pass",
            "ap_web_boot_order": "pass",
            "wifi_initialization_static_contract": "pass",
            "single_wlan_owner": "pass",
            "networkmanager_wifi_backend": "pass",
            "isolated_runtime_ethernet": "pass",
            "provisioning_ap_profile": "pass",
            "bounded_dhcp": "pass",
            "no_bridge_forwarding_or_nat": "pass",
            "pi_provider_selected": "pass",
            "machine_id_uninitialized": "pass",
            "ssh_host_keys_absent": "pass",
            "only_reviewed_network_profile": "pass",
            "rave_private_state_absent": "pass",
            "identity_and_secret_scan": "pass",
            "gate2b_us_regulatory_domain": "pass",
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
    record = {
        "schema_version": 1,
        "rave_repository_commit": args.rave_commit,
        "rave_worktree_dirty": args.rave_dirty == "true",
        "rpi_image_gen": {"tag": args.builder_tag, "commit": args.builder_commit},
        "builder_container": args.container_image,
        "target": {"platform": "raspberry-pi-5", "architecture": "arm64"},
        "configuration": args.configuration,
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
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-provenance", type=Path)
    parser.add_argument("--rave-commit")
    parser.add_argument("--rave-dirty", choices=("true", "false"))
    parser.add_argument("--builder-tag")
    parser.add_argument("--builder-commit")
    parser.add_argument("--container-image")
    parser.add_argument("--configuration")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.write_provenance:
            required = (
                args.rave_commit,
                args.rave_dirty,
                args.builder_tag,
                args.builder_commit,
                args.container_image,
                args.configuration,
            )
            require(all(required), "missing provenance argument")
            write_provenance(args)
            return 0
        require(args.rootfs is not None, "--rootfs is required for verification")
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
