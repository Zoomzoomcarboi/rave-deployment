import base64
import os
import stat
import struct
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.engineering_ssh_key import PublicKeyError, parse_public_key
from scripts.verify_rave_image import VerificationError, verify_engineering_ethernet_ssh

ROOT = Path(__file__).resolve().parents[1]


def synthetic_key(comment: str = "rave-engineering-test-fixture") -> str:
    blob = struct.pack(">I", len(b"ssh-ed25519")) + b"ssh-ed25519"
    blob += struct.pack(">I", 32) + bytes(range(32))
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}\n"


KEY = synthetic_key()
PI_PASSWORD_HASH = "$6$rave-console-test$synthetic-password-hash"


def _write(root: Path, relative: str, content: str, mode: int = 0o644) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def ssh_rootfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "rootfs"
    _write(root, "etc/machine-id", "", 0o444)
    _write(
        root,
        "var/lib/dpkg/status",
        "Package: openssh-server\nStatus: install ok installed\n\n"
        "Package: sudo\nStatus: install ok installed\n",
    )
    _write(root, "usr/lib/systemd/system/ssh.socket", "[Socket]\nListenStream=22\nAccept=no\n")
    _write(
        root,
        "usr/lib/systemd/system/ssh.service",
        "[Unit]\nAfter=network.target\n\n"
        "[Service]\nExecStartPre=/usr/sbin/sshd -t\nExecStart=/usr/sbin/sshd -D\n",
    )
    _write(root, "usr/sbin/sshd", "synthetic executable\n", 0o755)
    _write(root, "usr/bin/sudo", "synthetic executable\n", 0o4755)
    _write(
        root,
        "usr/lib/systemd/system/sshd-keygen.service",
        "[Unit]\nConditionFirstBoot=yes\nConditionPathIsReadWrite=/etc/ssh\n"
        "Before=ssh.service sshd.service sshd@.service\n[Service]\nExecStart=ssh-keygen -A\n"
        "[Install]\nWantedBy=ssh.service sshd.service sshd@.service ssh.socket\n",
    )
    _write(
        root,
        "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service",
        (ROOT / "systemd/rave-engineering-ssh-hostkeys.service").read_text(),
    )
    service_policy = (ROOT / "systemd/ssh.service.d/90-rave-hostkeys.conf").read_text()
    _write(root, "etc/systemd/system/ssh.service.d/90-rave-hostkeys.conf", service_policy)
    socket_policy = (ROOT / "systemd/ssh.socket.d/90-rave-ethernet.conf").read_text()
    _write(root, "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf", socket_policy)
    sshd_policy = (
        ROOT / "image/overlays/etc/ssh/sshd_config.d/90-rave-ethernet.conf"
    ).read_text()
    _write(root, "etc/ssh/sshd_config", "Include /etc/ssh/sshd_config.d/*.conf\n")
    _write(root, "etc/ssh/sshd_config.d/90-rave-ethernet.conf", sshd_policy)
    socket_enablement = root / "etc/systemd/system/sockets.target.wants/ssh.socket"
    socket_enablement.parent.mkdir(parents=True)
    socket_enablement.symlink_to("/usr/lib/systemd/system/ssh.socket")
    uid, gid = os.getuid(), os.getgid()
    _write(root, "etc/passwd", f"pi:x:{uid}:{gid}::/home/pi:/bin/bash\n")
    _write(root, "etc/group", "sudo:x:27:\n")
    _write(root, "etc/shadow", f"pi:{PI_PASSWORD_HASH}:20000::::::\n", 0o640)
    key = _write(root, "home/pi/.ssh/authorized_keys", KEY, 0o600)
    key.parent.chmod(0o700)
    sudoers = _write(
        root,
        "etc/sudoers.d/90-rave-engineering-ssh",
        "pi ALL=(ALL:ALL) NOPASSWD: ALL\n",
        0o440,
    )

    original_stat = Path.stat

    def root_owned_sudoers(path: Path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == sudoers:
            values = list(result)
            values[stat.ST_UID] = 0
            values[stat.ST_GID] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", root_owned_sudoers)
    return root


def test_engineering_ssh_source_contract_is_exact_and_non_publishable() -> None:
    layer = (ROOT / "image/layer/rave-engineering-ssh.yaml").read_text()
    hook = (ROOT / "image/bdebstrap/customize85-rave-engineering-ssh").read_text()
    socket = (ROOT / "systemd/ssh.socket.d/90-rave-ethernet.conf").read_text()
    service = (ROOT / "systemd/ssh.service.d/90-rave-hostkeys.conf").read_text()
    policy = (ROOT / "image/overlays/etc/ssh/sshd_config.d/90-rave-ethernet.conf").read_text()
    assert "packages: [openssh-server, sudo]" in layer
    assert "non-publishable" in layer
    assert socket.splitlines() == [
        "[Socket]",
        "ListenStream=",
        "ListenStream=10.77.0.1:22",
        "FreeBind=yes",
    ]
    assert service.splitlines() == [
        "[Unit]",
        "Requires=rave-engineering-ssh-hostkeys.service",
        "After=rave-engineering-ssh-hostkeys.service",
    ]
    assert "BindToDevice=" not in socket
    assert "PubkeyAuthentication yes" in policy
    assert "PasswordAuthentication no" in policy
    assert "KbdInteractiveAuthentication no" in policy
    assert "PermitRootLogin no" in policy
    assert "AllowUsers pi" in policy
    assert "AllowTcpForwarding no" in policy
    assert "AllowAgentForwarding no" in policy
    assert 'test -x "$rootfs/usr/sbin/chpasswd"' in hook
    assert "printf '%s\\n' 'pi:debug'" in hook
    assert 'chroot "$rootfs" /usr/sbin/chpasswd' in hook
    assert "usermod --password" not in hook
    assert "chpasswd -e" not in hook
    assert "/etc/shadow" not in hook
    assert "RAVE_CONSOLE" not in hook
    assert "password-file" not in hook
    assert "debug" not in policy
    assert 'rm -f -- "$rootfs/etc/sudoers.d/010_rpi-nopasswd"' in hook
    assert "/usr/sbin/deluser pi sudo" in hook
    assert "/usr/sbin/visudo -cf /etc/sudoers" in hook
    assert "multi-user.target.wants/ssh.service" in hook
    assert "sockets.target.wants/ssh.socket" in hook
    assert '"$rootfs/etc/systemd/system/ssh.service.wants/sshd-keygen.service"' in hook
    assert '"$rootfs/etc/systemd/system/ssh.socket.wants/sshd-keygen.service"' in hook
    assert "rave-engineering-ssh-hostkeys.service" in hook
    assert "IGconf_rave_ssh_public_key" in hook
    assert "engineering_ssh_key.py" in hook
    assert "build-supplied ED25519 public key" in hook
    assert "NetworkManager" not in socket + service + policy
    assert "wlan0" not in socket + service + policy
    assert "network-online.target" not in socket + service + policy
    assert not (ROOT / "image/overlays/home/pi/.ssh/authorized_keys").exists()
    assert (ROOT / "image/overlays/etc/sudoers.d/90-rave-engineering-ssh").read_text() == (
        "pi ALL=(ALL:ALL) NOPASSWD: ALL\n"
    )


def test_artifact_verifier_accepts_exact_engineering_ssh_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify_engineering_ethernet_ssh(ssh_rootfs(tmp_path, monkeypatch))


def test_public_key_validation_is_ed25519_only_and_returns_a_fingerprint() -> None:
    key = parse_public_key(KEY)
    assert key.normalized == KEY.strip()
    assert key.fingerprint.startswith("SHA256:")
    with pytest.raises(PublicKeyError, match="ssh-ed25519"):
        parse_public_key("ssh-rsa AAAA test\n")
    with pytest.raises(PublicKeyError):
        parse_public_key("-----BEGIN OPENSSH" + " PRIVATE KEY-----\n")


def test_engineering_build_requires_external_public_key_input() -> None:
    build = (ROOT / "scripts/build-rave-os.sh").read_text(encoding="utf-8")
    assert "RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE" in build
    assert "engineering_ssh_key.py" in build
    assert "IGconf_rave_ssh_public_key" in build
    forbidden = ("rave-pi-debug", "rave-pi-z890", "HMmFYGS", "wcUdqe9")
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for base in (ROOT / "image", ROOT / "scripts")
        for path in base.rglob("*")
        if path.is_file() and "build" not in path.parts
    )
    assert all(value not in source for value in forbidden)


def test_engineering_build_fails_before_build_tools_when_key_is_missing(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE", None)
    result = subprocess.run(
        [str(ROOT / "scripts/build-rave-os.sh"), str(tmp_path / "output")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 2
    assert "RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE is required" in result.stderr


def test_engineering_build_rejects_malformed_public_key_before_build_tools(
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "engineering.pub"
    malformed.write_text("-----BEGIN OPENSSH" + " PRIVATE KEY-----\n", encoding="utf-8")
    environment = os.environ.copy()
    environment["RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE"] = str(malformed)
    result = subprocess.run(
        [str(ROOT / "scripts/build-rave-os.sh"), str(tmp_path / "output")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 2
    assert "invalid engineering public key" in result.stderr


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ("ListenStream=22", "reset the wildcard"),
        ("ListenStream=0.0.0.0:22", "reset the wildcard"),
        ("ListenStream=[::]:22", "reset the wildcard"),
        ("FreeBind=no", "FreeBind"),
        ("BindToDevice=eth0", "device-lifetime coupling"),
        ("BindToDevice=wlan0", "device-lifetime coupling"),
    ),
)
def test_artifact_verifier_rejects_unsafe_ssh_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
    message: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    dropin = root / "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf"
    lines = dropin.read_text().splitlines()
    if replacement.startswith("ListenStream"):
        first_listener = lines.index("ListenStream=")
        lines[first_listener : first_listener + 2] = [replacement]
    elif replacement.startswith("FreeBind"):
        lines[lines.index("FreeBind=yes")] = replacement
    else:
        lines.append(replacement)
    dropin.write_text("\n".join(lines) + "\n")
    with pytest.raises(VerificationError, match=message):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ("PasswordAuthentication no", "PasswordAuthentication yes", "policy"),
        ("PermitRootLogin no", "PermitRootLogin yes", "policy"),
        ("AllowUsers pi", "AllowUsers root", "policy"),
    ),
)
def test_artifact_verifier_rejects_unsafe_sshd_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    message: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    policy = root / "etc/ssh/sshd_config.d/90-rave-ethernet.conf"
    policy.write_text(policy.read_text().replace(old, new))
    with pytest.raises(VerificationError, match=message):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize("address", ("0.0.0.0", "::", "192.168.77.1", "10.77.0.1"))
def test_artifact_verifier_rejects_sshd_listener_outside_socket_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    policy = root / "etc/ssh/sshd_config.d/90-rave-ethernet.conf"
    policy.write_text(policy.read_text() + f"ListenAddress {address}\n")
    with pytest.raises(VerificationError, match="owned exclusively by ssh.socket"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_direct_ssh_service_enablement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    enabled = root / "etc/systemd/system/multi-user.target.wants/ssh.service"
    enabled.parent.mkdir(parents=True, exist_ok=True)
    enabled.symlink_to("/usr/lib/systemd/system/ssh.service")
    with pytest.raises(VerificationError, match="directly enabled"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize("owner", ("ssh.socket", "ssh.service"))
def test_artifact_verifier_rejects_competing_hostkey_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    keygen_want = root / f"etc/systemd/system/{owner}.wants/sshd-keygen.service"
    keygen_want.parent.mkdir(parents=True)
    keygen_want.symlink_to("/usr/lib/systemd/system/sshd-keygen.service")
    with pytest.raises(VerificationError, match="competing conditional host-key generator"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    "unit",
    ("ssh.service", "rave-engineering-ssh-hostkeys.service"),
)
def test_artifact_verifier_rejects_obscuring_ssh_service_dropin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unit: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    _write(root, f"etc/systemd/system/{unit}.d/99-unsafe.conf", "[Unit]\nAfter=rave-webd.service\n")
    with pytest.raises(VerificationError, match="drop-ins obscure"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_baked_host_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    _write(root, "etc/ssh/ssh_host_ed25519_key", "synthetic private host key")
    with pytest.raises(VerificationError, match="baked"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize("shadow", ("!", "*NP*", "", "debug"))
def test_artifact_verifier_rejects_unusable_pi_console_password(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shadow: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    (root / "etc/shadow").write_text(f"pi:{shadow}:20000::::::\n")
    with pytest.raises(VerificationError, match="usable local console password"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_missing_authorized_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    (root / "home/pi/.ssh/authorized_keys").unlink()
    with pytest.raises(VerificationError, match="authorized_keys"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_builder_generic_sudo_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    _write(root, "etc/sudoers.d/010_rpi-nopasswd", "pi ALL=(ALL) NOPASSWD: ALL\n", 0o440)
    with pytest.raises(VerificationError, match="builder-generated generic sudo policy"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_pi_sudo_group_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    (root / "etc/group").write_text("sudo:x:27:pi\n")
    with pytest.raises(VerificationError, match="sudo-group membership"):
        verify_engineering_ethernet_ssh(root)


def test_empty_machine_id_and_absent_host_keys_use_rave_owned_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    machine_id = root / "etc/machine-id"
    assert machine_id.stat().st_size == 0
    assert not list((root / "etc/ssh").glob("ssh_host_*"))
    verify_engineering_ethernet_ssh(root)
    rave_unit = (root / "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service").read_text()
    socket = (root / "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf").read_text()
    service = (root / "etc/systemd/system/ssh.service.d/90-rave-hostkeys.conf").read_text()
    assert "ExecStart=/usr/bin/ssh-keygen -A" in rave_unit
    assert "Condition" not in rave_unit
    assert "Before=ssh.service" in rave_unit
    assert "ssh.socket" not in rave_unit
    assert "Requires=rave-engineering-ssh-hostkeys.service" in service
    assert "After=rave-engineering-ssh-hostkeys.service" in service
    assert "rave-engineering-ssh-hostkeys.service" not in socket


def test_artifact_verifier_rejects_missing_rave_hostkey_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    (root / "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service").unlink()
    with pytest.raises(VerificationError, match="RAVE engineering SSH host-key service"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ("ExecStart=/usr/bin/ssh-keygen -A", "ExecStart=/bin/true", "ssh-keygen -A"),
        ("Type=oneshot", "Type=simple", "Type=oneshot"),
        ("RemainAfterExit=yes", "RemainAfterExit=no", "RemainAfterExit=yes"),
    ),
)
def test_artifact_verifier_rejects_invalid_rave_hostkey_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    message: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    unit = root / "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service"
    unit.write_text(unit.read_text().replace(old, new))
    with pytest.raises(VerificationError, match=message):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    ("directive", "message"),
    (
        ("Requires=rave-engineering-ssh-hostkeys.service", "does not require"),
        ("After=rave-engineering-ssh-hostkeys.service", "not ordered after"),
    ),
)
def test_artifact_verifier_rejects_service_without_rave_hostkey_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    directive: str,
    message: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    service = root / "etc/systemd/system/ssh.service.d/90-rave-hostkeys.conf"
    service.write_text(service.read_text().replace(f"{directive}\n", ""))
    with pytest.raises(VerificationError, match=message):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    ("relative", "dependency"),
    (
        ("etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf", "rave-wifi-init.service"),
        ("usr/lib/systemd/system/ssh.service", "rave-management-dhcp.service"),
        ("usr/lib/systemd/system/ssh.service", "rave-webd.service"),
        ("usr/lib/systemd/system/ssh.service", "NetworkManager-wait-online.service"),
    ),
)
def test_artifact_verifier_rejects_ssh_management_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
    dependency: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    unit = root / relative
    unit.write_text(f"{unit.read_text()}\n[Unit]\nRequires={dependency}\n")
    with pytest.raises(VerificationError, match="management stack"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_explicit_ssh_device_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    socket = root / "etc/systemd/system/ssh.socket.d/90-rave-ethernet.conf"
    socket.write_text(
        f"{socket.read_text()}\n[Unit]\nBindsTo=sys-subsystem-net-devices-eth0.device\n"
    )
    with pytest.raises(VerificationError, match="device-lifetime dependency"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(
    "condition",
    (
        "ConditionFirstBoot=yes",
        "ConditionPathIsReadWrite=/etc/ssh",
        "ConditionPathIsSymbolicLink=!/etc/ssh",
    ),
)
def test_artifact_verifier_rejects_conditional_rave_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    unit = root / "usr/lib/systemd/system/rave-engineering-ssh-hostkeys.service"
    unit.write_text(unit.read_text().replace("[Unit]\n", f"[Unit]\n{condition}\n"))
    with pytest.raises(VerificationError, match="conditionally skipped"):
        verify_engineering_ethernet_ssh(root)
