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

if scripts/package-release-candidate.sh "$PWD/does-not-exist.img.zst" "$PWD/does-not-exist-provenance.json" "$PWD/build/guard-fixture" >/dev/null 2>&1; then
  printf 'Expected missing release source artifact to fail\n' >&2
  exit 1
fi
empty_source=$(mktemp)
if scripts/package-release-candidate.sh "$empty_source" "$PWD/does-not-exist-provenance.json" "$PWD/build/guard-fixture" >/dev/null 2>&1; then
  printf 'Expected empty release source artifact to fail\n' >&2
  exit 1
fi
rm -f "$empty_source"

fixture_root=$(mktemp -d)
trap 'rm -rf "$fixture_root"' EXIT
mkdir -p "$fixture_root/pass/etc/rave" "$fixture_root/fail/etc/rave"
printf '%s\n' 'state_dir=/var/lib/rave' > "$fixture_root/pass/etc/rave/runtime.conf"
env -u RAVE_IDENTITY_DENYLIST \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/pass"
RAVE_IDENTITY_DENYLIST= \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/pass"
printf '%s\n' 'The task runner handles bounded checks.' > "$fixture_root/pass/roadmap.md"
env "US""ER=runner" "HO""ME=/tmp/rave-ci-home" "HOST""NAME=ci-build-host" \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/pass"

printf '%s%s\n' 'runtime=/home/' 'runner/work/rave' > "$fixture_root/fail/etc/rave/runtime.conf"
if env "US""ER=runner" "HO""ME=/tmp/rave-ci-home" "HOST""NAME=ci-build-host" \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected contextual ambient user home fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
printf '%s%s\n' 'prompt=run' 'ner@ci-build-host' > "$fixture_root/fail/etc/rave/runtime.conf"
if env "US""ER=runner" "HO""ME=/tmp/rave-ci-home" "HOST""NAME=ci-build-host" \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected contextual ambient shell prompt fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
printf '%s%s\n' 'host' 'name=ci-build-host' > "$fixture_root/fail/etc/rave/runtime.conf"
if env "US""ER=runner" "HO""ME=/tmp/rave-ci-home" "HOST""NAME=ci-build-host" \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected contextual ambient hostname fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"

printf '%s%s\n' 'runtime=/ho' 'me/example/operator/rave' > "$fixture_root/fail/etc/rave/runtime.conf"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected developer home path fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
printf '%s%s\n' 'runtime=/Us' 'ers/example/rave' > "$fixture_root/fail/etc/rave/runtime.conf"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected macOS user path fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
printf '%s%s\n' 'runtime=C:\Us' 'ers\example\rave' > "$fixture_root/fail/etc/rave/runtime.conf"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected Windows user path fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
printf '%s\n' 'machine=ci-private-builder' > "$fixture_root/fail/etc/rave/runtime.conf"
if env "US""ER=runner" RAVE_IDENTITY_DENYLIST=ci-private-builder \
  scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected injected identity fixture to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/etc/rave/runtime.conf"
mkdir -p "$fixture_root/fail/etc/NetworkManager/system-connections"
printf '%s%s\n' 'p' 'sk=fixture-secret' > "$fixture_root/fail/etc/NetworkManager/system-connections/user.nmconnection"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected NetworkManager credential fixture to fail\n' >&2
  exit 1
fi

rm -rf "$fixture_root/fail/etc"
mkdir -p "$fixture_root/fail/docs"
printf '%s\n%s%s\n' \
  'Documentation must still reject secret material:' \
  "-----BEGIN PRIVATE" " KEY-----" > "$fixture_root/fail/docs/security.md"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected Markdown private-key marker fixture to fail\n' >&2
  exit 1
fi

rm -f "$fixture_root/fail/docs/security.md"
printf '%s%s\n' 'wifi_' 'password=not-a-real-placeholder' > "$fixture_root/fail/docs/network.md"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected Markdown Wi-Fi credential assignment fixture to fail\n' >&2
  exit 1
fi

rm -rf "$fixture_root/fail/docs"
mkdir -p "$fixture_root/fail/scripts" "$fixture_root/fail/tests"
printf '%s%s\n' 'access_' 'token=fixture-secret-value' > \
  "$fixture_root/fail/scripts/check-repository-safety.sh"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected checker-named credential fixture to fail\n' >&2
  exit 1
fi

rm -f "$fixture_root/fail/scripts/check-repository-safety.sh"
printf '%s%s\n' "-----BEGIN PRIVATE" " KEY-----" > \
  "$fixture_root/fail/tests/test_repository_safety.sh"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected safety-test-named private-key fixture to fail\n' >&2
  exit 1
fi

rm -f "$fixture_root/fail/tests/test_repository_safety.sh"
mkdir -p "$fixture_root/pass/tests"
printf '%s\n' \
  'wifi_password=synthetic-value  # RAVE-SAFETY: synthetic Wi-Fi credential fixture' > \
  "$fixture_root/pass/tests/test_synthetic_wifi.py"
scripts/check-repository-safety.sh --scan-root "$fixture_root/pass"

printf '%s\n' \
  'psk=correct-horse-battery-staple  # RAVE-SAFETY: synthetic Wi-Fi credential fixture # RAVE-SAFETY: scanner negative-test definition' > \
  "$fixture_root/fail/tests/test_realistic_psk.py"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected realistic test PSK to fail despite fixture marker\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/tests/test_realistic_psk.py"

printf '%s\n' \
  'wifi_password=realistic-network-password  # RAVE-SAFETY: synthetic Wi-Fi credential fixture # RAVE-SAFETY: scanner negative-test definition' > \
  "$fixture_root/fail/tests/test_realistic_wifi_password.py"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected realistic test Wi-Fi password to fail despite fixture marker\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/tests/test_realistic_wifi_password.py"

printf '%s\n' \
  'psk=realistic-network-password; psk=synthetic-value  # RAVE-SAFETY: synthetic Wi-Fi credential fixture # RAVE-SAFETY: scanner negative-test definition' > \
  "$fixture_root/fail/tests/test_marker_does_not_hide_realistic_psk.py"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected fixture marker not to hide another credential on the same line\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/tests/test_marker_does_not_hide_realistic_psk.py"

mkdir -p "$fixture_root/fail/opt/rave"
printf '%s\n' \
  'psk=synthetic-value  # RAVE-SAFETY: synthetic Wi-Fi credential fixture' > \
  "$fixture_root/fail/opt/rave/runtime.conf"
if scripts/check-repository-safety.sh --scan-root "$fixture_root/fail" >/dev/null 2>&1; then
  printf 'Expected production synthetic credential marker to fail\n' >&2
  exit 1
fi
rm -f "$fixture_root/fail/opt/rave/runtime.conf"

workflow=.github/workflows/ci.yml
grep -F 'RAVE_IDENTITY_DENYLIST: ${{ secrets.RAVE_IDENTITY_DENYLIST }}' "$workflow" >/dev/null
if grep -F 'Repository safety requires RAVE_IDENTITY_DENYLIST' "$workflow" >/dev/null; then
  printf 'CI safety gate must allow an empty optional identity denylist\n' >&2
  exit 1
fi
grep -F 'tests/test_repository_safety.sh' "$workflow" >/dev/null
grep -F 'scripts/check-repository-safety.sh' "$workflow" >/dev/null
