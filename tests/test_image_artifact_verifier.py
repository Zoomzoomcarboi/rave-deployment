import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_rave_image import (
    VerificationError,
    verify_clone_safety,
    verify_gate2b_us_regulatory_domain,
    verify_hailo_stack,
    verify_publishable_image_has_no_engineering_ssh,
    verify_rootfs,
)


def minimal_rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    for relative in ("etc", "var", "opt/rave", "var/lib/rave", "var/log/rave"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "etc/passwd").write_text(
        "root:x:0:0::/root:/bin/bash\n"
        "pi:x:1000:1000::/home/pi:/bin/bash\n"
        "rave:x:1001:1001::/var/lib/rave:/usr/sbin/nologin\n"
    )
    (root / "etc/group").write_text("rave:x:1001:\n")
    (root / "etc/shadow").write_text(
        "root:!:20000::::::\n"
        "pi:$6$rave-console-test$synthetic-password-hash:20000::::::\n"
        "rave:!:20000::::::\n"
    )
    (root / "etc/machine-id").touch()
    return root


def test_verifier_accepts_only_pi_with_a_usable_local_password(tmp_path: Path) -> None:
    verify_clone_safety(minimal_rootfs(tmp_path))


def test_verifier_rejects_missing_pi_shadow_entry(tmp_path: Path) -> None:
    root = minimal_rootfs(tmp_path)
    shadow = root / "etc/shadow"
    shadow.write_text(
        "\n".join(
            line
            for line in shadow.read_text().splitlines()
            if not line.startswith("pi:")
        )
        + "\n"
    )
    with pytest.raises(VerificationError, match="pi shadow entry is missing"):
        verify_clone_safety(root)


@pytest.mark.parametrize("password", ("!", "*NP*", "", "debug"))
def test_verifier_rejects_locked_or_empty_pi_password(
    tmp_path: Path, password: str
) -> None:
    root = minimal_rootfs(tmp_path)
    shadow = root / "etc/shadow"
    shadow.write_text(
        shadow.read_text().replace(
            "$6$rave-console-test$synthetic-password-hash", password
        )
    )
    with pytest.raises(VerificationError, match="pi must have a usable local console password"):
        verify_clone_safety(root)


@pytest.mark.parametrize("account", ("root", "rave"))
def test_verifier_rejects_usable_password_for_non_console_account(
    tmp_path: Path, account: str
) -> None:
    root = minimal_rootfs(tmp_path)
    shadow = root / "etc/shadow"
    shadow.write_text(
        shadow.read_text().replace(
            f"{account}:!:",
            f"{account}:$6$unintended$synthetic-password-hash:",
        )
    )
    with pytest.raises(VerificationError, match=f"account has usable credentials: {account}"):
        verify_clone_safety(root)


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


@pytest.mark.parametrize(
    "source",
    (
        'const wifiPassword = document.querySelector("#wifi-password");',
        "let wifiPassword = passwordInput.value;",
        "wifiPassword.value = password;",
        "const request = { password: password };",
        'document.querySelector("#wifi-password");',
    ),
)
def test_verifier_accepts_benign_wifi_password_program_code(
    tmp_path: Path, source: str
) -> None:
    root = minimal_rootfs(tmp_path)
    (root / "opt/rave/app.js").write_text(f"{source}\n")
    verify_clone_safety(root)


@pytest.mark.parametrize(
    "assignment",
    (
        "wifi_password=synthetic-value",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        "wifi-password: synthetic-value",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        "wifi password=synthetic-value",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        "psk=synthetic-value",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
    ),
)
def test_verifier_rejects_unquoted_config_wifi_credentials(
    tmp_path: Path, assignment: str
) -> None:
    root = minimal_rootfs(tmp_path)
    (root / "etc/unsafe.conf").write_text(f"{assignment}\n")
    with pytest.raises(VerificationError, match="Wi-Fi credential"):
        verify_clone_safety(root)


@pytest.mark.parametrize(
    "assignment",
    (
        'wifi_password="synthetic value"',  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        "wifi-password: 'synthetic value'",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        'psk="synthetic-value"',  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
    ),
)
def test_verifier_rejects_quoted_config_wifi_credentials(
    tmp_path: Path, assignment: str
) -> None:
    root = minimal_rootfs(tmp_path)
    (root / "etc/unsafe.conf").write_text(f"{assignment}\n")
    with pytest.raises(VerificationError, match="Wi-Fi credential"):
        verify_clone_safety(root)


@pytest.mark.parametrize(
    "source",
    (
        'const wifiPassword = "synthetic value";',
        "let psk = 'synthetic-value';",  # RAVE-SAFETY: synthetic Wi-Fi credential fixture
        'const request = { password: "synthetic value" };',
    ),
)
def test_verifier_rejects_hard_coded_javascript_wifi_credentials(
    tmp_path: Path, source: str
) -> None:
    root = minimal_rootfs(tmp_path)
    (root / "opt/rave/app.js").write_text(f"{source}\n")
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


@pytest.fixture
def hailo_rootfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from scripts import verify_rave_image as verifier

    root = tmp_path / "hailo-rootfs"
    kernel = "6.18.39+rpt-rpi-2712"
    version = "1:6.18.39-1+rpt1"
    files = {
        "etc/rave/compatibility/hailo-stack.env": (
            "RAVE_HAILO_ACCELERATOR=HAILO8\n"
            f"RAVE_HAILO_KERNEL_RELEASE={kernel}\n"
            f"RAVE_HAILO_KERNEL_PACKAGE_VERSION={version}\n"
            "RAVE_HAILORT_VERSION=4.23.0\n"
            "RAVE_HAILO_PCIE_DRIVER_VERSION=4.23.0\n"
            "RAVE_HAILO_IMAGE_CONTRACT=M2A\n"
        ),
        f"lib/modules/{kernel}/kernel/drivers/misc/hailo_pci.ko.xz": "module fixture",
        f"lib/modules/{kernel}/modules.dep": "kernel/drivers/misc/hailo_pci.ko.xz:\n",
        "lib/firmware/hailo/hailo8_fw.4.23.0.bin": "firmware fixture",
        "lib/udev/rules.d/51-hailo-udev.rules": "udev fixture",
        "etc/modprobe.d/hailo_pci.conf": "configuration fixture",
        "var/lib/dpkg/info/hailort-pcie-driver.postinst": "reviewed vendor fixture",
    }
    files["var/lib/dpkg/status"] = "\n\n".join(
        f"Package: {name}\nStatus: install ok installed\nVersion: {package_version}\n"
        f"Architecture: {'all' if name == 'hailort-pcie-driver' else 'arm64'}\n"
        for name, package_version in (
            ("linux-image-rpi-2712", version), ("linux-headers-rpi-2712", version),
            (f"linux-image-{kernel}", version), (f"linux-headers-{kernel}", version),
            ("hailort", "4.23.0"), ("hailort-pcie-driver", "4.23.0"),
        )
    )
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (root / "lib/firmware/hailo/hailo8_fw.bin").symlink_to("hailo8_fw.4.23.0.bin")
    real_sha256 = verifier.sha256
    # Avoid embedding vendor source in tests; only this exact fixture has its reviewed digest.
    monkeypatch.setattr(verifier, "sha256", lambda path: (
        "14ca5b281added9363b9a71db27bad0f7e91933cf70c78045a1bcaf48c0d785b"
        if path.read_bytes() == b"reviewed vendor fixture" else real_sha256(path)
    ))
    return root


def test_hailo_verifier_accepts_complete_offline_stack(hailo_rootfs: Path) -> None:
    verify_hailo_stack(hailo_rootfs)


@pytest.mark.parametrize("defect", (
    "contract", "package_version", "package_unconfigured", "driver_arch",
    "missing_kernel", "module_missing", "module_empty", "module_duplicate",
    "dependencies", "firmware_absolute", "firmware_missing", "udev", "conffile",
    "postinst", "placeholder",
))
def test_hailo_verifier_rejects_incomplete_stack(hailo_rootfs: Path, defect: str) -> None:
    root = hailo_rootfs
    modules = root / "lib/modules/6.18.39+rpt-rpi-2712"
    module = modules / "kernel/drivers/misc/hailo_pci.ko.xz"
    status = root / "var/lib/dpkg/status"
    if defect == "contract":
        (root / "etc/rave/compatibility/hailo-stack.env").write_text("RAVE_HAILORT_VERSION=4.22.0")
    elif defect == "package_version":
        status.write_text(status.read_text().replace("Version: 4.23.0", "Version: 4.22.0"))
    elif defect == "package_unconfigured":
        status.write_text(status.read_text().replace("install ok installed", "install ok unpacked"))
    elif defect == "driver_arch":
        status.write_text(status.read_text().replace("Architecture: all", "Architecture: arm64"))
    elif defect == "missing_kernel":
        status.write_text(status.read_text().replace("Package: linux-image-6.18", "Package: other-6.18"))
    elif defect == "module_missing":
        module.unlink()
    elif defect == "module_empty":
        module.write_text("")
    elif defect == "module_duplicate":
        module.with_suffix("").write_text("duplicate")
    elif defect == "dependencies":
        (modules / "modules.dep").write_text("other.ko:\n")
    elif defect == "firmware_absolute":
        link = root / "lib/firmware/hailo/hailo8_fw.bin"
        link.unlink()
        link.symlink_to("/lib/firmware/hailo/hailo8_fw.4.23.0.bin")
    elif defect == "firmware_missing":
        (root / "lib/firmware/hailo/hailo8_fw.4.23.0.bin").unlink()
    elif defect == "udev":
        (root / "lib/udev/rules.d/51-hailo-udev.rules").unlink()
    elif defect == "conffile":
        (root / "etc/modprobe.d/hailo_pci.conf").unlink()
    elif defect == "postinst":
        (root / "var/lib/dpkg/info/hailort-pcie-driver.postinst").write_text("#!/bin/sh\ntrue\n")
    elif defect == "placeholder":
        (root / "etc/rave/compatibility/HAILO_STACK_NOT_INTEGRATED").touch()
    with pytest.raises(VerificationError):
        verify_hailo_stack(root)


@pytest.mark.parametrize("package", (
    "dkms", "hailo-dkms", "hailo-all", "python3-hailort", "hailo-tappas-core", "hailo-model-zoo",
    "hailo-dataflow-compiler",
))
def test_hailo_verifier_rejects_forbidden_packages(hailo_rootfs: Path, package: str) -> None:
    status = hailo_rootfs / "var/lib/dpkg/status"
    status.write_text(status.read_text() + f"\n\nPackage: {package}\nStatus: install ok installed\n")
    with pytest.raises(VerificationError, match="forbidden M2A package"):
        verify_hailo_stack(hailo_rootfs)
