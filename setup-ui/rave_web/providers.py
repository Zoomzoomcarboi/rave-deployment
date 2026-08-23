"""Read-only providers for management state."""

import fcntl
import os
import socket
import struct
from pathlib import Path
from typing import Protocol

from .models import (
    Availability,
    ComponentStatus,
    NetworkMode,
    NetworkResponse,
    StatusResponse,
    SystemResponse,
)

NOT_INTEGRATED = ComponentStatus(
    availability=Availability.UNAVAILABLE,
    reason="not_integrated",
)
WEB_VERSION = "0.2.0"
MANAGEMENT_INTERFACE = "wlan0"
MANAGEMENT_ADDRESS = "192.168.77.1"
MAX_LOCAL_FILE_BYTES = 64 * 1024


class StatusProvider(Protocol):
    def status(self) -> StatusResponse: ...

    def network(self) -> NetworkResponse: ...

    def system(self) -> SystemResponse: ...


class GateOneProvider:
    """Truthful, immutable Gate-1 state without privileged side effects."""

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
        )


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


class PiManagementProvider(GateOneProvider):
    """Gate 2B appliance observations; no network or hardware actuation."""

    def __init__(
        self,
        *,
        os_release: Path = Path("/etc/os-release"),
        temperature: Path = Path("/sys/class/thermal/thermal_zone0/temp"),
    ) -> None:
        self._os_release = os_release
        self._temperature = temperature

    def network(self) -> NetworkResponse:
        address = _ipv4_address(MANAGEMENT_INTERFACE)
        active = address == MANAGEMENT_ADDRESS
        return NetworkResponse(
            api_version="v1",
            availability=Availability.READY if active else Availability.DEGRADED,
            mode=NetworkMode.PROVISIONING_AP if active else NetworkMode.ERROR,
            management_interface=MANAGEMENT_INTERFACE,
            local_discovery_name=None,
            runtime_network="10.77.0.0/24",
            actuation_available=False,
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
        )


def configured_provider() -> StatusProvider:
    """Select a provider explicitly; appliance service sets ``RAVE_PROVIDER=pi``."""
    provider = os.environ.get("RAVE_PROVIDER", "gate1")
    if provider == "gate1":
        return GateOneProvider()
    if provider == "pi":
        return PiManagementProvider()
    raise RuntimeError(f"unsupported RAVE_PROVIDER: {provider}")
