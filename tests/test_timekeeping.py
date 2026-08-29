from datetime import UTC, datetime
from pathlib import Path

from rave_web.models import Availability
from rave_web.providers import PiManagementProvider

ROOT = Path(__file__).resolve().parents[1]


def test_pi_provider_reports_synchronized_and_unsynchronized_time_truthfully(
    tmp_path: Path,
) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('PRETTY_NAME="RAVE OS Test"\n', encoding="utf-8")
    synchronized = tmp_path / "synchronized"
    rtc = tmp_path / "rtc0"
    rtc.mkdir()
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    provider = PiManagementProvider(
        os_release=os_release,
        synchronized_marker=synchronized,
        rtc_path=rtc,
        utc_now=lambda: now,
    )
    unsynchronized = provider.system()
    assert unsynchronized.availability == Availability.READY
    assert unsynchronized.time.current_utc == now
    assert unsynchronized.time.synchronized is False
    assert unsynchronized.time.rtc_available is True
    synchronized.touch()
    assert provider.system().time.synchronized is True


def test_image_declares_utc_and_preserves_systemd_time_ownership() -> None:
    config = (ROOT / "image/config/rave-os.yaml").read_text(encoding="utf-8")
    identity = (ROOT / "image/layer/rave-identity.yaml").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify_rave_image.py").read_text(encoding="utf-8")
    runtime = (
        ROOT / "image/overlays/etc/systemd/network/10-rave-ethernet.network"
    ).read_text(encoding="utf-8")
    ap = (
        ROOT
        / "image/overlays/etc/NetworkManager/system-connections/rave-setup.nmconnection"
    ).read_text(encoding="utf-8")
    assert "timezone: Etc/UTC" in config
    assert "/var/lib/systemd/timesync/clock" not in identity
    assert "systemd-timesyncd" in verifier
    assert "Gateway=" not in runtime and "DNS=" not in runtime
    assert "never-default=true" in ap and "method=shared" not in ap
    management_source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for directory in (ROOT / "setup-ui/rave_web", ROOT / "setup-ui/rave_networkd")
        for path in directory.rglob("*.py")
    )
    forbidden_clock_mutations = (
        "clock_settime",
        "settimeofday",
        "timedatectl set-time",
        "date --set",
        "date -s",
        "hwclock --systohc",
        "hwclock --hctosys",
    )
    assert all(command not in management_source for command in forbidden_clock_mutations)
