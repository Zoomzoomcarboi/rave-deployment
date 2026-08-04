from pathlib import Path
import pytest
from pydantic import ValidationError

from rave_edge.config import load_config, NetworkConfig, SafetyConfig


def test_example_configuration_loads() -> None:
    config = load_config(Path("config/rave.toml.example"))
    assert config.camera.crop_width == 1920
    assert config.camera.crop_height == 391
    assert config.inference.input_size == 960
    assert config.device.mode == "development_mock"
    assert config.safety.allow_vehicle_control is False


def test_vehicle_control_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SafetyConfig(
            require_paired_bridge=True,
            allow_vehicle_control=True,
            fail_closed_to_unavailable=True,
        )


def test_invalid_network_timing_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NetworkConfig(
            interface="eth0",
            pi_address="10.42.0.1/24",
            dhcp_start="10.42.0.10",
            dhcp_end="10.42.0.20",
            detection_port=42001,
            management_port=42002,
            heartbeat_interval_ms=750,
            stale_after_ms=750,
        )
