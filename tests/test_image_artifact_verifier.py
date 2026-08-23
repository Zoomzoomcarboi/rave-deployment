import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_rave_image import VerificationError, verify_clone_safety, verify_rootfs


def minimal_rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    for relative in ("etc", "var", "opt/rave", "var/lib/rave", "var/log/rave"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "etc/passwd").write_text("rave:x:1000:1000::/var/lib/rave:/usr/sbin/nologin\n")
    (root / "etc/group").write_text("rave:x:1000:\n")
    (root / "etc/machine-id").touch()
    return root


def test_verifier_rejects_initialized_machine_id(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    (root / "etc/machine-id").write_text("synthetic-machine-id\n")
    with pytest.raises(VerificationError, match="machine-id"):
        verify_clone_safety(root)


def test_verifier_rejects_root_target() -> None:
    with pytest.raises(VerificationError, match="host root"):
        verify_rootfs(Path("/"))


def test_verifier_rejects_private_key_marker(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    marker = "-----BEGIN PRIVATE" + " KEY-----\n"
    (root / "etc/unsafe.conf").write_text(marker)
    with pytest.raises(VerificationError, match="private-key"):
        verify_clone_safety(root)


def test_verifier_rejects_network_profile(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    profile = root / "etc/NetworkManager/system-connections/example.nmconnection"
    profile.parent.mkdir(parents=True)
    profile.touch()
    with pytest.raises(VerificationError, match="NetworkManager"):
        verify_clone_safety(root)


def test_verifier_rejects_injected_build_identity(tmp_path: Path, monkeypatch) -> None:
    root = minimal_rootfs(tmp_path)
    synthetic_identity = "example" + "-host"
    (root / "etc/unsafe.conf").write_text(f"owner={synthetic_identity}\n")
    monkeypatch.setenv("RAVE_ARTIFACT_DENYLIST", synthetic_identity)
    with pytest.raises(VerificationError, match="injected build identity"):
        verify_clone_safety(root)


def test_verifier_rejects_wifi_secret(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    field = "wifi_" + "password"
    (root / "etc/unsafe.conf").write_text(f"{field}=synthetic-value\n")
    with pytest.raises(VerificationError, match="Wi-Fi credential"):
        verify_clone_safety(root)


def test_verifier_rejects_ssh_authorized_key(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    key = root / "home/device/.ssh/authorized_keys"
    key.parent.mkdir(parents=True)
    key.write_text("synthetic public key material\n")
    with pytest.raises(VerificationError, match="developer SSH key"):
        verify_clone_safety(root)


def test_verifier_rejects_token_assignment(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    field = "access_" + "token"
    (root / "etc/unsafe.conf").write_text(f"{field}=synthetic-credential\n")
    with pytest.raises(VerificationError, match="token or credential"):
        verify_clone_safety(root)
