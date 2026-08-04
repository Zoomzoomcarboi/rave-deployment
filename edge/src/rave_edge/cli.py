from __future__ import annotations

from pathlib import Path
import typer

from .config import load_config
from .health import run_checks

app = typer.Typer(help="RAVE edge management commands")


@app.command()
def doctor(config: Path = typer.Option(..., exists=True, readable=True)) -> None:
    """Validate configuration and report local hardware readiness."""
    cfg = load_config(config)
    checks = run_checks(cfg.camera.device, cfg.inference.model_bundle)
    failed = False
    for check in checks:
        symbol = "PASS" if check.ok else "FAIL"
        typer.echo(f"[{symbol}] {check.name}: {check.detail}")
        failed |= not check.ok
    if failed:
        raise typer.Exit(code=1)


@app.command("config-check")
def config_check(config: Path = typer.Option(..., exists=True, readable=True)) -> None:
    cfg = load_config(config)
    typer.echo(f"Configuration valid for {cfg.device.get('name', 'unnamed-device')}")


if __name__ == "__main__":
    app()
