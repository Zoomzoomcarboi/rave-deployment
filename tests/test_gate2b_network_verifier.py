import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_rave_image import (
    VerificationError,
    verify_dhcp_service,
    verify_dnsmasq_configuration,
    verify_management_profile,
    verify_networkd_service,
    verify_runtime_ethernet_configuration,
    verify_web_service,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "image/overlays/etc/NetworkManager/system-connections/rave-setup.nmconnection"
DNSMASQ = ROOT / "image/overlays/etc/rave/network/dnsmasq.conf"
DHCP_UNIT = ROOT / "systemd/rave-management-dhcp.service"
WEB_UNIT = ROOT / "systemd/rave-webd.service"
WEB_SOCKET = ROOT / "systemd/rave-webd.socket"
NETWORKD_UNIT = ROOT / "systemd/rave-networkd.service"
ETHERNET_NETWORK = ROOT / "image/overlays/etc/systemd/network/10-rave-ethernet.network"
NM_UNMANAGED = ROOT / "image/overlays/etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf"


def copied_file(tmp_path: Path, source: Path, relative: str, mode: int = 0o644) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    path.chmod(mode)
    return path


def dhcp_rootfs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    rootfs = tmp_path / "rootfs"
    unit = copied_file(
        rootfs,
        DHCP_UNIT,
        "usr/lib/systemd/system/rave-management-dhcp.service",
    )
    lease_directory = rootfs / "var/lib/misc"
    lease_directory.mkdir(parents=True)
    lease_directory.chmod(0o755)
    original_stat = Path.stat

    def root_owned_lease_directory(path: Path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == lease_directory:
            values = list(result)
            values[stat.ST_UID] = 0
            values[stat.ST_GID] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", root_owned_lease_directory)
    return rootfs, unit


def ethernet_rootfs(tmp_path: Path) -> tuple[Path, Path]:
    rootfs = tmp_path / "rootfs"
    network = copied_file(
        rootfs,
        ETHERNET_NETWORK,
        "etc/systemd/network/10-rave-ethernet.network",
    )
    copied_file(
        rootfs,
        NM_UNMANAGED,
        "etc/NetworkManager/conf.d/10-rave-unmanaged-runtime.conf",
    )
    return rootfs, network


def networkd_rootfs(tmp_path: Path) -> tuple[Path, Path]:
    rootfs = tmp_path / "rootfs"
    unit = copied_file(
        rootfs,
        NETWORKD_UNIT,
        "usr/lib/systemd/system/rave-networkd.service",
    )
    for relative in (
        "setup-ui/rave_networkd/backend.py",
        "setup-ui/rave_networkd/server.py",
        "setup-ui/rave_network_ipc/client.py",
    ):
        copied_file(rootfs, ROOT / relative, f"opt/rave/management/{relative.removeprefix('setup-ui/')}")
    return rootfs, unit


def test_artifact_verifier_accepts_corrected_management_profile(tmp_path: Path) -> None:
    profile = copied_file(tmp_path, PROFILE, "rave-setup.nmconnection", 0o600)
    verify_management_profile(profile)


def test_artifact_verifier_rejects_management_profile_without_autoconnect(
    tmp_path: Path,
) -> None:
    profile = copied_file(tmp_path, PROFILE, "rave-setup.nmconnection", 0o600)
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("autoconnect=false\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(VerificationError, match="autoconnect"):
        verify_management_profile(profile)


def test_artifact_verifier_accepts_networkd_core_dump_protection(tmp_path: Path) -> None:
    rootfs, unit = networkd_rootfs(tmp_path)
    verify_networkd_service(rootfs, unit)


def test_artifact_verifier_rejects_networkd_shell_execution(tmp_path: Path) -> None:
    rootfs, unit = networkd_rootfs(tmp_path)
    backend = rootfs / "opt/rave/management/rave_networkd/backend.py"
    backend.write_text(
        backend.read_text(encoding="utf-8") + "\nsubprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )

    with pytest.raises(VerificationError, match="shell=True"):
        verify_networkd_service(rootfs, unit)


def test_artifact_verifier_rejects_networkd_core_dump_protection_removal(
    tmp_path: Path,
) -> None:
    rootfs, unit = networkd_rootfs(tmp_path)
    unit.write_text(
        unit.read_text(encoding="utf-8").replace("LimitCORE=0\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match="LimitCORE"):
        verify_networkd_service(rootfs, unit)


@pytest.mark.parametrize(
    ("addition", "message"),
    (
        ("gateway=", "gateway property"),
        ("gateway=192.168.77.254", "gateway property"),
        ("route1=0.0.0.0/0,192.168.77.254", "route settings"),
    ),
)
def test_artifact_verifier_rejects_management_gateway_or_default_route(
    tmp_path: Path, addition: str, message: str
) -> None:
    profile = copied_file(tmp_path, PROFILE, "rave-setup.nmconnection", 0o600)
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("may-fail=false\n", f"may-fail=false\n{addition}\n"),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match=message):
        verify_management_profile(profile)


def test_artifact_verifier_rejects_management_default_route_permission(tmp_path: Path) -> None:
    profile = copied_file(tmp_path, PROFILE, "rave-setup.nmconnection", 0o600)
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("never-default=true", "never-default=false"),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match="default route"):
        verify_management_profile(profile)


def test_artifact_verifier_accepts_isolated_runtime_ethernet(tmp_path: Path) -> None:
    rootfs, _ = ethernet_rootfs(tmp_path)
    verify_runtime_ethernet_configuration(rootfs)


@pytest.mark.parametrize(
    ("old", "new"),
    (
        ("DefaultRouteOnDevice=no", "DefaultRouteOnDevice=yes"),
        ("DHCP=no", "DHCP=yes"),
        ("IPMasquerade=no", "IPMasquerade=yes"),
        ("IPv6AcceptRA=no", "IPv6AcceptRA=yes"),
    ),
)
def test_artifact_verifier_rejects_runtime_ethernet_route_or_ownership_drift(
    tmp_path: Path, old: str, new: str
) -> None:
    rootfs, network = ethernet_rootfs(tmp_path)
    network.write_text(network.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(VerificationError, match="runtime Ethernet policy changed"):
        verify_runtime_ethernet_configuration(rootfs)


def test_artifact_verifier_rejects_networkmanager_eth0_override(tmp_path: Path) -> None:
    rootfs, _ = ethernet_rootfs(tmp_path)
    override = rootfs / "etc/NetworkManager/conf.d/99-unsafe.conf"
    override.write_text("[device-eth0]\nmatch-device=interface-name:eth0\nmanaged=true\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="another NetworkManager configuration"):
        verify_runtime_ethernet_configuration(rootfs)


@pytest.mark.parametrize(
    "relative",
    (
        "etc/systemd/network/20-overlapping.network",
        "etc/systemd/network/10-rave-ethernet.network.d/90-override.conf",
    ),
)
def test_artifact_verifier_rejects_overlapping_runtime_networkd_policy(
    tmp_path: Path, relative: str
) -> None:
    rootfs, _ = ethernet_rootfs(tmp_path)
    copied_file(rootfs, ETHERNET_NETWORK, relative)
    with pytest.raises(VerificationError, match="networkd policies|unexpected drop-ins"):
        verify_runtime_ethernet_configuration(rootfs)


def test_artifact_verifier_accepts_bounded_dnsmasq_contract(tmp_path: Path) -> None:
    config = copied_file(tmp_path, DNSMASQ, "dnsmasq.conf")
    verify_dnsmasq_configuration(config)


def test_artifact_verifier_rejects_invalid_log_dhcp_boolean(tmp_path: Path) -> None:
    config = copied_file(tmp_path, DNSMASQ, "dnsmasq.conf")
    config.write_text(config.read_text(encoding="utf-8") + "log-dhcp=0\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="log-dhcp"):
        verify_dnsmasq_configuration(config)


def test_artifact_verifier_rejects_dhcp_router_advertisement(tmp_path: Path) -> None:
    config = copied_file(tmp_path, DNSMASQ, "dnsmasq.conf")
    config.write_text(
        config.read_text(encoding="utf-8").replace("dhcp-option=3", "dhcp-option=3,192.168.77.1"),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match="router or DNS"):
        verify_dnsmasq_configuration(config)


def test_host_dnsmasq_parser_smoke_check(tmp_path: Path) -> None:
    dnsmasq = shutil.which("dnsmasq")
    if dnsmasq is None:
        pytest.skip("host dnsmasq is unavailable; target parser remains a mandatory image-build gate")
    config = copied_file(tmp_path, DNSMASQ, "dnsmasq.conf")
    result = subprocess.run(
        [
            dnsmasq,
            "--test",
            f"--conf-file={config}",
            "--no-hosts",
            "--no-resolv",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_artifact_verifier_accepts_strict_dhcp_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs, unit = dhcp_rootfs(tmp_path, monkeypatch)
    verify_dhcp_service(rootfs, unit)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ("ProtectSystem=strict", "ProtectSystem=false", "ProtectSystem=strict"),
        ("ReadWritePaths=/var/lib/misc", "ReadWritePaths=/", "exactly /var/lib/misc"),
        ("ReadWritePaths=/var/lib/misc", "", "exactly /var/lib/misc"),
    ),
)
def test_artifact_verifier_rejects_weakened_dhcp_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    message: str,
) -> None:
    rootfs, unit = dhcp_rootfs(tmp_path, monkeypatch)
    unit.write_text(unit.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    with pytest.raises(VerificationError, match=message):
        verify_dhcp_service(rootfs, unit)


def test_artifact_verifier_rejects_carried_dhcp_lease_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rootfs, unit = dhcp_rootfs(tmp_path, monkeypatch)
    (rootfs / "var/lib/misc/dnsmasq.leases").write_text("synthetic lease\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="carries a DHCP lease"):
        verify_dhcp_service(rootfs, unit)


def test_artifact_verifier_accepts_management_only_web_listener(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    unit = copied_file(rootfs, WEB_UNIT, "usr/lib/systemd/system/rave-webd.service")
    socket_unit = copied_file(rootfs, WEB_SOCKET, "usr/lib/systemd/system/rave-webd.socket")
    wants = rootfs / "etc/systemd/system/sockets.target.wants"
    wants.mkdir(parents=True)
    (wants / "rave-webd.socket").symlink_to("/usr/lib/systemd/system/rave-webd.socket")
    verify_web_service(rootfs, unit, socket_unit)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ("BindToDevice=wlan0", "BindToDevice=eth0", "exclusively to wlan0"),
        ("BindToDevice=wlan0", "", "exclusively to wlan0"),
        ("ListenStream=8080", "ListenStream=10.77.0.1:8080", "port changed"),
    ),
)
def test_artifact_verifier_rejects_non_management_web_socket(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    rootfs = tmp_path / "rootfs"
    unit = copied_file(rootfs, WEB_UNIT, "usr/lib/systemd/system/rave-webd.service")
    socket_unit = copied_file(rootfs, WEB_SOCKET, "usr/lib/systemd/system/rave-webd.socket")
    socket_unit.write_text(
        socket_unit.read_text(encoding="utf-8").replace(old, new),
        encoding="utf-8",
    )
    wants = rootfs / "etc/systemd/system/sockets.target.wants"
    wants.mkdir(parents=True)
    (wants / "rave-webd.socket").symlink_to("/usr/lib/systemd/system/rave-webd.socket")
    with pytest.raises(VerificationError, match=message):
        verify_web_service(rootfs, unit, socket_unit)


def test_artifact_verifier_rejects_web_service_owned_listener(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    unit = copied_file(rootfs, WEB_UNIT, "usr/lib/systemd/system/rave-webd.service")
    socket_unit = copied_file(rootfs, WEB_SOCKET, "usr/lib/systemd/system/rave-webd.socket")
    unit.write_text(
        unit.read_text(encoding="utf-8").replace("--fd 3", "--fd 3 --host 10.77.0.1"),
        encoding="utf-8",
    )
    with pytest.raises(VerificationError, match="additional listener"):
        verify_web_service(rootfs, unit, socket_unit)
