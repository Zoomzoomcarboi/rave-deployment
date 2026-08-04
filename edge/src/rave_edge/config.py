from __future__ import annotations

from pathlib import Path
import tomllib
from pydantic import BaseModel, Field, model_validator


class CameraConfig(BaseModel):
    device: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0, le=120)
    pixel_format: str
    crop_x: int = Field(ge=0)
    crop_y: int = Field(ge=0)
    crop_width: int = Field(gt=0)
    crop_height: int = Field(gt=0)
    orientation: str = "normal"

    @model_validator(mode="after")
    def crop_fits_frame(self) -> "CameraConfig":
        if self.crop_x + self.crop_width > self.width:
            raise ValueError("camera crop exceeds frame width")
        if self.crop_y + self.crop_height > self.height:
            raise ValueError("camera crop exceeds frame height")
        return self


class InferenceConfig(BaseModel):
    backend: str
    model_bundle: str
    input_size: int = Field(gt=0)
    confidence_threshold: float = Field(ge=0, le=1)
    max_frame_age_ms: int = Field(gt=0)


class NetworkConfig(BaseModel):
    interface: str
    pi_address: str
    dhcp_start: str
    dhcp_end: str
    detection_port: int = Field(gt=0, le=65535)
    management_port: int = Field(gt=0, le=65535)
    heartbeat_interval_ms: int = Field(gt=0)
    stale_after_ms: int = Field(gt=0)


class SafetyConfig(BaseModel):
    require_paired_bridge: bool = True
    allow_vehicle_control: bool = False
    fail_closed_to_unavailable: bool = True

    @model_validator(mode="after")
    def reject_control(self) -> "SafetyConfig":
        if self.allow_vehicle_control:
            raise ValueError("RAVE edge must never be configured for vehicle control")
        return self


class RaveConfig(BaseModel):
    device: dict
    camera: CameraConfig
    inference: InferenceConfig
    tracking: dict
    network: NetworkConfig
    safety: SafetyConfig


def load_config(path: str | Path) -> RaveConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        return RaveConfig.model_validate(tomllib.load(handle))
