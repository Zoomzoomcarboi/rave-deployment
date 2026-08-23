#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    require(not nm.exists() or not any(nm.iterdir()), "NetworkManager connection profile is present")
    for relative in ("var/lib/rave/identity", "var/lib/rave/pairing", "var/lib/rave/session"):
        require(not (rootfs / relative).exists(), f"cloned RAVE state present: /{relative}")
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


def verify_rootfs(rootfs: Path) -> dict[str, object]:
    rootfs = rootfs.resolve(strict=True)
    require(rootfs != Path("/"), "refusing to verify host root")
    require((rootfs / "etc").is_dir() and (rootfs / "var").is_dir(), "implausible rootfs")
    verify_clone_safety(rootfs)

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
        "opt/rave/web/rave_web/app.py",
        "opt/rave/web/rave_web/static/index.html",
        "opt/rave/web/rave_web/static/app.css",
        "opt/rave/web/rave_web/static/app.js",
        "usr/share/doc/rave-web/THIRD_PARTY_NOTICES.md",
        "etc/rave/network/GATE1_NO_NETWORK_ACTUATION",
        "etc/rave/compatibility/HAILO_STACK_NOT_INTEGRATED",
        "opt/rave/runtime/PERCEPTION_NOT_INTEGRATED",
        "var/lib/rave/update/UPDATE_SERVICE_NOT_INTEGRATED",
    )
    for relative in required_files:
        require((rootfs / relative).is_file(), f"missing expected file: /{relative}")
    require(not (rootfs / "opt/rave/web/WEB_PACKAGE_NOT_INSTALLED").exists(), "web install marker remains")

    package_status = (rootfs / "var/lib/dpkg/status").read_text(encoding="utf-8")
    for package in ("python3-fastapi", "python3-pydantic", "python3-uvicorn"):
        stanza = next(
            (block for block in package_status.split("\n\n") if block.startswith(f"Package: {package}\n")),
            "",
        )
        require(
            "Status: install ok installed\n" in f"{stanza}\n",
            f"missing runtime package: {package}",
        )

    unit = (rootfs / "usr/lib/systemd/system/rave-webd.service").read_text(encoding="utf-8")
    require("--host 127.0.0.1" in unit, "rave-webd is not loopback-only")
    require("RuntimeDirectory=" not in unit, "rave-webd owns a shared runtime directory")
    require(
        not (rootfs / "etc/systemd/system/multi-user.target.wants/rave-webd.service").exists(),
        "rave-webd must remain disabled in Gate 2A",
    )

    return {
        "status": "pass",
        "rootfs": str(rootfs),
        "checks": {
            "rave_account": "pass",
            "filesystem_contract": "pass",
            "web_content": "pass",
            "loopback_only_webd": "pass",
            "machine_id_uninitialized": "pass",
            "ssh_host_keys_absent": "pass",
            "network_profiles_absent": "pass",
            "rave_private_state_absent": "pass",
            "identity_and_secret_scan": "pass",
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
