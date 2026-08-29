"""Versioned, bounded management API models."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from rave_network_ipc.protocol import (
    NetworkMode,
    WifiSecurity,
    validate_password,
    validate_ssid,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Availability(StrEnum):
    UNAVAILABLE = "unavailable"
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
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
    provisioning_ap_active: bool = False
    station_ssid: str | None = Field(default=None, max_length=32)
    last_error: str | None = Field(default=None, max_length=64)


class WifiNetwork(StrictModel):
    ssid: str = Field(min_length=1, max_length=32)
    signal_percent: int = Field(ge=0, le=100)
    security: WifiSecurity
    connected: bool = False

    @field_validator("ssid")
    @classmethod
    def validate_network_ssid(cls, value: str) -> str:
        return validate_ssid(value)


class WifiScanResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    networks: list[WifiNetwork] = Field(max_length=64)


class NetworkConnectRequest(StrictModel):
    ssid: str
    password: SecretStr | None = None

    @field_validator("ssid")
    @classmethod
    def validate_requested_ssid(cls, value: str) -> str:
        return validate_ssid(value)

    @field_validator("password")
    @classmethod
    def validate_requested_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            validate_password(value.get_secret_value())
        return value


class ProvisioningRequest(StrictModel):
    pass


class NetworkActionResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    accepted: bool
    mode: NetworkMode
    reason: str = Field(min_length=1, max_length=64)


class TimeStatus(StrictModel):
    current_utc: datetime
    synchronized: bool
    rtc_available: bool


class SystemResponse(StrictModel):
    api_version: str = Field(pattern=r"^v1$")
    availability: Availability
    os_version: str | None = Field(default=None, max_length=64)
    web_version: str = Field(min_length=1, max_length=32)
    update_status: ComponentStatus
    temperature_c: float | None = Field(default=None, ge=-40, le=125)
    time: TimeStatus
