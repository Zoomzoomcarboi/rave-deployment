from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/rave-wifi-init.sh"
UNIT = ROOT / "systemd/rave-wifi-init.service"
WAIT_DROPIN = ROOT / "systemd/NetworkManager-wait-online.service.d/10-rave-wifi-init.conf"
PROFILE = ROOT / "image/overlays/etc/NetworkManager/system-connections/rave-setup.nmconnection"
RUNTIME_NETWORK = ROOT / "image/overlays/etc/systemd/network/10-rave-ethernet.network"


def test_wifi_initialization_is_networkmanager_owned_and_bounded() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    assert "NMCLI=/usr/bin/nmcli" in helper
    assert '"$NMCLI" --wait 10 radio wifi on' in helper
    assert '"$NMCLI" --wait 2 -t -f WIFI general' in helper
    assert '[ "$radio_state" = enabled ]' in helper
    assert 'while [ "$attempt" -lt 10 ]' in helper
    assert '"$NMCLI" --wait 20 connection up id "$CONNECTION" ifname "$INTERFACE"' in helper
    assert "while true" not in helper
    assert "rfkill" not in helper
    unit = UNIT.read_text(encoding="utf-8")
    assert "TimeoutStartSec=60s" in unit


def test_wifi_initialization_targets_existing_profile_interface_and_address() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    assert "CONNECTION=RAVE-Setup" in helper
    assert "INTERFACE=wlan0" in helper
    assert "ADDRESS=192.168.77.1/24" in helper
    assert 'GENERAL.CONNECTION device show "$INTERFACE"' in helper
    assert 'if [ "$active_connection" = "$CONNECTION" ]' in helper
    assert '"$IP" -4 -o address show dev "$INTERFACE"' in helper


def test_wifi_initialization_orders_networkmanager_before_wait_online() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    assert "Requires=NetworkManager.service" in unit
    assert "After=NetworkManager.service" in unit
    assert "Before=NetworkManager-wait-online.service" in unit
    dropin = WAIT_DROPIN.read_text(encoding="utf-8")
    assert "Requires=rave-wifi-init.service" in dropin
    assert "After=rave-wifi-init.service" in dropin


def test_management_consumers_require_successful_wifi_initialization() -> None:
    dhcp = (ROOT / "systemd/rave-management-dhcp.service").read_text(encoding="utf-8")
    web = (ROOT / "systemd/rave-webd.service").read_text(encoding="utf-8")
    for consumer in (dhcp, web):
        assert "Requires=rave-wifi-init.service" in consumer
        assert "After=network-online.target NetworkManager-wait-online.service rave-wifi-init.service" in consumer
    assert "Before=rave-webd.service" in dhcp


def test_network_semantics_remain_exactly_gate2b() -> None:
    profile = PROFILE.read_text(encoding="utf-8")
    assert profile == """[connection]
id=RAVE-Setup
uuid=0fc02a7e-795a-4e05-8952-9ea47f31f695
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100
wait-device-timeout=15000

[wifi]
mode=ap
ssid=RAVE-Setup
band=bg

[ipv4]
method=manual
address1=192.168.77.1/24
never-default=true
may-fail=false
gateway=
dns-search=

[ipv6]
method=disabled
"""
    runtime = RUNTIME_NETWORK.read_text(encoding="utf-8")
    assert "Name=eth0" in runtime
    assert "Address=10.77.0.1/24" in runtime
    assert "DHCP=no" in runtime
    assert "Gateway=" not in runtime
    assert "IPMasquerade=no" in runtime
    combined = f"{profile}\n{HELPER.read_text(encoding='utf-8')}".lower()
    assert all(term not in combined for term in ("bridge", "masquerade", "snat", "dnat"))
    assert all(term not in runtime for term in ("IPMasquerade=yes", "Bridge=", "DHCPServer=yes"))


def test_image_hook_installs_wifi_initialization_contract() -> None:
    hook = (ROOT / "image/bdebstrap/customize80-rave-network").read_text(encoding="utf-8")
    for installed in (
        "/usr/libexec/rave/rave-wifi-init",
        "/usr/lib/systemd/system/rave-wifi-init.service",
        "/etc/systemd/system/NetworkManager-wait-online.service.d/10-rave-wifi-init.conf",
    ):
        assert installed in hook


def test_artifact_verifier_keeps_physical_wifi_outside_static_pass_claim() -> None:
    verifier = (ROOT / "scripts/verify_rave_image.py").read_text(encoding="utf-8")
    assert '"wifi_initialization_static_contract": "pass"' in verifier
    assert (
        '"physical_wifi_ap_operation": "requires Raspberry Pi hardware validation"'
        in verifier
    )
