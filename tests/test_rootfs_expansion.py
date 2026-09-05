import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.rave_grow_rootfs import (
    ExpansionError,
    analyze_partition_table,
    verify_expanded_geometry,
    verify_filesystem_size,
)

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
GIB = 1024 * MIB
SECTOR_SIZE = 512
BOOT_START = 16_384
BOOT_SECTORS = 512 * MIB // SECTOR_SIZE
ROOT_START = BOOT_START + BOOT_SECTORS
ROOT_SECTORS = 12 * GIB // SECTOR_SIZE
DEVICE_BYTES = int(58.3 * GIB)


def partition_table(root_sectors: int = ROOT_SECTORS, extra_partition: bool = False) -> str:
    partitions = [
        {
            "node": "/dev/mmcblk0p1",
            "start": BOOT_START,
            "size": BOOT_SECTORS,
            "type": "c",
            "bootable": True,
        },
        {
            "node": "/dev/mmcblk0p2",
            "start": ROOT_START,
            "size": root_sectors,
            "type": "83",
        },
    ]
    if extra_partition:
        partitions.append(
            {
                "node": "/dev/mmcblk0p3",
                "start": ROOT_START + root_sectors,
                "size": 2048,
                "type": "83",
            }
        )
    return json.dumps(
        {
            "partitiontable": {
                "label": "dos",
                "device": "/dev/mmcblk0",
                "unit": "sectors",
                "sectorsize": SECTOR_SIZE,
                "partitions": partitions,
            }
        }
    )


def test_representative_58_gib_card_requires_growth_then_uses_entire_device() -> None:
    before = analyze_partition_table(
        partition_table(), "/dev/mmcblk0p2", DEVICE_BYTES
    )
    assert before.start_sector == ROOT_START
    assert before.needs_partition_growth
    assert before.trailing_bytes > 40 * GIB

    expanded_sectors = before.final_usable_sector - ROOT_START + 1
    after = analyze_partition_table(
        partition_table(root_sectors=expanded_sectors),
        "/dev/mmcblk0p2",
        DEVICE_BYTES,
    )
    verify_expanded_geometry(before, after)
    assert after.trailing_bytes == 0
    assert not after.needs_partition_growth


def test_root_must_be_final_partition() -> None:
    with pytest.raises(ExpansionError, match="final partition"):
        analyze_partition_table(
            partition_table(extra_partition=True), "/dev/mmcblk0p2", DEVICE_BYTES
        )


def test_partition_growth_must_preserve_start_sector() -> None:
    before = analyze_partition_table(partition_table(), "/dev/mmcblk0p2", DEVICE_BYTES)
    changed_start = ROOT_START + 2048
    expanded_sectors = before.final_usable_sector - changed_start + 1
    changed = json.loads(partition_table(root_sectors=expanded_sectors))
    changed["partitiontable"]["partitions"][1]["start"] = changed_start
    after = analyze_partition_table(json.dumps(changed), "/dev/mmcblk0p2", DEVICE_BYTES)

    with pytest.raises(ExpansionError, match="start sector changed"):
        verify_expanded_geometry(before, after)


def test_partition_growth_must_preserve_boot_partition() -> None:
    before = analyze_partition_table(partition_table(), "/dev/mmcblk0p2", DEVICE_BYTES)
    expanded_sectors = before.final_usable_sector - ROOT_START + 1
    changed = json.loads(partition_table(root_sectors=expanded_sectors))
    changed["partitiontable"]["partitions"][0]["size"] -= 2048
    after = analyze_partition_table(json.dumps(changed), "/dev/mmcblk0p2", DEVICE_BYTES)

    with pytest.raises(ExpansionError, match="BOOT partition changed"):
        verify_expanded_geometry(before, after)


def test_multi_gib_trailing_capacity_is_never_accepted() -> None:
    plan = analyze_partition_table(partition_table(), "/dev/mmcblk0p2", DEVICE_BYTES)

    with pytest.raises(ExpansionError, match="trailing capacity"):
        verify_expanded_geometry(plan, plan)


def test_filesystem_must_fill_expanded_partition() -> None:
    partition_bytes = 57 * GIB
    verify_filesystem_size(partition_bytes, partition_bytes - 4096)

    with pytest.raises(ExpansionError, match="filesystem does not fill"):
        verify_filesystem_size(partition_bytes, partition_bytes - 2 * GIB)


def test_image_installs_and_enables_guarded_root_expansion() -> None:
    layer = (ROOT / "image/layer/rave-base.yaml").read_text(encoding="utf-8")
    service = (ROOT / "systemd/rave-grow-rootfs.service").read_text(encoding="utf-8")
    script = (ROOT / "scripts/rave_grow_rootfs.py").read_text(encoding="utf-8")

    for package in ("cloud-guest-utils", "e2fsprogs", "util-linux"):
        assert package in layer
    assert "/usr/libexec/rave/rave-grow-rootfs" in layer
    assert "multi-user.target.wants/rave-grow-rootfs.service" in layer
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/libexec/rave/rave-grow-rootfs" in service
    assert "Before=rave-networkd.service" in service
    assert "rave-webd.socket" not in service
    assert "growpart" in script
    assert "resize2fs" in script
    assert "findmnt" in script
    assert "blockdev" in script
    assert "dumpe2fs" in script
    assert "os.replace" in script
    assert "COMPLETION_PATH.unlink(missing_ok=True)" in script
    assert 'partition_number == "2"' in script
    assert '"/dev/disk/by-slot/boot"' in script
    assert '== "BOOT"' in script


def test_enabled_rave_units_have_no_boot_target_ordering_cycle(tmp_path: Path) -> None:
    systemd_analyze = shutil.which("systemd-analyze")
    assert systemd_analyze is not None

    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    for source in (ROOT / "systemd").iterdir():
        if source.is_file():
            shutil.copy2(source, unit_dir / source.name)

    for unit in unit_dir.glob("*.service"):
        contents = unit.read_text(encoding="utf-8")
        normalized = []
        for line in contents.splitlines():
            if line.startswith("ExecStart="):
                line = "ExecStart=/usr/bin/true"
            elif line.startswith(("User=", "Group=")):
                line = f"{line.split('=', 1)[0]}=root"
            normalized.append(line)
        unit.write_text("\n".join(normalized) + "\n", encoding="utf-8")

    (unit_dir / "NetworkManager.service").write_text(
        "[Unit]\nDescription=CI-only NetworkManager stub\n\n"
        "[Service]\nType=oneshot\nExecStart=/usr/bin/true\n",
        encoding="utf-8",
    )
    multi_user_wants = unit_dir / "multi-user.target.wants"
    sockets_wants = unit_dir / "sockets.target.wants"
    multi_user_wants.mkdir()
    sockets_wants.mkdir()
    (multi_user_wants / "rave-grow-rootfs.service").symlink_to("../rave-grow-rootfs.service")
    (multi_user_wants / "rave-networkd.service").symlink_to("../rave-networkd.service")
    (sockets_wants / "rave-webd.socket").symlink_to("../rave-webd.socket")

    environment = os.environ.copy()
    environment["SYSTEMD_UNIT_PATH"] = ":".join(
        (str(unit_dir), "/usr/local/lib/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")
    )
    result = subprocess.run(
        [
            systemd_analyze,
            "verify",
            "--man=no",
            "multi-user.target",
            "sockets.target",
            "basic.target",
            "rave-grow-rootfs.service",
            "rave-webd.socket",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr


def test_root_expansion_sandbox_retains_online_resize_access() -> None:
    from scripts.verify_rave_image import effective_systemd_scalar

    unit = (ROOT / "systemd/rave-grow-rootfs.service").read_text()
    expected = {
        "ProtectSystem": "full",
        "NoNewPrivileges": "true",
        "PrivateTmp": "true",
        "ProtectHome": "true",
        "ReadWritePaths": "-/var/lib/rave/storage",
        "RestrictAddressFamilies": "AF_UNIX",
        "LockPersonality": "true",
        "MemoryDenyWriteExecute": "true",
    }
    for key, value in expected.items():
        assert effective_systemd_scalar((unit,), "Service", key) == value
    assert "ProtectSystem=strict" not in unit
    assert "After=local-fs.target systemd-udev-settle.service" in unit
    assert "rave-webd.socket" not in unit


@pytest.mark.parametrize("outcome", ["success", "resize_failure", "undersized"])
def test_partial_recovery_marker_and_idempotence(tmp_path, monkeypatch, outcome):
    # Command simulation tests orchestration only, not privileged resize success.
    from scripts import rave_grow_rootfs as grow

    disk = tmp_path / "disk"
    root = tmp_path / "root"
    disk.touch()
    root.touch()
    marker = tmp_path / "storage/complete.json"
    marker.parent.mkdir()
    marker.write_text('stale marker')
    monkeypatch.setattr(grow, "COMPLETION_PATH", marker)
    monkeypatch.setattr(grow, "assert_root_identity", lambda _: None)
    monkeypatch.setattr(grow, "assert_boot_identity", lambda _: None)
    sectors = 121230303
    table = json.loads(partition_table(sectors))
    table["partitiontable"]["device"] = str(disk)
    table["partitiontable"]["partitions"][1]["node"] = str(root)
    calls = []

    def command(*args):
        calls.append(args)
        if args[0] == grow.FINDMNT:
            return str(root)
        if args[0] == grow.LSBLK:
            return "2" if "PARTN" in args else "mmcblk0"
        if args[0] == grow.BLOCKDEV:
            return "62615191552"
        if args[0] == grow.SFDISK:
            return json.dumps(table)
        if args[0] == grow.RESIZE2FS:
            assert not marker.exists()
            if outcome == "resize_failure":
                raise grow.ExpansionError("resize failed")
            return ""
        pytest.fail(f"unexpected command: {args}")

    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if str(path) == "/dev/mmcblk0":
            return disk
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(grow, "command", command)

    def size(_):
        assert not marker.exists()
        return 12883329024 if outcome == "undersized" else sectors * 512

    monkeypatch.setattr(grow, "filesystem_size_bytes", size)
    if outcome != "success":
        with pytest.raises(grow.ExpansionError):
            grow.expand_root()
        assert not marker.exists()
        outcome = "success"
        grow.expand_root()
        assert json.loads(marker.read_text())["filesystem_bytes"] == sectors * 512
    else:
        grow.expand_root()
        first = marker.read_bytes()
        grow.expand_root()
        assert marker.read_bytes() == first
        assert json.loads(first)["filesystem_bytes"] == sectors * 512
    assert not any(call[0] == grow.GROWPART for call in calls)
