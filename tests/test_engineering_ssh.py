import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_rave_image import VerificationError, verify_engineering_ethernet_ssh

ROOT = Path(__file__).resolve().parents[1]
KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKR4QyPoOinkc4Jyg/o2/vgXzY+s3uCHP/CzFxGSg7JC "
    "rave-pi-debug\n"
)


def _write(root: Path, relative: str, content: str, mode: int = 0o644) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def ssh_rootfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "rootfs"
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
    keygen_want = root / "etc/systemd/system/ssh.socket.wants/sshd-keygen.service"
    keygen_want.parent.mkdir(parents=True)
    keygen_want.symlink_to("/usr/lib/systemd/system/sshd-keygen.service")
    service_keygen_want = root / "etc/systemd/system/ssh.service.wants/sshd-keygen.service"
    service_keygen_want.parent.mkdir(parents=True)
    service_keygen_want.symlink_to("/usr/lib/systemd/system/sshd-keygen.service")

    uid, gid = os.getuid(), os.getgid()
    _write(root, "etc/passwd", f"pi:x:{uid}:{gid}::/home/pi:/bin/bash\n")
    _write(root, "etc/group", "sudo:x:27:\n")
    _write(root, "etc/shadow", "pi:*NP*:20000::::::\n", 0o640)
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
    policy = (ROOT / "image/overlays/etc/ssh/sshd_config.d/90-rave-ethernet.conf").read_text()
    assert "packages: [openssh-server, sudo]" in layer
    assert "non-publishable" in layer
    assert socket.splitlines() == [
        "[Socket]",
        "ListenStream=",
        "ListenStream=10.77.0.1:22",
        "FreeBind=yes",
        "BindToDevice=eth0",
    ]
    assert "PasswordAuthentication no" in policy
    assert "PermitRootLogin no" in policy
    assert "AllowUsers pi" in policy
    assert "AllowTcpForwarding no" in policy
    assert "AllowAgentForwarding no" in policy
    assert "usermod --password '*NP*' pi" in hook
    assert 'rm -f -- "$rootfs/etc/sudoers.d/010_rpi-nopasswd"' in hook
    assert "/usr/sbin/deluser pi sudo" in hook
    assert "/usr/sbin/visudo -cf /etc/sudoers" in hook
    assert "multi-user.target.wants/ssh.service" in hook
    assert "sockets.target.wants/ssh.socket" in hook
    assert "ssh.socket.wants/sshd-keygen.service" in hook
    assert "NetworkManager" not in socket + policy
    assert "wlan0" not in socket + policy
    assert "network-online.target" not in socket + policy
    assert (ROOT / "image/overlays/home/pi/.ssh/authorized_keys").read_text() == KEY
    assert (ROOT / "image/overlays/etc/sudoers.d/90-rave-engineering-ssh").read_text() == (
        "pi ALL=(ALL:ALL) NOPASSWD: ALL\n"
    )


def test_artifact_verifier_accepts_exact_engineering_ssh_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify_engineering_ethernet_ssh(ssh_rootfs(tmp_path, monkeypatch))


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ("ListenStream=22", "reset the wildcard"),
        ("ListenStream=0.0.0.0:22", "reset the wildcard"),
        ("ListenStream=[::]:22", "reset the wildcard"),
        ("FreeBind=no", "FreeBind"),
        ("BindToDevice=wlan0", "bound to eth0"),
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
        lines[1:3] = [replacement]
    elif replacement.startswith("FreeBind"):
        lines[3] = replacement
    else:
        lines[4] = replacement
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


def test_artifact_verifier_rejects_direct_ssh_service_enablement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    enabled = root / "etc/systemd/system/multi-user.target.wants/ssh.service"
    enabled.parent.mkdir(parents=True, exist_ok=True)
    enabled.symlink_to("/usr/lib/systemd/system/ssh.service")
    with pytest.raises(VerificationError, match="directly enabled"):
        verify_engineering_ethernet_ssh(root)


def test_artifact_verifier_rejects_baked_host_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    _write(root, "etc/ssh/ssh_host_ed25519_key", "synthetic private host key")
    with pytest.raises(VerificationError, match="baked"):
        verify_engineering_ethernet_ssh(root)


@pytest.mark.parametrize(("shadow", "message"), (("!", "key-only"), ("$6$hash", "key-only")))
def test_artifact_verifier_rejects_locked_or_password_pi_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shadow: str,
    message: str,
) -> None:
    root = ssh_rootfs(tmp_path, monkeypatch)
    (root / "etc/shadow").write_text(f"pi:{shadow}:20000::::::\n")
    with pytest.raises(VerificationError, match=message):
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
