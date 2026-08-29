from pathlib import Path

from rave_web.models import Availability, NetworkMode
from rave_web.providers import PiManagementProvider, configured_provider


class ConnectedNetworkClient:
    def status(self):
        return {
            "mode": "provisioning_ap",
            "provisioning_ap_active": True,
            "station_ssid": None,
            "last_error": None,
        }


def test_pi_provider_real_system_happy_path(tmp_path: Path, monkeypatch) -> None:
    os_release = tmp_path / "os-release"
    temperature = tmp_path / "temp"
    os_release.write_text('PRETTY_NAME="RAVE OS Test 2B"\n', encoding="utf-8")
    temperature.write_text("48750\n", encoding="utf-8")
    monkeypatch.setattr("rave_web.providers._ipv4_address", lambda interface: "192.168.77.1")
    provider = PiManagementProvider(
        os_release=os_release,
        temperature=temperature,
        network_client=ConnectedNetworkClient(),
    )

    system = provider.system()
    network = provider.network()
    assert system.availability == Availability.READY
    assert system.os_version == "RAVE OS Test 2B"
    assert system.temperature_c == 48.75
    assert system.update_status.reason == "not_integrated"
    assert network.availability == Availability.READY
    assert network.mode == NetworkMode.PROVISIONING_AP
    assert network.management_interface == "wlan0"
    assert network.runtime_network == "10.77.0.0/24"
    assert network.actuation_available is True


def test_pi_provider_missing_or_invalid_temperature_is_truthful(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text("NAME=RAVE OS\nVERSION_ID=2B\n", encoding="utf-8")
    provider = PiManagementProvider(os_release=os_release, temperature=tmp_path / "missing")
    assert provider.system().temperature_c is None
    invalid = tmp_path / "invalid-temp"
    invalid.write_text("not-a-number\n", encoding="utf-8")
    assert PiManagementProvider(os_release=os_release, temperature=invalid).system().temperature_c is None


def test_pi_provider_degrades_when_management_address_is_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("rave_web.providers._ipv4_address", lambda interface: None)
    response = PiManagementProvider(os_release=tmp_path / "missing").network()
    assert response.availability == Availability.DEGRADED
    assert response.mode == NetworkMode.ERROR
    assert response.management_interface == "wlan0"


def test_pi_provider_selection_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("RAVE_PROVIDER", "pi")
    assert isinstance(configured_provider(), PiManagementProvider)


def test_unfinished_components_remain_not_integrated() -> None:
    status = PiManagementProvider().status()
    for component in (status.camera, status.perception, status.hailo, status.comma_link):
        assert component.availability == Availability.UNAVAILABLE
        assert component.reason == "not_integrated"
