from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .config import load_config
from .health import Status, run_checks

app = typer.Typer(help="RAVE edge management commands")


@app.command()
def doctor(config: Annotated[Path, typer.Option(exists=True, readable=True)]) -> None:
    """Validate configuration and report local hardware readiness."""
    cfg = load_config(config)
    checks = run_checks(cfg.camera.device, cfg.inference.model_bundle)
    failed = False
    for check in checks:
        typer.echo(f"[{check.status}] {check.name}: {check.detail}")
        failed |= check.status is Status.FAIL
    if failed:
        raise typer.Exit(code=1)


@app.command("config-check")
def config_check(config: Annotated[Path, typer.Option(exists=True, readable=True)]) -> None:
    cfg = load_config(config)
    typer.echo(f"Configuration valid for {cfg.device.name} ({cfg.device.mode})")


if __name__ == "__main__":
    app()
