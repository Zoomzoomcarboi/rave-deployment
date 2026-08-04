from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import shutil


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def run_checks(camera_device: str, model_bundle: str) -> list[Check]:
    checks = [
        Check("architecture", platform.machine() in {"aarch64", "x86_64"}, platform.machine()),
        Check("python", True, platform.python_version()),
        Check("camera", Path(camera_device).exists(), camera_device),
        Check("model bundle", Path(model_bundle).exists(), model_bundle),
        Check("hailortcli", shutil.which("hailortcli") is not None, "hailortcli in PATH"),
    ]
    return checks
