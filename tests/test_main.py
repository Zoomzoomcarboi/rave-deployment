import pytest

from rave_edge.config import load_config
from rave_edge.main import authorize_development_mock


def test_startup_refuses_mock_without_explicit_acknowledgement() -> None:
    config = load_config("config/rave.toml.example")
    with pytest.raises(RuntimeError, match="--development-mock"):
        authorize_development_mock(config, acknowledged=False)


def test_development_mock_startup_is_explicitly_permitted() -> None:
    config = load_config("config/rave.toml.example")
    authorize_development_mock(config, acknowledged=True)
