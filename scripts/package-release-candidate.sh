#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  printf 'usage: %s SOURCE.img.zst PROVENANCE.json OUTPUT_DIRECTORY\n' "$0" >&2
  exit 2
fi
source_input=$1
provenance_input=$2
output_input=$3
[[ -f $source_input && -s $source_input ]] || { printf 'error: source artifact is not a non-empty regular file: %s\n' "$source_input" >&2; exit 2; }
[[ -f $provenance_input && -s $provenance_input ]] || { printf 'error: provenance is not a non-empty regular file: %s\n' "$provenance_input" >&2; exit 2; }
command -v zstd >/dev/null
command -v xz >/dev/null
command -v sha256sum >/dev/null
command -v python3 >/dev/null
source_artifact=$(realpath -e -- "$source_input")
provenance=$(realpath -e -- "$provenance_input")
mkdir -p -- "$output_input"
output_dir=$(realpath -e -- "$output_input")
repository_root=$(git -C "$(dirname -- "$0")" rev-parse --show-toplevel)
tracked_release=$(realpath -e -- "$repository_root/release")
case "$output_dir/" in
  "$tracked_release/"*) printf 'error: candidate output must not be written under tracked release/: %s\n' "$output_dir" >&2; exit 2 ;;
esac
raw_image="$output_dir/RAVE-OS-Pi5-Gate2B-Candidate.img"
xz_image="$raw_image.xz"
checksums="$output_dir/SHA256SUMS"
release_manifest="$output_dir/release.json"
zstd -t -- "$source_artifact"
source_size=$(stat -c %s -- "$source_artifact")
(( source_size >= 1048576 )) || { printf 'error: source artifact is implausibly small\n' >&2; exit 2; }
source_sha=$(sha256sum -- "$source_artifact" | cut -d ' ' -f 1)
python3 - "$provenance" "$(basename -- "$source_artifact")" "$source_size" "$source_sha" <<'PY'
import json
import re
import sys
from pathlib import Path

path, filename, size_text, digest = sys.argv[1:]
try:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    artifact = record["artifact"]
    required = (
        record["schema_version"],
        record["rave_repository_commit"],
        record["rave_worktree_dirty"],
        record["build_timestamp_utc"],
        record["builder_container"],
        record["configuration"],
        record["target"]["architecture"],
        record["target"]["platform"],
        record["rpi_image_gen"]["tag"],
        record["rpi_image_gen"]["commit"],
        record["reproducibility"],
    )
except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
    raise SystemExit(f"error: incomplete or invalid provenance: {exc}")
if required[0] != 1:
    raise SystemExit("error: unsupported provenance schema")
if not isinstance(required[1], str) or not re.fullmatch(r"[0-9a-f]{40}", required[1]):
    raise SystemExit("error: provenance has invalid repository commit")
if not isinstance(required[2], bool):
    raise SystemExit("error: provenance has invalid dirty-worktree state")
if required[6:] and (required[6] != "arm64" or required[7] != "raspberry-pi-5"):
    raise SystemExit("error: provenance target is not Raspberry Pi 5 arm64")
expected = (artifact.get("filename"), artifact.get("size_bytes"), artifact.get("sha256"))
actual = (filename, int(size_text), digest)
if expected != actual:
    raise SystemExit(f"error: source artifact does not match provenance: expected {expected!r}, got {actual!r}")
PY
zstd -d -f -o "$raw_image" -- "$source_artifact"
[[ -f $raw_image && -s $raw_image ]] || { printf 'error: extracted image is empty\n' >&2; exit 2; }
raw_size=$(stat -c %s -- "$raw_image")
(( raw_size >= 268435456 )) || { printf 'error: extracted image is implausibly small\n' >&2; exit 2; }
raw_sha=$(sha256sum -- "$raw_image" | cut -d ' ' -f 1)
xz -T0 -f -6 --keep -- "$raw_image"
[[ -f $xz_image && -s $xz_image ]] || { printf 'error: compressed candidate is empty\n' >&2; exit 2; }
xz -t -- "$xz_image"
xz_size=$(stat -c %s -- "$xz_image")
(( xz_size >= 1048576 )) || { printf 'error: compressed candidate is implausibly small\n' >&2; exit 2; }
xz_sha=$(sha256sum -- "$xz_image" | cut -d ' ' -f 1)
printf '%s  %s\n' "$xz_sha" "$(basename -- "$xz_image")" > "$checksums"
python3 - "$provenance" "$release_manifest" "$(basename -- "$xz_image")" "$xz_size" "$xz_sha" "$raw_size" "$raw_sha" "$source_size" "$source_sha" <<'PY'
import json
import sys
from pathlib import Path

provenance_path, output_path, image, xz_size, xz_sha, raw_size, raw_sha, source_size, source_sha = sys.argv[1:]
provenance = json.loads(Path(provenance_path).read_text(encoding="utf-8"))
record = {
    "schema_version": 1,
    "name": "RAVE OS Gate 2B Candidate",
    "release_tag": None,
    "status": "candidate_not_published",
    "target": "Raspberry Pi 5",
    "architecture": "arm64",
    "image": image,
    "image_download_size": int(xz_size),
    "image_download_sha256": xz_sha,
    "extract_size": int(raw_size),
    "extract_sha256": raw_sha,
    "init_format": "none",
    "image_source_commit": provenance["rave_repository_commit"],
    "image_source_worktree_dirty": provenance["rave_worktree_dirty"],
    "source_artifact": {
        "filename": provenance["artifact"]["filename"],
        "size": int(source_size),
        "sha256": source_sha,
    },
    "rpi_image_gen": provenance["rpi_image_gen"],
    "builder_container": provenance["builder_container"],
    "build_timestamp_utc": provenance["build_timestamp_utc"],
    "build_provenance": provenance,
    "validation": {
        "gate_2b_image_build": "PASS",
        "artifact_verifier": "PASS",
        "physical_pi_boot": "NOT_YET_VALIDATED",
        "production_ready": False,
        "road_ready": False,
    },
}
Path(output_path).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
printf 'Candidate: %s\nChecksums: %s\nManifest: %s\n' "$xz_image" "$checksums" "$release_manifest"
