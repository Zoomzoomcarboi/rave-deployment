from pathlib import Path

import pytest
import yaml

from scripts.verify_rave_image import VerificationError, verify_mdns_discovery

ROOT = Path(__file__).resolve().parents[1]
AVAHI_CONFIG = ROOT / "image/overlays/etc/rave/avahi-daemon.conf"
AVAHI_OVERRIDE = ROOT / "systemd/avahi-daemon.service.d/90-rave-management.conf"


def test_image_declares_wlan_scoped_mdns_responder() -> None:
    layer = yaml.safe_load((ROOT / "image/layer/rave-web.yaml").read_text(encoding="utf-8"))
    assert "avahi-daemon" in layer["mmdebstrap"]["packages"]

    config = AVAHI_CONFIG.read_text(encoding="utf-8")
    assert "host-name=rave-pi" in config
    assert "domain-name=local" in config
    assert "allow-interfaces=wlan0" in config
    assert "publish-addresses=yes" in config
    assert "enable-reflector=no" in config
    assert "eth0" not in config

    control = (ROOT / "packaging/debian/control").read_text(encoding="utf-8")
    install = (ROOT / "packaging/debian/rave-web.install").read_text(encoding="utf-8")
    assert "Depends: avahi-daemon," in control
    assert "image/overlays/etc/rave/avahi-daemon.conf /etc/rave" in install
    assert "/etc/avahi/avahi-daemon.conf" not in install
    assert (
        "systemd/avahi-daemon.service.d/90-rave-management.conf "
        "/lib/systemd/system/avahi-daemon.service.d"
    ) in install


def test_web_image_hook_installs_mdns_policy_without_ethernet_changes() -> None:
    hook = (ROOT / "image/bdebstrap/customize90-rave-web").read_text(encoding="utf-8")
    assert "image/overlays/etc/rave/avahi-daemon.conf" in hook
    assert '"$rootfs/etc/rave/avahi-daemon.conf"' in hook
    assert "90-rave-management.conf" in hook
    assert "multi-user.target.wants/avahi-daemon.service" in hook
    assert "sockets.target.wants/avahi-daemon.socket" in hook
    assert "10.77.0.1" not in hook
    assert "eth0" not in hook


def test_rave_pi_hostname_and_runtime_ethernet_policy_are_preserved() -> None:
    image = yaml.safe_load((ROOT / "image/config/rave-os.yaml").read_text(encoding="utf-8"))
    assert image["device"]["hostname"] == "rave-pi"

    runtime = (
        ROOT / "image/overlays/etc/systemd/network/10-rave-ethernet.network"
    ).read_text(encoding="utf-8")
    assert "Address=10.77.0.1/24" in runtime
    assert "DHCP=no" in runtime
    assert "DefaultRouteOnDevice=no" in runtime
    assert "IPMasquerade=no" in runtime
    assert "MulticastDNS" not in runtime

    web_socket = (ROOT / "systemd/rave-webd.socket").read_text(encoding="utf-8")
    assert "BindToDevice=wlan0" in web_socket
    assert "ListenStream=8080" in web_socket
    assert "eth0" not in web_socket


def mdns_rootfs(tmp_path: Path) -> Path:
    root = tmp_path / "rootfs"
    binary = root / "usr/sbin/avahi-daemon"
    binary.parent.mkdir(parents=True)
    binary.write_text("synthetic executable\n", encoding="utf-8")
    policy = root / "etc/rave/avahi-daemon.conf"
    policy.parent.mkdir(parents=True)
    policy.write_text(AVAHI_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    service = root / "usr/lib/systemd/system/avahi-daemon.service"
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text(
        "[Service]\nExecStart=/usr/sbin/avahi-daemon -s\n",
        encoding="utf-8",
    )
    override = root / "usr/lib/systemd/system/avahi-daemon.service.d/90-rave-management.conf"
    override.parent.mkdir(parents=True)
    override.write_text(AVAHI_OVERRIDE.read_text(encoding="utf-8"), encoding="utf-8")
    for target, relative in (
        (
            "/usr/lib/systemd/system/avahi-daemon.service",
            "etc/systemd/system/multi-user.target.wants/avahi-daemon.service",
        ),
        (
            "/usr/lib/systemd/system/avahi-daemon.socket",
            "etc/systemd/system/sockets.target.wants/avahi-daemon.socket",
        ),
    ):
        want = root / relative
        want.parent.mkdir(parents=True)
        want.symlink_to(target)
    return root


def test_artifact_verifier_accepts_wlan_scoped_mdns_policy(tmp_path: Path) -> None:
    package_status = "Package: avahi-daemon\nStatus: install ok installed\n"
    assert "allow-interfaces=wlan0" in verify_mdns_discovery(
        mdns_rootfs(tmp_path), package_status
    )


def test_artifact_verifier_rejects_mdns_outside_wlan(tmp_path: Path) -> None:
    root = mdns_rootfs(tmp_path)
    policy = root / "etc/rave/avahi-daemon.conf"
    policy.write_text(
        policy.read_text(encoding="utf-8").replace(
            "allow-interfaces=wlan0", "allow-interfaces=eth0"
        ),
        encoding="utf-8",
    )
    package_status = "Package: avahi-daemon\nStatus: install ok installed\n"
    with pytest.raises(VerificationError, match="exclusively to wlan0"):
        verify_mdns_discovery(root, package_status)
