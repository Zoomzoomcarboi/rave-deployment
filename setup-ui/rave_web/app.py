"""Unprivileged RAVE local management API and static shell."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from rave_network_ipc.client import NetworkdUnavailable

from .models import (
    NetworkActionResponse,
    NetworkConnectRequest,
    NetworkResponse,
    ProvisioningRequest,
    StatusResponse,
    SystemResponse,
    WifiScanResponse,
)
from .providers import WEB_VERSION, StatusProvider, configured_provider

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
APP_CSS = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
NAVIGATION_JS = (STATIC_DIR / "navigation.js").read_text(encoding="utf-8")


async def request_validation_failed(
    _request: Request, _error: RequestValidationError
) -> JSONResponse:
    """Reject malformed input without reflecting credential-bearing request values."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "request_validation_failed"},
    )


def create_app(provider: StatusProvider | None = None) -> FastAPI:
    state_provider = provider or configured_provider()
    app = FastAPI(
        title="RAVE Management API",
        version=WEB_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.add_exception_handler(RequestValidationError, request_validation_failed)

    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        return HTMLResponse(INDEX_HTML)

    @app.get("/static/app.css", include_in_schema=False)
    async def stylesheet() -> Response:
        return Response(APP_CSS, media_type="text/css")

    @app.get("/static/app.js", include_in_schema=False)
    async def javascript() -> Response:
        return Response(APP_JS, media_type="text/javascript")

    @app.get("/static/navigation.js", include_in_schema=False)
    async def navigation_javascript() -> Response:
        return Response(NAVIGATION_JS, media_type="text/javascript")

    @app.get("/api/v1/status", response_model=StatusResponse)
    def get_status() -> StatusResponse:
        return state_provider.status()

    @app.get("/api/v1/network", response_model=NetworkResponse)
    def get_network() -> NetworkResponse:
        return state_provider.network()

    @app.get("/api/v1/system", response_model=SystemResponse)
    def get_system() -> SystemResponse:
        return state_provider.system()

    @app.get("/api/v1/network/wifi", response_model=WifiScanResponse)
    def get_wifi_networks() -> WifiScanResponse:
        try:
            return state_provider.wifi_networks()
        except NetworkdUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @app.post(
        "/api/v1/network/connect",
        response_model=NetworkActionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def connect_wifi(request: NetworkConnectRequest) -> NetworkActionResponse:
        try:
            return state_provider.connect_wifi(request)
        except NetworkdUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @app.post(
        "/api/v1/network/provisioning",
        response_model=NetworkActionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enable_provisioning(request: ProvisioningRequest) -> NetworkActionResponse:
        try:
            return state_provider.enable_provisioning(request)
        except NetworkdUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    return app


app = create_app()
