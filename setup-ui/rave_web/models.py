"""Versioned, bounded management API models."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Availability(StrEnum):
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


class NetworkMode(StrEnum):
    UNCONFIGURED = "unconfigured"
    STATION_CONNECTING = "station_connecting"
    STATION_CONNECTED = "station_connected"
    PROVISIONING_AP = "provisioning_ap"
    TRANSITION = "transition"
    ERROR = "error"


class ComponentStatus(StrictModel):
    availability: Availability
    reason: str = Field(min_length=1, max_length=64)


class StatusResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    valid_for_ms: int = Field(ge=100, le=5000)
    overall: Availability
    camera: ComponentStatus
    perception: ComponentStatus
    hailo: ComponentStatus
    comma_link: ComponentStatus


class NetworkResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    availability: Availability
    mode: NetworkMode
    management_interface: str | None = Field(default=None, max_length=32)
    local_discovery_name: str | None = Field(default=None, max_length=253)
    runtime_network: str = Field(pattern=r"^10\.77\.0\.0/24$")
    actuation_available: bool = False


class SystemResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    availability: Availability
    os_version: str | None = Field(default=None, max_length=64)
    web_version: str = Field(min_length=1, max_length=32)
    update_status: ComponentStatus
    temperature_c: float | None = Field(default=None, ge=-40, le=125)
