from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "image/overlays/etc/NetworkManager/system-connections/rave-setup.nmconnection"
RUNTIME_NETWORK = ROOT / "image/overlays/etc/systemd/network/10-rave-ethernet.network"


def test_network_daemon_owns_bounded_management_wifi_initialization() -> None:
    unit = (ROOT / "systemd/rave-networkd.service").read_text(encoding="utf-8")
    controller = (ROOT / "setup-ui/rave_networkd/controller.py").read_text(encoding="utf-8")
    backend = (ROOT / "setup-ui/rave_networkd/backend.py").read_text(encoding="utf-8")
    assert "Requires=NetworkManager.service" in unit
    assert "After=NetworkManager.service" in unit
    assert "TimeoutStopSec=5s" in unit
    assert "LimitCORE=0" in unit
    assert "Queue(maxsize=1)" in controller
    assert 'INTERFACE = "wlan0"' in backend
    assert 'PROVISIONING_PROFILE = "RAVE-Setup"' in backend
    assert 'SAVED_PROFILE = "RAVE-Management"' in backend
    assert 'PREVIOUS_PROFILE = "RAVE-Management-Previous"' in backend
    assert "COMMAND_TIMEOUT_SECONDS = 35.0" in backend
    assert '"connection.autoconnect",\n            "yes"' not in backend
    assert "connection.autoconnect-retries" not in backend
    assert "while true" not in backend.lower()
    assert "rfkill" not in backend


def test_management_consumers_do_not_gate_global_network_online() -> None:
    for name in (
        "rave-networkd.service",
        "rave-management-dhcp.service",
        "rave-webd.socket",
        "rave-webd.service",
    ):
        unit = (ROOT / "systemd" / name).read_text(encoding="utf-8")
        assert "network-online.target" not in unit
        assert "NetworkManager-wait-online.service" not in unit


def test_web_socket_has_no_networkmanager_sockets_target_cycle() -> None:
    socket = (ROOT / "systemd/rave-webd.socket").read_text(encoding="utf-8")
    assert "Requires=NetworkManager.service" not in socket
    assert "After=NetworkManager.service" not in socket
    assert "BindToDevice=wlan0" in socket
    assert "ListenStream=8080" in socket
    assert "eth0" not in socket


def test_provisioning_profile_is_state_owned_and_runtime_is_unchanged() -> None:
    profile = PROFILE.read_text(encoding="utf-8")
    assert "id=RAVE-Setup" in profile
    assert "interface-name=wlan0" in profile
    assert "autoconnect=false" in profile
    assert "mode=ap" in profile
    assert "ssid=RAVE-Setup" in profile
    assert "address1=192.168.77.1/24" in profile
    assert "never-default=true" in profile
    assert "method=shared" not in profile
    runtime = RUNTIME_NETWORK.read_text(encoding="utf-8")
    assert "Name=eth0" in runtime
    assert "Address=10.77.0.1/24" in runtime
    assert "DHCP=no" in runtime
    assert "Gateway=" not in runtime
    assert "IPMasquerade=no" in runtime
    combined = f"{profile}\n{runtime}".lower()
    assert all(term not in combined for term in ("bridge", "snat", "dnat"))
    assert all(term not in runtime for term in ("IPMasquerade=yes", "Bridge=", "DHCPServer=yes"))


def test_image_hook_installs_and_enables_state_owner_only() -> None:
    hook = (ROOT / "image/bdebstrap/customize80-rave-network").read_text(encoding="utf-8")
    for installed in (
        "/opt/rave/management/rave_network_ipc",
        "/opt/rave/management/rave_networkd",
        "/usr/lib/systemd/system/rave-networkd.service",
        "multi-user.target.wants/rave-networkd.service",
    ):
        assert installed in hook
    assert "multi-user.target.wants/rave-management-dhcp.service" not in hook
    assert "rave-wifi-init" not in hook


def test_artifact_verifier_keeps_physical_transition_outside_static_claim() -> None:
    verifier = (ROOT / "scripts/verify_rave_image.py").read_text(encoding="utf-8")
    assert '"typed_network_privilege_boundary": "pass"' in verifier
    assert '"bounded_station_to_ap_recovery": "pass"' in verifier
    assert (
        '"physical_wifi_ap_operation": "requires Raspberry Pi hardware validation"'
        in verifier
    )
