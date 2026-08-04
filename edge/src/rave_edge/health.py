from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import platform
import shutil


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _pi_hardware_status(machine: str, model: str | None) -> Check:
    if machine != "aarch64":
        return Check(
            "pi_deployment_readiness",
            Status.FAIL,
            f"{machine} is suitable for host development only, not Raspberry Pi deployment",
        )
    if not model or "Raspberry Pi 5" not in model:
        return Check(
            "pi_deployment_readiness",
            Status.FAIL,
            "aarch64 detected, but Raspberry Pi 5 identity was not verified",
        )
    return Check("pi_deployment_readiness", Status.PASS, model.strip("\x00"))


def run_checks(
    camera_device: str,
    model_bundle: str,
    *,
    machine: str | None = None,
    pi_model: str | None = None,
) -> list[Check]:
    detected_machine = machine or platform.machine()
    if pi_model is None:
        model_path = Path("/proc/device-tree/model")
        if model_path.is_file():
            pi_model = model_path.read_text(errors="replace")

    host_status = (
        Status.PASS if detected_machine in {"x86_64", "aarch64"} else Status.WARN
    )
    checks = [
        Check(
            "development_host",
            host_status,
            f"{detected_machine}; Python {platform.python_version()}",
        ),
        _pi_hardware_status(detected_machine, pi_model),
        Check(
            "camera",
            Status.PASS if Path(camera_device).exists() else Status.FAIL,
            camera_device,
        ),
        Check(
            "model_bundle",
            Status.PASS if Path(model_bundle).exists() else Status.FAIL,
            model_bundle,
        ),
        Check(
            "hailo_runtime",
            Status.PASS if shutil.which("hailortcli") else Status.FAIL,
            "hailortcli in PATH",
        ),
    ]
    return checks
