from rave_edge.health import Status, run_checks


def _status(checks, name: str) -> Status:
    return next(check.status for check in checks if check.name == name)


def test_x86_is_development_capable_but_not_pi_ready() -> None:
    checks = run_checks("/missing-camera", "/missing-model", machine="x86_64")
    assert _status(checks, "development_host") is Status.PASS
    assert _status(checks, "pi_deployment_readiness") is Status.FAIL


def test_verified_pi5_is_hardware_ready() -> None:
    checks = run_checks(
        "/missing-camera",
        "/missing-model",
        machine="aarch64",
        pi_model="Raspberry Pi 5 Model B Rev 1.0",
    )
    assert _status(checks, "pi_deployment_readiness") is Status.PASS
