import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_rave_image import (
    VerificationError,
    verify_clone_safety,
    verify_gate2b_us_regulatory_domain,
    verify_publishable_image_has_no_engineering_ssh,
    verify_rootfs,
)


def minimal_rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    for relative in ("etc", "var", "opt/rave", "var/lib/rave", "var/log/rave"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "etc/passwd").write_text("rave:x:1000:1000::/var/lib/rave:/usr/sbin/nologin\n")
    (root / "etc/group").write_text("rave:x:1000:\n")
    (root / "etc/shadow").write_text("rave:!:20000::::::\n")
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
    with pytest.raises(VerificationError, match="unreviewed SSH authorized key"):
        verify_clone_safety(root)


def test_verifier_rejects_token_assignment(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    field = "access_" + "token"
    (root / "etc/unsafe.conf").write_text(f"{field}=synthetic-credential\n")
    with pytest.raises(VerificationError, match="token or credential"):
        verify_clone_safety(root)


def test_publishable_policy_does_not_require_engineering_ssh(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    verify_publishable_image_has_no_engineering_ssh(root)


def test_publishable_policy_rejects_engineering_ssh_assets(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    engineering_policy = root / "etc/ssh/sshd_config.d/90-rave-ethernet.conf"
    engineering_policy.parent.mkdir(parents=True)
    engineering_policy.write_text("synthetic engineering policy\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="non-publishable Gate 2B engineering SSH"):
        verify_publishable_image_has_no_engineering_ssh(root)


def regulatory_rootfs(tmp_path: Path, *, regdom: str = "US") -> Path:
    root = tmp_path / "regulatory-rootfs"
    regulatory = root / "etc/modprobe.d/cfg80211_regdomain.conf"
    regulatory.parent.mkdir(parents=True)
    regulatory.write_text(f"options cfg80211 ieee80211_regdom={regdom}\n", encoding="utf-8")
    return root


def test_gate2b_us_regulatory_domain_accepts_explicit_us_setting(tmp_path: Path) -> None:
    verify_gate2b_us_regulatory_domain(regulatory_rootfs(tmp_path))


def test_gate2b_us_regulatory_domain_rejects_gb_fallback(tmp_path: Path) -> None:
    with pytest.raises(VerificationError, match="regulatory domain"):
        verify_gate2b_us_regulatory_domain(regulatory_rootfs(tmp_path, regdom="GB"))
