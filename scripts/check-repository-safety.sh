#!/usr/bin/env bash
set -euo pipefail

fail=0

artifact_pattern='(\.(avi|mkv|mov|mp4|mpeg|mpg|h264|h265|yuv|raw|pcap|pcapng|hef|onnx|pt|pth|tflite|tfl|engine|plan|trt|weights|bin|blob|safetensors|ckpt|deb|rpm|whl)$|\.img(\.(xz|zst))?$|\.tar\.(gz|bz2|xz|zst)$|(^|/)rave-model-[^/]+\.tar(\.[^/]+)?$|\.model\.tar(\.[^/]+)?$|(^|/)models/releases/)'

check_artifact_paths() {
  local found=0
  local path
  while IFS= read -r path; do
    if [[ "$path" =~ $artifact_pattern ]]; then
      printf 'Prohibited binary or capture is tracked: %s\n' "$path" >&2
      found=1
    fi
  done
  return "$found"
}

if [[ "${1:-}" == "--artifact-paths-from-stdin" ]]; then
  check_artifact_paths
  exit $?
fi

if ! git ls-files | check_artifact_paths; then
  fail=1
fi

while IFS= read -r finding; do
  printf 'Possible private key or credential pattern: %s\n' "$finding" >&2
  fail=1
done < <(
  git grep -nEI \
    -- '-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|(api[_-]?key|secret[_-]?key|access[_-]?token)[[:space:]]*[:=][[:space:]]*["'\''][^"'\'']{8,}' \
    -- ':!scripts/check-repository-safety.sh' || true
)

exit "$fail"
