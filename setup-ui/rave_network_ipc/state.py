"""Canonical management-network state transition policy."""

from enum import StrEnum

from .protocol import NetworkMode


class NetworkEvent(StrEnum):
    BOOT = "boot"
    NO_SAVED_NETWORK = "no_saved_network"
    STATION_REQUESTED = "station_requested"
    STATION_CONNECTED = "station_connected"
    STATION_TIMEOUT = "station_timeout"
    PROVISIONING_REQUESTED = "provisioning_requested"
    AP_READY = "ap_ready"
    AP_FAILED = "ap_failed"


_TRANSITIONS: dict[tuple[NetworkMode, NetworkEvent], NetworkMode] = {
    (NetworkMode.UNCONFIGURED, NetworkEvent.BOOT): NetworkMode.STATION_CONNECTING,
    (NetworkMode.STATION_CONNECTING, NetworkEvent.NO_SAVED_NETWORK): NetworkMode.TRANSITION,
    (NetworkMode.STATION_CONNECTING, NetworkEvent.STATION_CONNECTED): NetworkMode.STATION_CONNECTED,
    (NetworkMode.STATION_CONNECTING, NetworkEvent.STATION_TIMEOUT): NetworkMode.TRANSITION,
    (NetworkMode.STATION_CONNECTING, NetworkEvent.PROVISIONING_REQUESTED): NetworkMode.TRANSITION,
    (NetworkMode.STATION_CONNECTED, NetworkEvent.STATION_REQUESTED): NetworkMode.TRANSITION,
    (NetworkMode.STATION_CONNECTED, NetworkEvent.PROVISIONING_REQUESTED): NetworkMode.TRANSITION,
    (NetworkMode.STATION_CONNECTED, NetworkEvent.STATION_TIMEOUT): NetworkMode.TRANSITION,
    (NetworkMode.PROVISIONING_AP, NetworkEvent.STATION_REQUESTED): NetworkMode.TRANSITION,
    (NetworkMode.PROVISIONING_AP, NetworkEvent.PROVISIONING_REQUESTED): NetworkMode.TRANSITION,
    (NetworkMode.TRANSITION, NetworkEvent.STATION_CONNECTED): NetworkMode.STATION_CONNECTED,
    (NetworkMode.TRANSITION, NetworkEvent.STATION_TIMEOUT): NetworkMode.TRANSITION,
    (NetworkMode.TRANSITION, NetworkEvent.AP_READY): NetworkMode.PROVISIONING_AP,
    (NetworkMode.TRANSITION, NetworkEvent.AP_FAILED): NetworkMode.ERROR,
    (NetworkMode.ERROR, NetworkEvent.BOOT): NetworkMode.STATION_CONNECTING,
    (NetworkMode.ERROR, NetworkEvent.PROVISIONING_REQUESTED): NetworkMode.TRANSITION,
}


def transition(current: NetworkMode, event: NetworkEvent) -> NetworkMode:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as error:
        raise ValueError(f"invalid network transition: {current} + {event}") from error
