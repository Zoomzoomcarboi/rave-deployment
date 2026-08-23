"""Unprivileged RAVE local management API and static shell."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from .models import NetworkResponse, StatusResponse, SystemResponse
from .providers import GateOneProvider, StatusProvider

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
APP_CSS = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def create_app(provider: StatusProvider | None = None) -> FastAPI:
    state_provider = provider or GateOneProvider()
    app = FastAPI(
        title="RAVE Management API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        return HTMLResponse(INDEX_HTML)

    @app.get("/static/app.css", include_in_schema=False)
    async def stylesheet() -> Response:
        return Response(APP_CSS, media_type="text/css")

    @app.get("/static/app.js", include_in_schema=False)
    async def javascript() -> Response:
        return Response(APP_JS, media_type="text/javascript")

    @app.get("/api/v1/status", response_model=StatusResponse)
    def get_status() -> StatusResponse:
        return state_provider.status()

    @app.get("/api/v1/network", response_model=NetworkResponse)
    def get_network() -> NetworkResponse:
        return state_provider.network()

    @app.get("/api/v1/system", response_model=SystemResponse)
    def get_system() -> SystemResponse:
        return state_provider.system()

    return app


app = create_app()
