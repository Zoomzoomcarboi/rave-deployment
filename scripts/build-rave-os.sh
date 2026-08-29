#!/usr/bin/env bash
set -euo pipefail

repository_root=$(realpath -e -- "$(dirname -- "${BASH_SOURCE[0]}")/..")
lock_file="$repository_root/image/rpi-image-gen.lock.json"
output_input=${1:-"$repository_root/build/rave-os-gate2b"}
engineering_key_input=${RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE:-}

command -v python3 >/dev/null || { printf 'error: python3 is required\n' >&2; exit 2; }
test -f "$lock_file" || { printf 'error: missing %s\n' "$lock_file" >&2; exit 2; }
test -n "$engineering_key_input" || {
  printf 'error: RAVE_ENGINEERING_SSH_PUBLIC_KEY_FILE is required for this engineering image\n' >&2
  exit 2
}
engineering_key_input=$(realpath -e -- "$engineering_key_input")
test -f "$engineering_key_input" || {
  printf 'error: engineering SSH public-key input is not a file\n' >&2
  exit 2
}
engineering_public_key=$(python3 "$repository_root/scripts/engineering_ssh_key.py" \
  --input "$engineering_key_input")
engineering_key_fingerprint=$(python3 "$repository_root/scripts/engineering_ssh_key.py" \
  --input "$engineering_key_input" --fingerprint)
command -v docker >/dev/null || { printf 'error: docker is required\n' >&2; exit 2; }
command -v git >/dev/null || { printf 'error: git is required\n' >&2; exit 2; }

readarray -t lock < <(python3 - "$lock_file" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
for key in ("repository", "tag", "commit", "container_image"):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"invalid builder lock field: {key}")
    print(value)
PY
)
builder_repository=${lock[0]}
builder_tag=${lock[1]}
builder_commit=${lock[2]}
container_image=${lock[3]}

mkdir -p -- "$output_input"
output_dir=$(realpath -e -- "$output_input")
test -n "$output_dir"
test "$output_dir" != "/"
test "$output_dir" != "$repository_root"

builder_dir="$output_dir/rpi-image-gen"
if [[ ! -e $builder_dir ]]; then
  printf 'Retrieving rpi-image-gen %s into %s\n' "$builder_tag" "$builder_dir"
  git clone --quiet --depth 1 --branch "$builder_tag" "$builder_repository" "$builder_dir"
fi
test -d "$builder_dir/.git" || { printf 'error: invalid builder checkout: %s\n' "$builder_dir" >&2; exit 2; }
resolved_commit=$(git -C "$builder_dir" rev-parse HEAD)
[[ $resolved_commit == "$builder_commit" ]] || {
  printf 'error: builder commit %s does not match lock %s\n' "$resolved_commit" "$builder_commit" >&2
  exit 2
}
[[ -z $(git -C "$builder_dir" status --porcelain) ]] || {
  printf 'error: builder checkout contains local changes: %s\n' "$builder_dir" >&2
  exit 2
}

rave_commit=$(git -C "$repository_root" rev-parse HEAD)
rave_dirty=false
[[ -z $(git -C "$repository_root" status --porcelain) ]] || rave_dirty=true
version="gate2b-${rave_commit:0:12}"
artifact_denylist=$(printf '%s\n%s\n%s\n%s\n' \
  "${USER:-${LOGNAME:-}}" "${HOME:-}" "${HOSTNAME:-}" "$repository_root")

printf 'Builder: %s %s\n' "$builder_tag" "$builder_commit"
printf 'Container: %s\n' "$container_image"
printf 'Output: %s\n' "$output_dir"
printf 'The build uses an ephemeral privileged container; no block device is passed.\n'

docker run --rm --privileged \
  --env DEBIAN_FRONTEND=noninteractive \
  --env "RAVE_ARTIFACT_DENYLIST=$artifact_denylist" \
  --volume "$builder_dir:/builder:ro" \
  --volume "$repository_root:/rave:ro" \
  --volume "$output_dir:/out" \
  "$container_image" \
  bash -c '
    set -euo pipefail
    mountpoint -q /proc/sys/fs/binfmt_misc || mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc
    apt-get update
    /builder/install_deps.sh
    useradd --uid 1000 --home-dir /tmp/rave-builder-home --create-home --shell /bin/bash imagebuilder
    install -d -m 0755 /out/work /out/work/cache
    install -d -m 0700 \
      /tmp/rave-builder-home/.config \
      /tmp/rave-builder-home/.config/containers \
      /tmp/rave-builder-home/.local \
      /tmp/rave-builder-home/.local/share \
      /tmp/rave-builder-home/.local/share/containers
    chown -R 1000:1000 /out /tmp/rave-builder-home
    chmod 0755 /out /out/work /out/work/cache
    setpriv --reuid=1000 --regid=1000 --init-groups \
      env HOME=/tmp/rave-builder-home PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      /builder/rpi-image-gen build -B /out/work -S /rave/image -c rave-os.yaml -- \
      "IGconf_artefact_version=$1" "IGconf_rave_ssh_public_key=$7"
    rootfs="/out/work/chroot-$1/filesystem"
    artifact="/out/work/deploy-$1/rave-os-gate2b.img.zst"
    setpriv --reuid=1000 --regid=1000 --init-groups \
      env HOME=/tmp/rave-builder-home PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
      podman unshare python3 /rave/scripts/verify_rave_image.py \
      --rootfs "$rootfs" --artifact "$artifact" --report /out/artifact-verification.json
    python3 /rave/scripts/verify_rave_image.py --write-provenance /out/provenance.json \
      --artifact "$artifact" --rave-commit "$2" --rave-dirty "$3" \
      --builder-tag "$4" --builder-commit "$5" --container-image "$6" \
      --configuration image/config/rave-os.yaml \
      --engineering-ssh-public-key-fingerprint "$8"
  ' -- "$version" "$rave_commit" "$rave_dirty" "$builder_tag" "$builder_commit" "$container_image" \
    "$engineering_public_key" "$engineering_key_fingerprint"

printf 'Build, artifact verification, and provenance generation completed.\n'
printf 'Artifact: %s/work/deploy-%s/rave-os-gate2b.img.zst\n' "$output_dir" "$version"
printf 'Provenance: %s/provenance.json\n' "$output_dir"
