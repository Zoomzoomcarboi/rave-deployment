"""Read-only providers for management state.

Gate 1 deliberately has no hardware, NetworkManager, transport, or updater provider.
"""

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
            web_version="0.1.0",
            update_status=NOT_INTEGRATED,
        )
