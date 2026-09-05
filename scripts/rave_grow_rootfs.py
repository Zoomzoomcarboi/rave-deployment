#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_TRAILING_BYTES = 16 * 1024 * 1024
COMPLETION_PATH = Path("/var/lib/rave/storage/root-expanded-v1.json")

FINDMNT = "/usr/bin/findmnt"
LSBLK = "/usr/bin/lsblk"
GROWPART = "/usr/bin/growpart"
UDEVADM = "/usr/bin/udevadm"
SFDISK = "/usr/sbin/sfdisk"
BLOCKDEV = "/usr/sbin/blockdev"
BLKID = "/usr/sbin/blkid"
RESIZE2FS = "/usr/sbin/resize2fs"
DUMPE2FS = "/usr/sbin/dumpe2fs"


class ExpansionError(RuntimeError):
    pass


@dataclass(frozen=True)
class GrowthPlan:
    disk: str
    root_partition: str
    sector_size: int
    start_sector: int
    partition_sectors: int
    end_sector: int
    final_usable_sector: int
    trailing_bytes: int
    unchanged_partitions: tuple[tuple[str, int, int, str, bool], ...]

    @property
    def needs_partition_growth(self) -> bool:
        return self.trailing_bytes > MAX_TRAILING_BYTES


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExpansionError(message)


def _integer(value: Any, name: str) -> int:
    require(isinstance(value, int) and value >= 0, f"invalid {name} in partition table")
    return value


def analyze_partition_table(table_json: str, root_partition: str, device_bytes: int) -> GrowthPlan:
    try:
        document = json.loads(table_json)
        table = document["partitiontable"]
        partitions = table["partitions"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ExpansionError(f"invalid partition table JSON: {error}") from error

    require(isinstance(table, dict), "invalid partition table")
    require(table.get("label") == "dos", "boot device must use the expected MBR partition table")
    require(table.get("unit") == "sectors", "partition table must report sector units")
    require(
        isinstance(partitions, list) and len(partitions) == 2,
        "ROOT must be the final partition in an exact BOOT/ROOT layout",
    )
    sector_size = _integer(table.get("sectorsize"), "sector size")
    require(sector_size > 0, "partition-table sector size is zero")
    require(device_bytes >= sector_size, "boot device size is invalid")

    normalized_root = str(Path(root_partition).resolve(strict=False))
    entries: list[tuple[dict[str, Any], int, int, int]] = []
    for partition in partitions:
        require(isinstance(partition, dict), "invalid partition entry")
        start = _integer(partition.get("start"), "partition start")
        size = _integer(partition.get("size"), "partition size")
        require(size > 0, "partition size is zero")
        entries.append((partition, start, size, start + size - 1))

    roots = [entry for entry in entries if str(Path(str(entry[0].get("node"))).resolve(strict=False)) == normalized_root]
    require(len(roots) == 1, "ROOT partition is not uniquely present in the partition table")
    root, start_sector, partition_sectors, end_sector = roots[0]
    require(end_sector == max(entry[3] for entry in entries), "ROOT must be the final partition")

    final_usable_sector = device_bytes // sector_size - 1
    require(end_sector <= final_usable_sector, "ROOT extends beyond the physical boot device")
    trailing_bytes = (final_usable_sector - end_sector) * sector_size
    unchanged = tuple(
        (
            str(partition.get("node")),
            start,
            size,
            str(partition.get("type", "")),
            bool(partition.get("bootable", False)),
        )
        for partition, start, size, _ in entries
        if partition is not root
    )
    return GrowthPlan(
        disk=str(table.get("device")),
        root_partition=str(root.get("node")),
        sector_size=sector_size,
        start_sector=start_sector,
        partition_sectors=partition_sectors,
        end_sector=end_sector,
        final_usable_sector=final_usable_sector,
        trailing_bytes=trailing_bytes,
        unchanged_partitions=unchanged,
    )


def verify_expanded_geometry(before: GrowthPlan, after: GrowthPlan) -> None:
    require(after.disk == before.disk, "boot device changed during ROOT expansion")
    require(after.root_partition == before.root_partition, "ROOT partition changed during expansion")
    require(after.start_sector == before.start_sector, "ROOT partition start sector changed")
    require(after.end_sector >= before.end_sector, "ROOT partition became smaller")
    require(after.final_usable_sector == before.final_usable_sector, "boot device geometry changed")
    require(after.unchanged_partitions == before.unchanged_partitions, "BOOT partition changed")
    require(
        after.trailing_bytes <= MAX_TRAILING_BYTES,
        "multi-gigabyte trailing capacity remains after ROOT expansion",
    )


def verify_filesystem_size(partition_bytes: int, filesystem_bytes: int) -> None:
    require(filesystem_bytes <= partition_bytes, "ext4 filesystem exceeds ROOT partition")
    require(
        partition_bytes - filesystem_bytes <= MAX_TRAILING_BYTES,
        "ext4 filesystem does not fill the expanded ROOT partition",
    )


def command(*arguments: str) -> str:
    result = subprocess.run(arguments, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ExpansionError(f"command failed: {arguments[0]}: {detail}")
    return result.stdout.strip()


def filesystem_size_bytes(root_partition: str) -> int:
    output = command(DUMPE2FS, "-h", root_partition)
    block_count = re.search(r"^Block count:\s+([0-9]+)$", output, re.MULTILINE)
    block_size = re.search(r"^Block size:\s+([0-9]+)$", output, re.MULTILINE)
    require(block_count is not None and block_size is not None, "cannot read ext4 filesystem size")
    return int(block_count.group(1)) * int(block_size.group(1))


def assert_root_identity(root_partition: str) -> None:
    alias = str(Path("/dev/disk/by-slot/system").resolve(strict=True))
    require(alias == root_partition, "/dev/disk/by-slot/system does not resolve to mounted ROOT")
    require(command(FINDMNT, "-n", "-o", "FSTYPE", "/") == "ext4", "ROOT filesystem is not ext4")
    require(command(BLKID, "-s", "LABEL", "-o", "value", root_partition) == "ROOT", "ROOT label changed")


def assert_boot_identity(plan: GrowthPlan) -> None:
    require(len(plan.unchanged_partitions) == 1, "BOOT partition is not unique")
    boot_partition = str(Path("/dev/disk/by-slot/boot").resolve(strict=True))
    expected_partition = str(Path(plan.unchanged_partitions[0][0]).resolve(strict=True))
    require(boot_partition == expected_partition, "/dev/disk/by-slot/boot does not resolve to BOOT")
    require(command(BLKID, "-s", "LABEL", "-o", "value", boot_partition) == "BOOT", "BOOT label changed")


def write_completion(plan: GrowthPlan, filesystem_bytes: int) -> None:
    record = {
        "status": "complete",
        "disk": plan.disk,
        "root_partition": plan.root_partition,
        "root_start_sector": plan.start_sector,
        "root_end_sector": plan.end_sector,
        "final_usable_sector": plan.final_usable_sector,
        "trailing_bytes": plan.trailing_bytes,
        "filesystem_bytes": filesystem_bytes,
    }
    COMPLETION_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = COMPLETION_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(record, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.chmod(temporary, 0o640)
    os.replace(temporary, COMPLETION_PATH)
    directory_fd = os.open(COMPLETION_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def expand_root() -> None:
    COMPLETION_PATH.unlink(missing_ok=True)
    root_partition = str(Path(command(FINDMNT, "-n", "-o", "SOURCE", "/")).resolve(strict=True))
    assert_root_identity(root_partition)

    parent_name = command(LSBLK, "-dn", "-o", "PKNAME", root_partition)
    partition_number = command(LSBLK, "-dn", "-o", "PARTN", root_partition)
    require(parent_name and "/" not in parent_name, "cannot identify physical ROOT parent device")
    require(partition_number.isdigit(), "cannot identify ROOT partition number")
    require(partition_number == "2", "ROOT must be partition 2 in the BOOT/ROOT layout")
    disk = str(Path("/dev") / parent_name)
    device_bytes = int(command(BLOCKDEV, "--getsize64", disk))

    before = analyze_partition_table(command(SFDISK, "--json", disk), root_partition, device_bytes)
    require(str(Path(before.disk).resolve(strict=True)) == str(Path(disk).resolve(strict=True)), "partition table is not for the ROOT boot device")
    assert_boot_identity(before)

    if before.needs_partition_growth:
        command(GROWPART, disk, partition_number)
        command(UDEVADM, "settle")

    after = analyze_partition_table(command(SFDISK, "--json", disk), root_partition, device_bytes)
    verify_expanded_geometry(before, after)
    assert_root_identity(root_partition)
    assert_boot_identity(after)

    command(RESIZE2FS, root_partition)
    assert_root_identity(root_partition)
    assert_boot_identity(after)
    filesystem_bytes = filesystem_size_bytes(root_partition)
    partition_bytes = after.partition_sectors * after.sector_size
    verify_filesystem_size(partition_bytes, filesystem_bytes)
    write_completion(after, filesystem_bytes)


def main() -> int:
    try:
        expand_root()
        return 0
    except (ExpansionError, OSError, ValueError) as error:
        print(f"RAVE ROOT expansion failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
