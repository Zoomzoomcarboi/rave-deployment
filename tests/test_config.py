from pathlib import Path
import pytest
from pydantic import ValidationError

from rave_edge.config import load_config, SafetyConfig


def test_example_configuration_loads() -> None:
    config = load_config(Path("config/rave.toml.example"))
    assert config.camera.crop_width == 1920
    assert config.camera.crop_height == 391
    assert config.inference.input_size == 960
    assert config.safety.allow_vehicle_control is False


def test_vehicle_control_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SafetyConfig(
            require_paired_bridge=True,
            allow_vehicle_control=True,
            fail_closed_to_unavailable=True,
        )
