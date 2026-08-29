#!/usr/bin/env bash
set -u

export LANG=C
export LC_ALL=C

if (( EUID != 0 )); then
  printf 'FAIL: run this read-only validation as root on the RAVE engineering Pi\n' >&2
  exit 2
fi

failures=0

check() {
  local name=$1
  shift
  if "$@" >/dev/null 2>&1; then
    printf 'PASS: %s\n' "$name"
  else
    printf 'FAIL: %s\n' "$name"
    failures=$((failures + 1))
  fi
}

service_state_is() {
  local unit=$1 expected_active=$2 expected_sub=$3
  [[ $(systemctl show --property=ActiveState --value "$unit") == "$expected_active" ]] &&
    [[ $(systemctl show --property=SubState --value "$unit") == "$expected_sub" ]]
}

interface_has_only_address() {
  local interface=$1 expected=$2
  mapfile -t addresses < <(ip -4 -o address show dev "$interface" scope global | awk '{print $4}')
  [[ ${#addresses[@]} -eq 1 && ${addresses[0]} == "$expected" ]]
}

route_contract_isolated() {
  local -a routes
  mapfile -t routes < <(ip -4 route show dev eth0)
  [[ ${#routes[@]} -eq 1 ]] &&
    grep -Eq '^10\.77\.0\.0/24 .* scope link .* src 10\.77\.0\.1' <<<"${routes[0]}" &&
    ! ip -4 route show default | grep -q . &&
    ! ip -6 route show default | grep -q .
}

networkmanager_leaves_eth0_unmanaged() {
  [[ $(nmcli --terse --fields GENERAL.STATE device show eth0) == "GENERAL.STATE:10 (unmanaged)" ]]
}

rave_setup_is_active() {
  nmcli --terse --fields NAME,DEVICE connection show --active | grep -Fxq 'RAVE-Setup:wlan0'
}

listener_is_exact() {
  local port=$1 expected=$2
  mapfile -t addresses < <(ss -H -ltn4 "sport = :$port" | awk '{print $4}')
  [[ ${#addresses[@]} -eq 1 && ${addresses[0]} == "$expected" ]] &&
    ! ss -H -ltn6 "sport = :$port" | grep -q .
}

listener_port_is_present() {
  local port=$1
  [[ $(ss -H -ltn "sport = :$port" | wc -l) -eq 1 ]]
}

web_socket_is_management_bound() {
  [[ $(systemctl show rave-webd.socket --property=BindToDevice --value) == wlan0 ]] &&
    [[ $(systemctl show rave-webd.socket --property=ActiveState --value) == active ]] &&
    [[ $(systemctl show rave-webd.socket --property=SubState --value) == listening ]]
}

web_root_is_available() {
  curl --fail --silent --show-error --connect-timeout 3 --max-time 5 \
    http://192.168.77.1:8080/ >/dev/null
}

socket_activated_service_is_healthy() {
  local active sub result
  active=$(systemctl show rave-webd.service --property=ActiveState --value)
  sub=$(systemctl show rave-webd.service --property=SubState --value)
  result=$(systemctl show rave-webd.service --property=Result --value)
  [[ $active == active && $sub == running && $result == success ]] ||
    [[ $active == inactive && $sub == dead && $result == success ]]
}

networkd_socket_is_restricted() {
  local mode owner group
  mode=$(stat --format='%a' /run/rave/networkd.sock)
  owner=$(stat --format='%U' /run/rave/networkd.sock)
  group=$(stat --format='%G' /run/rave/networkd.sock)
  [[ $mode == 660 && $owner == root && $group == rave ]]
}

dhcp_socket_is_management_only() {
  local sockets
  sockets=$(ss -H -lunp 'sport = :67')
  [[ -n $sockets && $sockets == *wlan0* && $sockets != *eth0* ]]
}

ssh_dependencies_are_isolated() {
  local relationships
  relationships=$(systemctl show ssh.socket ssh.service \
    --property=Requires,Wants,After,Before,BindsTo,PartOf --value)
  ! grep -Eq \
    'rave-networkd|rave-management-dhcp|rave-webd|NetworkManager(-wait-online)?|sys-subsystem-net-devices-eth0\.device' \
    <<<"$relationships"
}

ssh_has_no_device_binding() {
  [[ -z $(systemctl show ssh.socket --property=BindToDevice --value) ]] &&
    ! systemctl show ssh.socket --property=BindsTo --value |
      grep -q 'sys-subsystem-net-devices-eth0.device'
}

management_has_no_gateway_or_dns() {
  ! nmcli --get-values IP4.GATEWAY,IP4.DNS device show wlan0 | grep -q '[^[:space:]]'
}

no_bridge_or_forwarding() {
  [[ $(sysctl -n net.ipv4.ip_forward) == 0 ]] &&
    [[ $(sysctl -n net.ipv6.conf.all.forwarding) == 0 ]] &&
    ! ip -o link show type bridge | grep -q .
}

host_private_keys_are_present_and_restricted() {
  compgen -G '/etc/ssh/ssh_host_*_key' >/dev/null &&
    ! find /etc/ssh -maxdepth 1 -type f -name 'ssh_host_*_key' ! -perm 0600 | grep -q .
}


timekeeping_is_truthful() {
  local synchronized marker=no
  [[ $(timedatectl show --property=Timezone --value) == Etc/UTC ]] || return 1
  [[ $(systemctl is-active systemd-timesyncd.service) == active ]] || return 1
  [[ -e /sys/class/rtc/rtc0 ]] || return 1
  [[ -e /run/systemd/timesync/synchronized ]] && marker=yes
  synchronized=$(timedatectl show --property=SystemClockSynchronized --value)
  [[ $synchronized == "$marker" ]]
}

check 'eth0 has only 10.77.0.1/24' interface_has_only_address eth0 10.77.0.1/24
check 'wlan0 has only 192.168.77.1/24' interface_has_only_address wlan0 192.168.77.1/24
check 'runtime route is connected-only with no IPv4/IPv6 default' route_contract_isolated
check 'NetworkManager leaves eth0 unmanaged' networkmanager_leaves_eth0_unmanaged
check 'RAVE-Setup is active on wlan0' rave_setup_is_active
check 'systemd-networkd is active/running' service_state_is systemd-networkd.service active running
check 'management network daemon is active/running' service_state_is rave-networkd.service active running
check 'DHCP is active/running' service_state_is rave-management-dhcp.service active running
check 'web management socket is bound to wlan0' web_socket_is_management_bound
check 'socket-activated web service is healthy' socket_activated_service_is_healthy
check 'management web root returns HTTP success' web_root_is_available
check 'SSH socket is active/listening' service_state_is ssh.socket active listening
check 'SSH listener is exactly 10.77.0.1:22' listener_is_exact 22 10.77.0.1:22
check 'one inherited web listener exists on port 8080' listener_port_is_present 8080
check 'network daemon socket is root:rave mode 0660' networkd_socket_is_restricted
check 'DHCP socket is bound to wlan0 and not eth0' dhcp_socket_is_management_only
check 'DHCP target configuration parses' dnsmasq --test \
  --conf-file=/etc/rave/network/dnsmasq.conf --no-hosts --no-resolv
check 'DHCP lease database exists and is writable' test -w /var/lib/misc/dnsmasq.leases
check 'management interface has no gateway or DNS' management_has_no_gateway_or_dns
check 'bridging and IP forwarding are absent' no_bridge_or_forwarding
check 'SSH has no management dependency' ssh_dependencies_are_isolated
check 'SSH has no eth0 device-unit lifetime binding' ssh_has_no_device_binding
check 'per-device SSH host private keys exist with mode 0600' host_private_keys_are_present_and_restricted
check 'UTC/time synchronization state is truthful' timekeeping_is_truthful

printf '\nSSH host-key fingerprints for qualification records:\n'
for public_key in /etc/ssh/ssh_host_*_key.pub; do
  [[ -f $public_key ]] && ssh-keygen -lf "$public_key"
done

printf '\nExplicit RAVE unit states:\n'
systemctl show rave-networkd.service rave-management-dhcp.service rave-webd.socket \
  rave-webd.service ssh.socket systemd-timesyncd.service \
  --property=Id,LoadState,ActiveState,SubState,Result,NRestarts --no-pager

if (( failures == 0 )); then
  printf '\nGate 2B target-local checks passed. External Ethernet, client DHCP, and exposure checks remain required.\n'
else
  printf '\nGate 2B target-local checks failed: %d\n' "$failures" >&2
fi

test "$failures" -eq 0
