#!/usr/bin/env python3
"""Manual M2B.1 model storage; no runtime integration or output-ABI qualification."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

STORE = Path("/opt/rave/models")
SELECTED = {
    "schema_version": 1,
    "model_id": "RAVE-2026.09.02-001",
    "artifact": "rave_yolo26n_960.hef",
    "sha256": "913053bb96815b16b79093924ed563844f8edbc02ef6d40129a290eff3e32aea",
    "accelerator": "hailo8",
    "hailort": "4.23.0",
    "input": {"width": 960, "height": 960, "dtype": "UINT8", "layout": "NHWC"},
    "classes": ["vehicle", "motorcycle"],
    "output_abi": None,
}


def load_manifest(path: Path) -> dict:
    """Accept only the selected baseline, including JSON types and known fields."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("manifest must be a regular file, not a symlink")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.keys() != SELECTED.keys():
        raise ValueError("invalid manifest fields")
    for key, expected in SELECTED.items():
        if json.dumps(manifest[key], sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError(f"invalid manifest field: {key}")
    return manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_model(manifest_path: Path, directory: Path) -> dict:
    """Validate declared compatibility and exact bytes, without loading Hailo."""
    manifest = load_manifest(manifest_path)
    artifact = directory / manifest["artifact"]
    if not stat.S_ISREG(artifact.lstat().st_mode):
        raise ValueError("HEF must be a regular file, not a symlink")
    if sha256_file(artifact) != manifest["sha256"]:
        raise ValueError("HEF SHA256 mismatch")
    return manifest


def _installed_version(store: Path, model_id: str) -> Path:
    # Exact ID selection also excludes absolute paths, traversal and staging names.
    if model_id != SELECTED["model_id"]:
        raise ValueError("unsupported model ID")
    version = store / model_id
    if not stat.S_ISDIR(version.lstat().st_mode):
        raise ValueError("installed version must be a directory, not a symlink")
    validate_model(version / "manifest.json", version)
    return version


def _sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _store_lock(store: Path):
    """Serialize manual mutations; the image supplies a root-owned 0755 store."""
    info = store.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
        raise ValueError("model store must be a real directory without group/other write access")
    if info.st_uid != os.geteuid():
        raise ValueError("model administration must run as the store owner")
    fd = os.open(store / ".admin.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def install_model(manifest_path: Path, source: Path, store: Path = STORE) -> Path:
    """Publish a validated copy by same-filesystem rename; never replace a version."""
    manifest = load_manifest(manifest_path)
    with _store_lock(store):
        destination = store / manifest["model_id"]
        if os.path.lexists(destination):
            validate_model(manifest_path, source)
            return _installed_version(store, manifest["model_id"])
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=store) as temporary:
            stage = Path(temporary)
            artifact = source / manifest["artifact"]
            if not stat.S_ISREG(artifact.lstat().st_mode):
                raise ValueError("HEF must be a regular file, not a symlink")
            shutil.copyfile(artifact, stage / manifest["artifact"])
            (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
            validate_model(stage / "manifest.json", stage)
            for path in stage.iterdir():
                path.chmod(0o644)
                with path.open("rb") as stream:
                    os.fsync(stream.fileno())
            stage.chmod(0o755)
            _sync_directory(stage)
            os.rename(stage, destination)
            _sync_directory(store)
        return destination


def _replace_pointer(store: Path, name: str, model_id: str) -> Path:
    version = _installed_version(store, model_id)
    with tempfile.TemporaryDirectory(prefix=".pointer-", dir=store) as temporary:
        link = Path(temporary) / "link"
        link.symlink_to(version.name)
        os.replace(link, store / name)
        _sync_directory(store)
    return version


def activate_model(model_id: str, store: Path = STORE) -> Path:
    """Switch only the storage pointer; no service restart or runtime qualification."""
    with _store_lock(store):
        return _replace_pointer(store, "current", model_id)


def qualify_model(model_id: str, store: Path = STORE) -> Path:
    """Explicit operator attestation of qualification; never inferred from current."""
    with _store_lock(store):
        return _replace_pointer(store, "known-good", model_id)


def rollback_model(store: Path = STORE) -> Path:
    with _store_lock(store):
        model_id = os.readlink(store / "known-good")
        return _replace_pointer(store, "current", model_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "install"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("source", type=Path, help="directory containing the HEF")
    for name in ("activate", "qualify"):
        commands.add_parser(name).add_argument("model_id")
    commands.add_parser("rollback")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            validate_model(args.manifest, args.source)
            print("Valid selected-model manifest and SHA256; output ABI remains unverified.")
        elif args.command == "install":
            print(
                f"Installed or already installed: {install_model(args.manifest, args.source, args.store)}"
            )
        elif args.command == "rollback":
            print(rollback_model(args.store))
        else:
            action = {"activate": activate_model, "qualify": qualify_model}[args.command]
            print(action(args.model_id, args.store))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Model operation failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
