import asyncio
from typing import Any

from rave_web.app import create_app
from rave_web.models import Availability, NetworkMode


def endpoint(path: str) -> Any:
    return next(route.endpoint for route in create_app().routes if route.path == path)


def model_body(path: str) -> dict[str, Any]:
    return endpoint(path)().model_dump(mode="json")


async def get_assets() -> tuple[Any, Any, Any]:
    return tuple(
        await asyncio.gather(
            endpoint("/")(),
            endpoint("/static/app.css")(),
            endpoint("/static/app.js")(),
        )
    )


def test_status_is_truthfully_unavailable() -> None:
    body = model_body("/api/v1/status")
    assert body["api_version"] == "v1"
    assert body["valid_for_ms"] == 1000
    assert body["overall"] == Availability.UNAVAILABLE
    for component in ("camera", "perception", "hailo", "comma_link"):
        assert body[component] == {
            "availability": Availability.UNAVAILABLE,
            "reason": "not_integrated",
        }


def test_network_has_no_actuation_or_credentials() -> None:
    body = model_body("/api/v1/network")
    assert body["mode"] == NetworkMode.UNCONFIGURED
    assert body["actuation_available"] is False
    assert body["runtime_network"] == "10.77.0.0/24"
    assert not ({"ssid", "password", "psk"} & body.keys())


def test_system_does_not_fabricate_measurements() -> None:
    body = model_body("/api/v1/system")
    assert body["availability"] == Availability.UNAVAILABLE
    assert body["os_version"] is None
    assert body["temperature_c"] is None
    assert body["update_status"]["reason"] == "not_integrated"


def test_static_galaxy_shell_is_served_locally() -> None:
    page, css, script = asyncio.run(get_assets())
    assert page.status_code == css.status_code == script.status_code == 200
    page_text = page.body.decode()
    css_text = css.body.decode()
    script_text = script.body.decode()
    assert "Dashboard" in page_text and "Diagnostics" in page_text
    assert "--main-fg: #8b6cc5" in css_text
    for path in ("/api/v1/status", "/api/v1/network", "/api/v1/system"):
        assert f'"{path}"' in script_text
    assert "new AbortController()" in script_text
    assert 'cache: "no-store"' in script_text
    assert "setInterval" not in script_text
    assert "Promise.allSettled(requests)" in script_text
    assert "controller.abort();" in script_text
    assert "Promise.all([" not in script_text
    assert script_text.index("Promise.allSettled(requests)") < script_text.index("scheduleRefresh(nextRefreshMs)")
    for selector in ("#component-cards", "#network-mode", "#management-state", "#os-version", "#temperature", "#update-state"):
        assert selector in script_text


def test_static_shell_uses_authoritative_galaxy_metrics() -> None:
    css = asyncio.run(endpoint("/static/app.css")()).body.decode()
    for declaration in (
        "--sidebar-width: 250px",
        "--dashboard-card: #0e1020",
        "--dashboard-card-2: #111525",
        "max-width: 1280px",
        "padding: 2rem 2rem 3rem 0.5rem",
        "transform: var(--hover-scale-sm)",
    ):
        assert declaration in css
