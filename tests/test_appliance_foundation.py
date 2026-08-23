import inspect
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_gate_one_web_has_no_privileged_network_or_hardware_calls() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "setup-ui" / "rave_web").glob("*.py")
    )
    forbidden = ("import subprocess", "from subprocess", "os.system", "import dbus", "import cv2")
    assert all(term not in source for term in forbidden)


def test_image_composes_all_gate_one_layers() -> None:
    config = yaml.safe_load((ROOT / "image/config/rave-os-gate1.yaml").read_text())
    assert config["include"]["file"] == "trixie-minbase.yaml"
    assert config["device"]["layer"] == "rpi5"
    assert config["device"]["hostname"] == "rave-pi"
    assert config["image"] == {"layer": "image-rpios", "name": "rave-os-gate2a"}
    assert config["deploy"] == {"compression": "zstd"}
    assert list(config["layer"].values()) == [
        "rave-base",
        "rave-identity",
        "rave-network",
        "rave-hailo",
        "rave-runtime",
        "rave-web",
        "rave-update",
    ]


def test_gate_two_a_builder_is_exactly_pinned() -> None:
    lock = json.loads((ROOT / "image/rpi-image-gen.lock.json").read_text())
    assert lock == {
        "repository": "https://github.com/raspberrypi/rpi-image-gen.git",
        "tag": "v2.7.0",
        "commit": "a7b6d4806183195f3efadb533f58c8e46393d057",
        "container_image": (
            "docker.io/library/debian@"
            "sha256:34cd9e9fd437c0a095ec39cb2e73422c9f30821b0d0848ed74fd0d43bae4d958"
        ),
    }


def test_gate_two_a_entrypoint_uses_source_tree_and_relative_config_name() -> None:
    script = (ROOT / "scripts/build-rave-os.sh").read_text()
    assert 'resolved_commit == "$builder_commit"' in script
    assert "-S /rave/image -c rave-os-gate1.yaml" in script
    assert "--device" not in script
    assert "RAVE_ARTIFACT_DENYLIST" in script


def test_gate_two_a_entrypoint_initializes_fresh_unprivileged_build_tree() -> None:
    script = (ROOT / "scripts/build-rave-os.sh").read_text()
    create_output = script.index("install -d -m 0755 /out/work /out/work/cache")
    create_config = script.index("/tmp/rave-builder-home/.config/containers")
    create_local = script.index("/tmp/rave-builder-home/.local/share/containers")
    normalize_owner = script.index("chown -R 1000:1000 /out /tmp/rave-builder-home")
    unprivileged_build = script.index("setpriv --reuid=1000 --regid=1000 --init-groups")

    assert create_output < normalize_owner < unprivileged_build
    assert create_config < normalize_owner
    assert create_local < normalize_owner
    assert "chmod 0777" not in script


def test_runtime_paths_and_service_identity_are_product_scoped() -> None:
    base = (ROOT / "image/layer/rave-base.yaml").read_text()
    unit = (ROOT / "systemd/rave-webd.service").read_text()
    for path in ("/opt/rave", "/etc/rave", "/var/lib/rave", "/var/log/rave", "/run/rave"):
        assert path in base
    assert "User=rave" in unit and "Group=rave" in unit
    assert "PrivateDevices=true" in unit
    assert "--host 127.0.0.1" in unit
    assert "RuntimeDirectory=" not in unit


def test_identity_layer_clears_cloned_state() -> None:
    layer = (ROOT / "image/layer/rave-identity.yaml").read_text()
    assert "cleanup-hooks:" in layer
    assert "customize-hooks:" not in layer
    for marker in (
        "/etc/machine-id",
        "ssh_host_*",
        "NetworkManager/system-connections",
        "/var/lib/rave/identity",
        "/var/lib/rave/pairing",
        "/var/lib/rave/session",
        "/var/log/rave",
    ):
        assert marker in layer


def test_image_hooks_strictly_guard_and_quote_target_rootfs() -> None:
    for path in sorted((ROOT / "image/layer").glob("rave-*.yaml")):
        document = yaml.safe_load(path.read_text())
        hooks = document.get("mmdebstrap", {})
        for phase in ("customize-hooks", "cleanup-hooks"):
            for hook in hooks.get(phase, []):
                assert "set -eu" in hook
                required = (
                    "rootfs_input=${1:?missing target rootfs}",
                    'rootfs=$(realpath -e -- "$rootfs_input")',
                    'test -n "$rootfs"',
                    'test "$rootfs" != "/"',
                    'test -d "$rootfs',
                )
                positions = [hook.index(fragment) for fragment in required]
                assert positions == sorted(positions)
                first_mutation = min(
                    hook.index(command)
                    for command in ("mkdir ", "chroot ", "rm ", "touch ", "install ", "find ")
                    if command in hook
                )
                assert hook.index('test "$rootfs" != "/"') < first_mutation
                assert 'test "$rootfs" != "/"' in hook
                assert "$1/" not in hook


def test_identity_cleanup_rejects_unsafe_or_implausible_roots_before_deletion() -> None:
    layer = yaml.safe_load((ROOT / "image/layer/rave-identity.yaml").read_text())
    cleanup = layer["mmdebstrap"]["cleanup-hooks"][0]
    guard_end = cleanup.index('test -d "$rootfs/var"')
    destructive_start = cleanup.index("rm -f --")
    guards = cleanup[:destructive_start]
    assert 'rootfs_input=${1:?missing target rootfs}' in guards
    assert 'rootfs=$(realpath -e -- "$rootfs_input")' in guards
    assert 'test -n "$rootfs"' in guards
    assert 'test "$rootfs" != "/"' in guards
    assert 'test -d "$rootfs/etc"' in guards
    assert 'test -d "$rootfs/var"' in guards
    assert guard_end < destructive_start


def test_product_layer_dependencies_are_semantic_not_linear() -> None:
    for name in ("rave-network", "rave-hailo", "rave-runtime", "rave-web", "rave-update"):
        layer = (ROOT / f"image/layer/{name}.yaml").read_text()
        assert "# X-Env-Layer-Requires: rave-base" in layer


def test_rave_web_declares_direct_pydantic_dependency() -> None:
    control = (ROOT / "packaging/debian/control").read_text()
    rave_web_stanza = control.split("Package: rave-web", maxsplit=1)[1]
    assert "Depends:" in rave_web_stanza
    assert "python3-pydantic" in rave_web_stanza


def test_rave_web_preserves_star_pilot_mit_notice() -> None:
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    install = (ROOT / "packaging/debian/rave-web.install").read_text()
    assert "Zoomzoomcarboi/StarPilot" in notice
    assert "c1fd07db6d4ce5db51b3ec896dac7db43454e365" in notice
    assert "Copyright (c) 2018, Comma.ai, Inc." in notice
    assert "Permission is hereby granted, free of charge" in notice
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in notice
    assert "THIRD_PARTY_NOTICES.md /usr/share/doc/rave-web" in install


def test_provider_routes_use_fastapi_sync_execution_contract() -> None:
    from rave_web.app import create_app

    provider_paths = {"/api/v1/status", "/api/v1/network", "/api/v1/system"}
    endpoints = {route.path: route.endpoint for route in create_app().routes if route.path in provider_paths}
    assert endpoints.keys() == provider_paths
    assert all(not inspect.iscoroutinefunction(endpoint) for endpoint in endpoints.values())
