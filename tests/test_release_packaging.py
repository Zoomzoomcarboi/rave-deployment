import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGER = ROOT / "scripts/package-release-candidate.sh"
RAW_MINIMUM = 256 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def validated_build(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    if not shutil.which("zstd") or not shutil.which("xz"):
        pytest.skip("release packaging requires zstd and xz")
    directory = tmp_path_factory.mktemp("validated-build")
    raw = directory / "source.img"
    with raw.open("wb") as stream:
        stream.write(os.urandom(2 * 1024 * 1024))
        stream.truncate(RAW_MINIMUM)
    artifact = directory / "rave-os-gate2b.img.zst"
    subprocess.run(["zstd", "-q", "-f", "-3", str(raw), "-o", str(artifact)], check=True)
    provenance = directory / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": {
                    "filename": artifact.name,
                    "sha256": sha256(artifact),
                    "size_bytes": artifact.stat().st_size,
                },
                "build_timestamp_utc": "2026-08-23T00:00:00+00:00",
                "builder_container": "example.invalid/builder@sha256:" + "1" * 64,
                "configuration": "image/config/rave-os-gate1.yaml",
                "rave_repository_commit": "a" * 40,
                "rave_worktree_dirty": False,
                "reproducibility": {
                    "bit_for_bit_reproducibility_claimed": False,
                    "builder_source_pinned": True,
                    "container_base_pinned": True,
                    "package_repositories_snapshot_pinned": False,
                },
                "rpi_image_gen": {"commit": "b" * 40, "tag": "v2.7.0"},
                "target": {"architecture": "arm64", "platform": "raspberry-pi-5"},
            }
        ),
        encoding="utf-8",
    )
    return artifact, provenance


def test_missing_and_zero_byte_artifacts_are_rejected(tmp_path: Path) -> None:
    provenance = tmp_path / "provenance.json"
    provenance.write_text("{}", encoding="utf-8")
    missing = subprocess.run(
        [str(PACKAGER), str(tmp_path / "missing.img.zst"), str(provenance), str(tmp_path / "candidate")],
        check=False,
    )
    assert missing.returncode != 0
    empty = tmp_path / "empty.img.zst"
    empty.touch()
    zero = subprocess.run(
        [str(PACKAGER), str(empty), str(provenance), str(tmp_path / "candidate")], check=False
    )
    assert zero.returncode != 0


def test_missing_and_mismatched_provenance_are_rejected(
    validated_build: tuple[Path, Path], tmp_path: Path
) -> None:
    artifact, provenance = validated_build
    missing = subprocess.run(
        [str(PACKAGER), str(artifact), str(tmp_path / "missing.json"), str(tmp_path / "missing")],
        check=False,
    )
    assert missing.returncode != 0
    record = json.loads(provenance.read_text(encoding="utf-8"))
    record["artifact"]["sha256"] = "0" * 64
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps(record), encoding="utf-8")
    result = subprocess.run(
        [str(PACKAGER), str(artifact), str(mismatch), str(tmp_path / "mismatch")], check=False
    )
    assert result.returncode != 0


def test_candidate_metadata_matches_files_and_does_not_change_tracked_release(
    validated_build: tuple[Path, Path], tmp_path: Path
) -> None:
    artifact, provenance = validated_build
    tracked_before = {
        path.relative_to(ROOT): sha256(path)
        for path in (ROOT / "release").iterdir()
        if path.is_file()
    }
    candidate = tmp_path / "candidate"
    subprocess.run([str(PACKAGER), str(artifact), str(provenance), str(candidate)], check=True)

    image = candidate / "RAVE-OS-Pi5-Gate2B-Candidate.img.xz"
    raw = candidate / "RAVE-OS-Pi5-Gate2B-Candidate.img"
    checksum_line = (candidate / "SHA256SUMS").read_text(encoding="utf-8").strip()
    assert checksum_line == f"{sha256(image)}  {image.name}"
    manifest = json.loads((candidate / "release.json").read_text(encoding="utf-8"))
    assert manifest["image_download_size"] == image.stat().st_size
    assert manifest["image_download_sha256"] == sha256(image)
    assert manifest["extract_size"] == raw.stat().st_size
    assert manifest["extract_sha256"] == sha256(raw)
    assert manifest["image_source_commit"] == "a" * 40
    assert manifest["image_source_worktree_dirty"] is False
    assert manifest["source_artifact"]["sha256"] == sha256(artifact)
    assert manifest["build_provenance"] == json.loads(provenance.read_text(encoding="utf-8"))
    tracked_after = {
        path.relative_to(ROOT): sha256(path)
        for path in (ROOT / "release").iterdir()
        if path.is_file()
    }
    assert tracked_after == tracked_before


def test_no_build_specific_checksum_is_tracked() -> None:
    assert not (ROOT / "release/SHA256SUMS").exists()
    assert not (ROOT / "release/release.json").exists()
    example = json.loads((ROOT / "release/release.json.example").read_text(encoding="utf-8"))
    assert "generated from" in example["image_download_sha256"]
