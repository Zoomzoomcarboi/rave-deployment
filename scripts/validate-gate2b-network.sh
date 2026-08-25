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
    'rave-wifi-init|rave-management-dhcp|rave-webd|NetworkManager(-wait-online)?|sys-subsystem-net-devices-eth0\.device' \
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

check 'eth0 has only 10.77.0.1/24' interface_has_only_address eth0 10.77.0.1/24
check 'wlan0 has only 192.168.77.1/24' interface_has_only_address wlan0 192.168.77.1/24
check 'runtime route is connected-only with no IPv4/IPv6 default' route_contract_isolated
check 'NetworkManager leaves eth0 unmanaged' networkmanager_leaves_eth0_unmanaged
check 'RAVE-Setup is active on wlan0' rave_setup_is_active
check 'systemd-networkd is active/running' service_state_is systemd-networkd.service active running
check 'Wi-Fi initialization completed' service_state_is rave-wifi-init.service active exited
check 'DHCP is active/running' service_state_is rave-management-dhcp.service active running
check 'web management is active/running' service_state_is rave-webd.service active running
check 'SSH socket is active/listening' service_state_is ssh.socket active listening
check 'SSH listener is exactly 10.77.0.1:22' listener_is_exact 22 10.77.0.1:22
check 'web listener is exactly 192.168.77.1:8080' listener_is_exact 8080 192.168.77.1:8080
check 'DHCP socket is bound to wlan0 and not eth0' dhcp_socket_is_management_only
check 'DHCP target configuration parses' dnsmasq --test \
  --conf-file=/etc/rave/network/dnsmasq.conf --no-hosts --no-resolv
check 'DHCP lease database exists and is writable' test -w /var/lib/misc/dnsmasq.leases
check 'management interface has no gateway or DNS' management_has_no_gateway_or_dns
check 'bridging and IP forwarding are absent' no_bridge_or_forwarding
check 'SSH has no management dependency' ssh_dependencies_are_isolated
check 'SSH has no eth0 device-unit lifetime binding' ssh_has_no_device_binding
check 'per-device SSH host private keys exist with mode 0600' host_private_keys_are_present_and_restricted

printf '\nSSH host-key fingerprints for qualification records:\n'
for public_key in /etc/ssh/ssh_host_*_key.pub; do
  [[ -f $public_key ]] && ssh-keygen -lf "$public_key"
done

printf '\nExplicit RAVE unit states:\n'
systemctl show rave-wifi-init.service rave-management-dhcp.service rave-webd.service ssh.socket \
  --property=Id,LoadState,ActiveState,SubState,Result --no-pager

if (( failures == 0 )); then
  printf '\nGate 2B target-local checks passed. External Ethernet, client DHCP, and exposure checks remain required.\n'
else
  printf '\nGate 2B target-local checks failed: %d\n' "$failures" >&2
fi

test "$failures" -eq 0
