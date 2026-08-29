import asyncio

import pytest
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from rave_web.app import create_app
from rave_web.models import NetworkActionResponse, NetworkConnectRequest, NetworkMode


class ConnectOnlyProvider:
    def __init__(self) -> None:
        self.password: str | None = None

    def connect_wifi(self, request: NetworkConnectRequest) -> NetworkActionResponse:
        self.password = request.password.get_secret_value() if request.password else None
        return NetworkActionResponse(
            api_version="v1",
            accepted=True,
            mode=NetworkMode.TRANSITION,
            reason="station_connection_requested",
        )


@pytest.mark.parametrize(
    "payload",
    (
        {"ssid": "RAVE", "password": "correct-horse", "interface": "eth0"},
        {"ssid": "RAVE", "password": "correct-horse", "nmcli_args": ["general"]},
        {"ssid": "RAVE", "password": "correct-horse", "properties": {"ipv4.method": "shared"}},
    ),
)
def test_connect_request_rejects_unreviewed_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NetworkConnectRequest.model_validate(payload)


@pytest.mark.parametrize(
    "ssid",
    (
        "",
        "x" * 33,
        "\U0001f680" * 9,
        "line\nbreak",
        "nul\x00byte",
    ),
)
def test_connect_request_rejects_invalid_or_oversize_ssid(ssid: str) -> None:
    with pytest.raises(ValidationError):
        NetworkConnectRequest(ssid=ssid, password="correct-horse")


def test_connect_request_accepts_32_byte_unicode_ssid_boundary() -> None:
    request = NetworkConnectRequest(ssid="\U0001f680" * 8, password="correct-horse")
    assert request.ssid == "\U0001f680" * 8


@pytest.mark.parametrize("password", ("short", "x" * 64, "line\nbreak"))
def test_connect_request_rejects_invalid_password(password: str) -> None:
    with pytest.raises(ValidationError):
        NetworkConnectRequest(ssid="RAVE", password=password)


def test_connect_request_keeps_password_secret_and_out_of_serialization() -> None:
    request = NetworkConnectRequest(ssid="RAVE", password="correct-horse")
    assert request.password is not None
    assert request.password.get_secret_value() == "correct-horse"
    assert "correct-horse" not in request.model_dump_json()


def test_connect_api_accepts_typed_request_without_returning_credential() -> None:
    provider = ConnectOnlyProvider()
    app = create_app(provider)
    route = next(route for route in app.routes if route.path == "/api/v1/network/connect")
    response = route.endpoint(
        NetworkConnectRequest(ssid="RAVE", password="correct-horse")
    )
    body = response.model_dump(mode="json")
    assert route.status_code == 202
    assert body == {
        "api_version": "v1",
        "accepted": True,
        "mode": "transition",
        "reason": "station_connection_requested",
    }
    assert provider.password == "correct-horse"
    assert "correct-horse" not in response.model_dump_json()


def test_connect_api_rejects_unexpected_fields_before_provider() -> None:
    provider = ConnectOnlyProvider()
    with pytest.raises(ValidationError):
        NetworkConnectRequest.model_validate(
            {
                "ssid": "RAVE",
                "password": "correct-horse",
                "interface": "eth0",
            }
        )
    assert provider.password is None


def test_request_validation_response_does_not_reflect_invalid_password() -> None:
    app = create_app(ConnectOnlyProvider())
    handler = app.exception_handlers[RequestValidationError]
    response = asyncio.run(handler(None, None))
    assert response.status_code == 422
    assert response.body == b'{"detail":"request_validation_failed"}'
    assert b"password" not in response.body


def test_openapi_remains_versioned_and_default_schema_path_is_absent() -> None:
    app = create_app(ConnectOnlyProvider())
    paths = {route.path for route in app.routes}
    assert app.openapi_url == "/api/v1/openapi.json"
    assert "/api/v1/openapi.json" in paths
    assert "/openapi.json" not in paths
