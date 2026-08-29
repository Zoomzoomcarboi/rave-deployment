"""Unprivileged providers for appliance observations and typed network IPC."""

import fcntl
import os
import socket
import struct
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from rave_network_ipc.client import NetworkdClient, NetworkdUnavailable

from .models import (
    Availability,
    ComponentStatus,
    NetworkActionResponse,
    NetworkConnectRequest,
    NetworkMode,
    NetworkResponse,
    ProvisioningRequest,
    StatusResponse,
    SystemResponse,
    TimeStatus,
    WifiScanResponse,
)

NOT_INTEGRATED = ComponentStatus(
    availability=Availability.UNAVAILABLE,
    reason="not_integrated",
)
WEB_VERSION = "0.3.0"
MANAGEMENT_INTERFACE = "wlan0"
MANAGEMENT_ADDRESS = "192.168.77.1"
MAX_LOCAL_FILE_BYTES = 64 * 1024


class StatusProvider(Protocol):
    def status(self) -> StatusResponse: ...

    def network(self) -> NetworkResponse: ...

    def system(self) -> SystemResponse: ...

    def wifi_networks(self) -> WifiScanResponse: ...

    def connect_wifi(self, request: NetworkConnectRequest) -> NetworkActionResponse: ...

    def enable_provisioning(
        self, request: ProvisioningRequest
    ) -> NetworkActionResponse: ...


class UnavailableProvider:
    """Truthful, immutable unavailable state without privileged side effects."""

    def status(self) -> StatusResponse:
        return StatusResponse(
            api_version="v1",
            valid_for_ms=1000,
            overall=Availability.UNAVAILABLE,
            camera=NOT_INTEGRATED,
            perception=NOT_INTEGRATED,
            hailo=NOT_INTEGRATED,
            comma_link=NOT_INTEGRATED,
        )

    def network(self) -> NetworkResponse:
        return NetworkResponse(
            api_version="v1",
            availability=Availability.UNAVAILABLE,
            mode=NetworkMode.UNCONFIGURED,
            runtime_network="10.77.0.0/24",
            actuation_available=False,
        )

    def system(self) -> SystemResponse:
        return SystemResponse(
            api_version="v1",
            availability=Availability.UNAVAILABLE,
            web_version=WEB_VERSION,
            update_status=NOT_INTEGRATED,
            time=TimeStatus(
                current_utc=datetime.now(UTC),
                synchronized=False,
                rtc_available=False,
            ),
        )

    def wifi_networks(self) -> WifiScanResponse:
        raise NetworkdUnavailable("network_actuation_unavailable")

    def connect_wifi(self, request: NetworkConnectRequest) -> NetworkActionResponse:
        raise NetworkdUnavailable("network_actuation_unavailable")

    def enable_provisioning(
        self, request: ProvisioningRequest
    ) -> NetworkActionResponse:
        raise NetworkdUnavailable("network_actuation_unavailable")


def _read_bounded(path: Path, limit: int = MAX_LOCAL_FILE_BYTES) -> str | None:
    """Read a small trusted local status file without following an unbounded stream."""
    try:
        with path.open("rb") as source:
            data = source.read(limit + 1)
    except OSError:
        return None
    if len(data) > limit:
        return None
    return data.decode("utf-8", errors="replace").strip()


def _os_identification(path: Path) -> str | None:
    content = _read_bounded(path)
    if not content:
        return None
    values: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"PRETTY_NAME", "NAME", "VERSION_ID"}:
            values[key] = value.strip().strip('"')[:64]
    pretty = values.get("PRETTY_NAME")
    if pretty:
        return pretty
    name = values.get("NAME")
    version = values.get("VERSION_ID")
    return " ".join(part for part in (name, version) if part) or None


def _temperature_c(path: Path) -> float | None:
    value = _read_bounded(path, 32)
    if value is None:
        return None
    try:
        temperature = int(value) / 1000
    except ValueError:
        return None
    return temperature if -40 <= temperature <= 125 else None


def _ipv4_address(interface: str) -> str | None:
    """Return one interface IPv4 address with a bounded local ioctl."""
    ifname = interface.encode("ascii")
    if len(ifname) > 15:
        return None
    request = struct.pack("256s", ifname)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as descriptor:
            response = fcntl.ioctl(descriptor.fileno(), 0x8915, request)
    except OSError:
        return None
    return socket.inet_ntoa(response[20:24])


class PiManagementProvider(UnavailableProvider):
    """Appliance observations plus the narrow local network-daemon client."""

    def __init__(
        self,
        *,
        os_release: Path = Path("/etc/os-release"),
        temperature: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
        synchronized_marker: Path = Path("/run/systemd/timesync/synchronized"),
        rtc_path: Path = Path("/sys/class/rtc/rtc0"),
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        network_client: NetworkdClient | None = None,
    ) -> None:
        self._os_release = os_release
        self._temperature = temperature
        self._synchronized_marker = synchronized_marker
        self._rtc_path = rtc_path
        self._utc_now = utc_now
        self._network_client = network_client or NetworkdClient()

    def network(self) -> NetworkResponse:
        try:
            status = self._network_client.status()
        except NetworkdUnavailable:
            return self._network_fallback()
        mode = NetworkMode(status["mode"])
        return NetworkResponse(
            api_version="v1",
            availability=_network_availability(mode),
            mode=mode,
            management_interface=MANAGEMENT_INTERFACE,
            # Local discovery is not installed by the current image. Do not
            # advertise a hostname until an interface-scoped implementation is
            # reviewed and validated.
            local_discovery_name=None,
            runtime_network="10.77.0.0/24",
            actuation_available=True,
            provisioning_ap_active=bool(status["provisioning_ap_active"]),
            station_ssid=status.get("station_ssid"),
            last_error=status.get("last_error"),
        )

    def wifi_networks(self) -> WifiScanResponse:
        response = self._network_client.scan()
        return WifiScanResponse(api_version="v1", networks=response["networks"])

    def connect_wifi(self, request: NetworkConnectRequest) -> NetworkActionResponse:
        password = request.password.get_secret_value() if request.password is not None else None
        response = self._network_client.connect(request.ssid, password)
        return NetworkActionResponse(
            api_version="v1",
            accepted=response["accepted"],
            mode=response["mode"],
            reason=response["reason"],
        )

    def enable_provisioning(
        self, request: ProvisioningRequest
    ) -> NetworkActionResponse:
        del request
        response = self._network_client.provisioning()
        return NetworkActionResponse(
            api_version="v1",
            accepted=response["accepted"],
            mode=response["mode"],
            reason=response["reason"],
        )

    def system(self) -> SystemResponse:
        os_version = _os_identification(self._os_release)
        return SystemResponse(
            api_version="v1",
            availability=Availability.READY if os_version else Availability.DEGRADED,
            os_version=os_version,
            web_version=WEB_VERSION,
            update_status=NOT_INTEGRATED,
            temperature_c=_temperature_c(self._temperature),
            time=TimeStatus(
                current_utc=self._utc_now(),
                synchronized=self._synchronized_marker.is_file(),
                rtc_available=self._rtc_path.exists(),
            ),
        )

    @staticmethod
    def _network_fallback() -> NetworkResponse:
        address = _ipv4_address(MANAGEMENT_INTERFACE)
        active = address == MANAGEMENT_ADDRESS
        return NetworkResponse(
            api_version="v1",
            availability=Availability.DEGRADED,
            mode=NetworkMode.PROVISIONING_AP if active else NetworkMode.ERROR,
            management_interface=MANAGEMENT_INTERFACE,
            runtime_network="10.77.0.0/24",
            actuation_available=False,
            provisioning_ap_active=active,
            last_error="network_daemon_unavailable",
        )


def _network_availability(mode: NetworkMode) -> Availability:
    if mode in {NetworkMode.PROVISIONING_AP, NetworkMode.STATION_CONNECTED}:
        return Availability.READY
    if mode in {NetworkMode.STATION_CONNECTING, NetworkMode.TRANSITION}:
        return Availability.STARTING
    if mode == NetworkMode.ERROR:
        return Availability.ERROR
    return Availability.DEGRADED


def configured_provider() -> StatusProvider:
    """Select a provider explicitly; appliance service sets ``RAVE_PROVIDER=pi``."""
    provider = os.environ.get("RAVE_PROVIDER", "gate1")
    if provider == "gate1":
        return UnavailableProvider()
    if provider == "pi":
        return PiManagementProvider()
    raise RuntimeError(f"unsupported RAVE_PROVIDER: {provider}")
