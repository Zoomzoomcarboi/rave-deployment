#!/usr/bin/env bash
set -euo pipefail

unit_source=${1:-systemd}
systemd_analyze=${SYSTEMD_ANALYZE:-systemd-analyze}

if [[ ! -d $unit_source ]]; then
  printf 'Systemd unit directory not found: %s\n' "$unit_source" >&2
  exit 2
fi
if ! command -v "$systemd_analyze" >/dev/null 2>&1; then
  printf 'systemd-analyze is required for systemd unit verification\n' >&2
  exit 2
fi

verification_dir=$(mktemp -d "${TMPDIR:-/tmp}/rave-ci-units.XXXXXX")
trap 'rm -rf -- "$verification_dir"' EXIT

unit_suffixes=(service socket target timer path)
verification_units=()
for suffix in "${unit_suffixes[@]}"; do
  while IFS= read -r -d '' unit; do
    destination="$verification_dir/$(basename "$unit")"
    cp -- "$unit" "$destination"
    verification_units+=("$destination")
  done < <(find "$unit_source" -maxdepth 1 -type f -name "*.$suffix" -print0 | sort -z)
done

if ((${#verification_units[@]} == 0)); then
  printf 'No systemd units found in %s\n' "$unit_source" >&2
  exit 2
fi

# The generic CI host does not provide RAVE's service account or installed
# /opt/rave executables. Normalize only those host-specific service fields;
# dependency and ordering directives remain unchanged and are fully verified.
for unit in "$verification_dir"/*.service; do
  sed -E -i \
    -e 's|^ExecStart=.*|ExecStart=/usr/bin/true|' \
    -e 's|^User=.*|User=root|' \
    -e 's|^Group=.*|Group=root|' \
    "$unit"
done

# Raspberry Pi OS supplies NetworkManager.service, while the generic GitHub
# runner does not. This CI-only stub models that confirmed external target-OS
# dependency. Internal RAVE dependencies must resolve to the real staged units.
printf '%s\n' \
  '[Unit]' \
  'Description=CI-only NetworkManager target-OS dependency stub' \
  '' \
  '[Service]' \
  'Type=oneshot' \
  'ExecStart=/usr/bin/true' \
  > "$verification_dir/NetworkManager.service"

SYSTEMD_UNIT_PATH="$verification_dir:/usr/local/lib/systemd/system:/usr/lib/systemd/system:/lib/systemd/system" \
  "$systemd_analyze" verify --man=no "${verification_units[@]}"
