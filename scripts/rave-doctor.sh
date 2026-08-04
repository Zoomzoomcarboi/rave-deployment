#!/usr/bin/env bash
set -u

fail=0
check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    printf '[PASS] %s\n' "$name"
  else
    printf '[FAIL] %s\n' "$name"
    fail=1
  fi
}

check "Raspberry Pi model file" test -r /proc/device-tree/model
check "Hailo runtime CLI" command -v hailortcli
check "Camera alias" test -e /dev/rave-camera
check "RAVE configuration" test -r /etc/rave/rave.toml
check "RAVE model bundle" test -r /opt/rave/models/current/manifest.json
check "Ethernet interface" test -d /sys/class/net/eth0

exit "$fail"
