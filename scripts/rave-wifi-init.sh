#!/bin/sh
set -eu

NMCLI=/usr/bin/nmcli
IP=/usr/bin/ip
SLEEP=/usr/bin/sleep
INTERFACE=wlan0
CONNECTION=RAVE-Setup
ADDRESS=192.168.77.1/24

log() {
  printf 'rave-wifi-init: %s\n' "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

log 'enabling the NetworkManager Wi-Fi radio'
"$NMCLI" --wait 10 radio wifi on || fail 'NetworkManager could not enable the Wi-Fi radio'
radio_state=$("$NMCLI" --wait 2 -t -f WIFI general 2>/dev/null || true)
[ "$radio_state" = enabled ] || fail "NetworkManager Wi-Fi radio state is not enabled: ${radio_state:-unknown}"
log 'NetworkManager reports the Wi-Fi radio enabled'

attempt=0
device_type=
while [ "$attempt" -lt 10 ]; do
  if device_type=$("$NMCLI" --wait 1 -g GENERAL.TYPE device show "$INTERFACE" 2>/dev/null) && \
      [ "$device_type" = wifi ]; then
    break
  fi
  attempt=$((attempt + 1))
  "$SLEEP" 1
done
[ "$device_type" = wifi ] || fail 'wlan0 did not become a NetworkManager Wi-Fi device within the bounded wait'
log 'wlan0 is available to NetworkManager'

active_connection=$("$NMCLI" --wait 2 -g GENERAL.CONNECTION device show "$INTERFACE" 2>/dev/null || true)
if [ "$active_connection" = "$CONNECTION" ]; then
  log 'RAVE-Setup is already active; leaving the connection undisturbed'
else
  log 'activating the existing RAVE-Setup profile on wlan0'
  "$NMCLI" --wait 20 connection up id "$CONNECTION" ifname "$INTERFACE" || \
    fail 'RAVE-Setup activation failed'
fi

attempt=0
addresses=
while [ "$attempt" -lt 10 ]; do
  addresses=$("$IP" -4 -o address show dev "$INTERFACE" 2>/dev/null || true)
  case " $addresses " in
    *" inet $ADDRESS "*)
      log 'verified 192.168.77.1/24 on wlan0'
      exit 0
      ;;
  esac
  attempt=$((attempt + 1))
  "$SLEEP" 0.5
done
fail 'RAVE-Setup activated without the required 192.168.77.1/24 address on wlan0'
