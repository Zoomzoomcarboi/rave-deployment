import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = ROOT / "scripts/verify-systemd-units.sh"


def _write_fake_systemd_analyze(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

unit_path = Path(os.environ["SYSTEMD_UNIT_PATH"].split(":", 1)[0])
required = {"rave-webd.socket", "NetworkManager.service"}
missing = sorted(name for name in required if not (unit_path / name).is_file())
for argument in sys.argv[1:]:
    candidate = Path(argument)
    if not candidate.is_file():
        continue
    text = candidate.read_text(encoding="utf-8")
    for dependency in re.findall(r"^(?:Requires|Wants)=(.+)$", text, re.MULTILINE):
        for name in dependency.split():
            if name.startswith("rave-") and not (unit_path / name).is_file():
                missing.append(name)
if missing:
    print("missing units: " + ", ".join(sorted(set(missing))), file=sys.stderr)
    raise SystemExit(1)
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_verifier(tmp_path: Path, unit_directory: Path) -> subprocess.CompletedProcess[str]:
    fake_analyzer = tmp_path / "systemd-analyze"
    _write_fake_systemd_analyze(fake_analyzer)
    environment = os.environ.copy()
    environment["SYSTEMD_ANALYZE"] = str(fake_analyzer)
    return subprocess.run(
        [str(VERIFY_SCRIPT), str(unit_directory)],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_ci_verifier_resolves_real_socket_and_target_os_stub(tmp_path: Path) -> None:
    result = _run_verifier(tmp_path, ROOT / "systemd")
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_verifier_fails_for_missing_internal_rave_dependency(tmp_path: Path) -> None:
    units = tmp_path / "units"
    units.mkdir()
    for source in (ROOT / "systemd").iterdir():
        if source.is_file():
            (units / source.name).write_bytes(source.read_bytes())
    web_service = units / "rave-webd.service"
    web_service.write_text(
        web_service.read_text(encoding="utf-8").replace(
            "rave-webd.socket", "rave-missing.socket"
        ),
        encoding="utf-8",
    )

    result = _run_verifier(tmp_path, units)

    assert result.returncode != 0
    assert "rave-missing.socket" in result.stderr


def test_ci_verification_preserves_production_dependency_semantics() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    networkd = (ROOT / "systemd/rave-networkd.service").read_text(encoding="utf-8")
    dhcp = (ROOT / "systemd/rave-management-dhcp.service").read_text(encoding="utf-8")

    assert "scripts/verify-systemd-units.sh" in workflow
    assert "|| true" not in workflow
    assert "--offline" not in workflow
    assert "Requires=NetworkManager.service" in networkd
    assert "After=NetworkManager.service" in networkd
    assert "Requires=NetworkManager.service" in dhcp
    assert "After=NetworkManager.service" in dhcp


def test_ci_stub_is_not_referenced_by_deployment_artifacts() -> None:
    for root in (ROOT / "image", ROOT / "systemd"):
        for path in root.rglob("*"):
            if path.is_file():
                assert "CI-only NetworkManager" not in path.read_text(
                    encoding="utf-8", errors="ignore"
                )
