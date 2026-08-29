import pytest
from rave_web.models import NetworkMode
from rave_web.network_policy import NetworkEvent, transition


def test_boot_to_station_then_connected() -> None:
    state = transition(NetworkMode.UNCONFIGURED, NetworkEvent.BOOT)
    assert state == NetworkMode.STATION_CONNECTING
    assert transition(state, NetworkEvent.STATION_CONNECTED) == NetworkMode.STATION_CONNECTED


def test_failed_station_recovers_provisioning_ap() -> None:
    state = transition(NetworkMode.STATION_CONNECTING, NetworkEvent.STATION_TIMEOUT)
    assert state == NetworkMode.TRANSITION
    assert transition(state, NetworkEvent.AP_READY) == NetworkMode.PROVISIONING_AP
    state = transition(NetworkMode.PROVISIONING_AP, NetworkEvent.STATION_REQUESTED)
    state = transition(state, NetworkEvent.STATION_TIMEOUT)
    assert state == NetworkMode.TRANSITION
    assert transition(state, NetworkEvent.AP_READY) == NetworkMode.PROVISIONING_AP


def test_undefined_transition_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid network transition"):
        transition(NetworkMode.STATION_CONNECTED, NetworkEvent.AP_READY)
