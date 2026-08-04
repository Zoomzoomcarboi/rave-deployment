#!/usr/bin/env bash
set -euo pipefail

# Developer/repair path only. Normal users should flash a signed RAVE OS image.

if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "Unsupported architecture: RAVE requires 64-bit ARM on Raspberry Pi 5." >&2
  exit 1
fi

if [[ ! -r /proc/device-tree/model ]] || ! grep -q "Raspberry Pi 5" /proc/device-tree/model; then
  echo "Unsupported board: Raspberry Pi 5 was not detected." >&2
  exit 1
fi

if ! command -v hailortcli >/dev/null 2>&1; then
  echo "Hailo runtime not detected. Install the pinned RAVE-supported Hailo packages first." >&2
  exit 1
fi

echo "Mock installer validation passed."
echo "TODO: add signed APT repository and install rave-edge package."
