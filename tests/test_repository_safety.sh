#!/usr/bin/env bash
set -euo pipefail

prohibited=(
  "release/rave-os-v1.img"
  "release/rave-os-v1.img.xz"
  "release/rave-os-v1.img.zst"
  "models/network.bin"
  "models/network.blob"
  "models/releases/manifest.json"
  "models/rave-model-v1.tar"
  "models/rave-model-v1.tar.zst"
  "models/network.model.tar.xz"
  "release/model-bundle.tar.zst"
)

for path in "${prohibited[@]}"; do
  if printf '%s\n' "$path" |
    scripts/check-repository-safety.sh --artifact-paths-from-stdin >/dev/null 2>&1; then
    printf 'Expected prohibited artifact path to fail: %s\n' "$path" >&2
    exit 1
  fi
done

printf '%s\n' "models/example-manifest.json" |
  scripts/check-repository-safety.sh --artifact-paths-from-stdin
