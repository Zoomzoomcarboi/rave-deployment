import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
LAYER = ROOT / "image/layer/rave-hailo.yaml"


def test_hailo_layer_declares_validated_m2a_stack() -> None:
    text = LAYER.read_text()

    assert "6.18.39+rpt-rpi-2712" in text
    assert "1:6.18.39-1+rpt1" in text
    assert "4.23.0" in text
    assert "HAILO8" in text

    package_section = text.split("setup-hooks:", maxsplit=1)[0]

    assert "build-essential" in package_section
    assert "linux-headers-rpi-2712" in package_section
    assert "hailort" in package_section

    # The vendor driver postinst is unsafe during an offline image build.
    assert "hailort-pcie-driver" not in package_section

    assert "apt-get download '${driver_package}=${hailo_version}'" in text
    assert "/usr/bin/dpkg --unpack" in text
    assert 'dpkg-deb -f "$driver_deb" Architecture)' in text
    assert '= "all"' in text

    assert "ecc4d75bdb3e7e5e8996c5a8569bd328df47a3189838865d2cfaab32c386df7b" in text
    assert "22e802d5c8809ccf31a47afd4d08f64c1c880cca57b3e54922c2fbf56a7b8066" in text
    assert "14ca5b281added9363b9a71db27bad0f7e91933cf70c78045a1bcaf48c0d785b" in text
    assert "9d65f7ed4286791d2b558e8a69d9d4d2b59acbdcd62f0bec49e55eeff153368d" in text

    assert 'test -f "$control_dir/preinst"' in text
    assert 'test ! -e "$control_dir/preinst"' not in text
    assert "ARCH=arm64 UNAME_STR=raspi" in text
    assert "INSTALL_MOD_DIR=kernel/drivers/misc DEPMOD=/bin/true modules_install" in text
    assert "KERNEL_DIR=" not in text
    assert "/usr/sbin/depmod -a '$target_kernel'" in text

    # Offline image construction must never execute modprobe.
    executable_lines = [
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not any(re.search(r"(?:^|[\s/])modprobe(?:\s|$)", line) for line in executable_lines)

    # Broad Hailo software stacks remain outside the M2A boundary.
    assert "hailo-all" not in text
    assert "python3-hailort" not in text
    assert "hailo-tappas" not in text


def test_hailo_layer_pins_compatibility_set_before_install() -> None:
    text = LAYER.read_text()

    assert "setup-hooks:" in text
    assert "Pin: version 1:6.18.39-1+rpt1" in text
    assert "Pin: version 4.23.0" in text
    assert text.count("Pin-Priority: 1001") == 2


def test_hailo_layer_replaces_placeholder_contract() -> None:
    text = LAYER.read_text()

    assert 'rm -f "$rootfs/etc/rave/compatibility/HAILO_STACK_NOT_INTEGRATED"' in text
    assert "hailo-stack.env" in text
    assert "RAVE_HAILO_IMAGE_CONTRACT=M2A" in text


@pytest.mark.parametrize("failure", ["", "modules", "modules_install", "depmod"])
def test_offline_build_targets_pi_and_stops_on_failure(tmp_path: Path, failure: str) -> None:
    """Execute the layer's build shell with recording tools, without a chroot."""
    hook = yaml.safe_load(LAYER.read_text())["mmdebstrap"]["customize-hooks"][0]
    script = hook.split('if ! chroot "$rootfs" /bin/sh -c "', 1)[1].split(
        '" > "$rootfs$build_log"', 1
    )[0]
    kernel = "6.18.39+rpt-rpi-2712"
    script = script.replace("$target_kernel", kernel)
    # Only redirect the absolute depmod executable; preserve its actual arguments.
    script = script.replace("/usr/sbin/depmod", str(tmp_path / "depmod"))
    recorder = """#!/bin/sh
set -eu
name=${0##*/}
printf '%s' "$name" >> "$CALLS"
for arg do printf ' %s' "$arg" >> "$CALLS"; done
printf '\n' >> "$CALLS"
last=
for arg do last=$arg; done
if [ "$FAIL_STAGE" = "$name" ] || [ "$FAIL_STAGE" = "$last" ]; then
    exit 23
fi
"""
    for name in ("make", "depmod", "uname", "modprobe"):
        tool = tmp_path / name
        tool.write_text(recorder if name in ("make", "depmod") else "#!/bin/sh\nexit 99\n")
        tool.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        ["/bin/sh", "-c", script], capture_output=True, text=True, check=False,
        env={**os.environ, "PATH": f"{tmp_path}:/usr/bin:/bin", "CALLS": str(calls),
             "FAIL_STAGE": failure},
    )
    assert result.returncode == (23 if failure else 0), result.stderr
    recorded = calls.read_text().splitlines()
    stages = [line.split()[-1] if line.startswith("make ") else "depmod" for line in recorded]
    expected = ["clean", "modules", "modules_install", "depmod", "clean"]
    assert stages == (expected[:expected.index(failure) + 1] if failure else expected)
    for line in recorded:
        if line.startswith("make "):
            assert f"-C /lib/modules/{kernel}/build" in line
            assert "M=/usr/src/hailort-pcie-driver/linux/pcie" in line
            assert "ARCH=arm64 UNAME_STR=raspi" in line
            if line.endswith(" modules_install"):
                assert "INSTALL_MOD_DIR=kernel/drivers/misc DEPMOD=/bin/true" in line
        else:
            assert line == f"depmod -a {kernel}"


def test_driver_conffile_is_verified_after_dpkg_configure() -> None:
    hook = yaml.safe_load(LAYER.read_text())["mmdebstrap"]["customize-hooks"][0]
    assert hook.index('/usr/bin/dpkg --configure') < hook.index(
        'test -s "$rootfs/etc/modprobe.d/hailo_pci.conf"'
    )
