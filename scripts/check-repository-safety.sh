#!/usr/bin/env bash
set -euo pipefail

artifact_pattern='(\.(avi|mkv|mov|mp4|mpeg|mpg|h264|h265|yuv|raw|pcap|pcapng|hef|onnx|pt|pth|tflite|tfl|engine|plan|trt|weights|bin|blob|safetensors|ckpt|deb|rpm|whl)$|\.img(\.(xz|zst))?$|\.tar\.(gz|bz2|xz|zst)$|(^|/)rave-model-[^/]+\.tar(\.[^/]+)?$|\.model\.tar(\.[^/]+)?$|(^|/)models/releases/)'
private_key_pattern='-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE'" KEY-----"
token_name_pattern='(api[_-]?key|secret[_-]?key|access[_-]?to'
token_pattern="${token_name_pattern}ken)[[:space:]]*[:=][[:space:]]*[^[:space:]]{8,}"
secret_pattern="$private_key_pattern|AKIA[0-9A-Z]{16}|$token_pattern"
linux_home_prefix='/ho'
mac_home_prefix='/Us'
windows_home_prefix='[A-Za-z]:\\Us'
home_pattern="(^|[^[:alnum:]_])(${linux_home_prefix}me/[^/[:space:]]+|${mac_home_prefix}ers/[^/[:space:]]+|${windows_home_prefix}ers\\\\[^\\\\[:space:]]+)(/|\\\\)"
wifi_secret_pattern='(^|[[:space:]])(wifi[-_ ]?password|psk)[[:space:]]*[:=][[:space:]]*[^[:space:]#]+'
fail=0

check_artifact_paths() {
  local found=0 path
  while IFS= read -r path; do
    if [[ "$path" =~ $artifact_pattern ]]; then
      printf 'Prohibited binary or capture path: %s\n' "$path" >&2
      found=1
    fi
  done
  return "$found"
}

identity_values() {
  [[ -n ${RAVE_IDENTITY_DENYLIST:-} ]] && printf '%s\n' "$RAVE_IDENTITY_DENYLIST"
  return 0
}

escape_ere() {
  printf '%s' "$1" | sed 's/[][\\.^$*+?(){}|]/\\&/g'
}

scan_ambient_identity() {
  local display=$1 file=$2 ambient_user ambient_hostname escaped_user escaped_hostname pattern
  ambient_user=${USER:-${LOGNAME:-}}
  ambient_hostname=${HOSTNAME:-}

  if [[ -n ${HOME:-} && ${#HOME} -ge 5 ]] && grep -nF -- "$HOME" "$file" >/dev/null; then
    printf 'Ambient build home found in %s\n' "$display" >&2; fail=1
  fi

  if [[ -n $ambient_user ]]; then
    escaped_user=$(escape_ere "$ambient_user")
    pattern="(${linux_home_prefix}me/|${mac_home_prefix}ers/)${escaped_user}/|${windows_home_prefix}ers\\\\${escaped_user}\\\\|(^|[^[:alnum:]_])(user(name)?|owner)[[:space:]]*[:=][[:space:]]*['\"]?${escaped_user}([^[:alnum:]_.-]|$)|(^|[^[:alnum:]_.-])${escaped_user}@[[:alnum:]_.-]+"
    if grep -nEI -- "$pattern" "$file" >/dev/null; then
      printf 'Contextual ambient build user found in %s\n' "$display" >&2; fail=1
    fi
  fi

  if [[ -n $ambient_hostname ]]; then
    escaped_hostname=$(escape_ere "$ambient_hostname")
    pattern="(^|[^[:alnum:]_])(hostname|host|machine)[[:space:]]*[:=][[:space:]]*['\"]?${escaped_hostname}([^[:alnum:]_.-]|$)"
    if grep -nEI -- "$pattern" "$file" >/dev/null; then
      printf 'Contextual ambient build hostname found in %s\n' "$display" >&2; fail=1
    fi
  fi
}

scan_file() {
  local display=$1 file=$2 basename value
  basename=${file##*/}
  case "$file" in
    image/overlays/etc/NetworkManager/system-connections/rave-setup.nmconnection|etc/NetworkManager/system-connections/rave-setup.nmconnection)
      ;;
    *.nmconnection|*/NetworkManager/system-connections/*)
      printf 'Unintended NetworkManager profile: %s\n' "$display" >&2; fail=1 ;;
  esac
  case "$basename" in
    ssh_host_*|id_rsa|id_dsa|id_ecdsa|id_ed25519)
      printf 'Unintended SSH key material: %s\n' "$display" >&2; fail=1 ;;
  esac
  grep -Iq . "$file" 2>/dev/null || return 0
  if grep -nEI -- "$secret_pattern" "$file" >/dev/null; then
    printf 'Possible private key or credential pattern: %s\n' "$display" >&2; fail=1
  fi
  if [[ "$file" != *.md ]] && grep -nEI -- "$home_pattern" "$file" >/dev/null; then
    printf 'Developer user-home path in runtime source: %s\n' "$display" >&2; fail=1
  fi
  if grep -nEI -- "$wifi_secret_pattern" "$file" >/dev/null; then
    printf 'Possible Wi-Fi credential material: %s\n' "$display" >&2; fail=1
  fi
  scan_ambient_identity "$display" "$file"
  while IFS= read -r value; do
    [[ ${#value} -ge 5 ]] || continue
    if grep -nF -- "$value" "$file" >/dev/null; then
      printf 'Injected build/developer identity found in %s\n' "$display" >&2; fail=1
    fi
  done < <(identity_values)
}

scan_root() {
  local root=$1 file relative
  while IFS= read -r -d '' file; do
    relative=${file#"$root"/}
    if ! printf '%s\n' "$relative" | check_artifact_paths >/dev/null 2>&1; then fail=1; fi
    scan_file "$relative" "$file"
  done < <(find "$root" -type f -print0)
}

if [[ ${1:-} == "--artifact-paths-from-stdin" ]]; then
  check_artifact_paths
  exit $?
fi
if [[ ${1:-} == "--scan-root" ]]; then
  [[ $# -eq 2 && -d $2 ]] || { printf 'usage: %s --scan-root DIRECTORY\n' "$0" >&2; exit 2; }
  scan_root "$2"
  exit "$fail"
fi

if ! git ls-files --cached --others --exclude-standard | check_artifact_paths; then fail=1; fi
while IFS= read -r file; do
  [[ -f $file ]] && scan_file "$file" "$file"
done < <(git ls-files --cached --others --exclude-standard)
exit "$fail"
