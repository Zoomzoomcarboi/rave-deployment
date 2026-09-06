import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import rave_model as model

REPO = Path(__file__).resolve().parents[1]
FAKE_HEF = b"small synthetic HEF fixture\n"


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    baseline = copy.deepcopy(model.SELECTED)
    baseline["sha256"] = hashlib.sha256(FAKE_HEF).hexdigest()
    monkeypatch.setattr(model, "SELECTED", baseline)
    source = tmp_path / "source"
    source.mkdir()
    (source / baseline["artifact"]).write_bytes(FAKE_HEF)
    manifest = source / "manifest.json"
    manifest.write_text(json.dumps(baseline))
    store = tmp_path / "models"
    store.mkdir(mode=0o755)
    return source, manifest, store


def test_release_manifest_matches_frozen_baseline():
    path = REPO / "models/RAVE-2026.09.02-001.manifest.json"
    assert model.load_manifest(path) == model.SELECTED
    assert model.SELECTED["sha256"] == (
        "913053bb96815b16b79093924ed563844f8edbc02ef6d40129a290eff3e32aea"
    )
    assert model.SELECTED["output_abi"] is None


def test_install_valid_and_idempotent(candidate):
    source, manifest, store = candidate
    installed = model.install_model(manifest, source, store)
    assert installed == store / model.SELECTED["model_id"]
    assert (installed / model.SELECTED["artifact"]).read_bytes() == FAKE_HEF
    assert (installed.stat().st_mode & 0o777) == 0o755
    assert ((installed / "manifest.json").stat().st_mode & 0o777) == 0o644
    inode = installed.stat().st_ino
    assert model.install_model(manifest, source, store) == installed
    assert installed.stat().st_ino == inode
    assert not (store / "current").exists()
    assert not (store / "known-good").exists()
    assert not list(store.glob(".stage-*"))


@pytest.mark.parametrize("damage", ["wrong-hash", "missing"])
def test_invalid_artifact_not_installed(candidate, damage):
    source, manifest, store = candidate
    artifact = source / model.SELECTED["artifact"]
    if damage == "missing":
        artifact.unlink()
    else:
        artifact.write_bytes(b"wrong")
    with pytest.raises((ValueError, OSError)):
        model.install_model(manifest, source, store)
    assert not (store / model.SELECTED["model_id"]).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("schema_version", 1.0),
        ("model_id", "../outside"),
        ("model_id", "/outside"),
        ("model_id", "another-model"),
        ("artifact", "../escape.hef"),
        ("artifact", "/escape.hef"),
        ("sha256", "0" * 64),
        ("accelerator", "hailo8l"),
        ("hailort", "4.24.0"),
        ("input", {"width": 640, "height": 960, "dtype": "UINT8", "layout": "NHWC"}),
        ("input", {"width": 960, "height": 960, "dtype": "FLOAT32", "layout": "NHWC"}),
        ("input", {"width": 960, "height": 960, "dtype": "UINT8", "layout": "NCHW"}),
        ("classes", ["motorcycle", "vehicle"]),
        ("classes", ["vehicle"]),
        ("output_abi", {"invented": "tensor"}),
    ],
)
def test_manifest_field_rejected(candidate, field, value):
    source, manifest, store = candidate
    data = json.loads(manifest.read_text())
    data[field] = value
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        model.install_model(manifest, source, store)
    assert not (store / model.SELECTED["model_id"]).exists()


@pytest.mark.parametrize("content", ["{", "[]", "null", "{}", '{"schema_version":1}'])
def test_malformed_manifest(candidate, content):
    source, manifest, store = candidate
    manifest.write_text(content)
    with pytest.raises(ValueError):
        model.install_model(manifest, source, store)


@pytest.mark.parametrize("kind", ["empty", "corrupt", "symlink"])
def test_existing_version_never_overwritten(candidate, kind):
    source, manifest, store = candidate
    version = store / model.SELECTED["model_id"]
    if kind == "symlink":
        version.symlink_to(source, target_is_directory=True)
    elif kind == "empty":
        version.mkdir()
    else:
        model.install_model(manifest, source, store)
        (version / model.SELECTED["artifact"]).write_bytes(b"corrupt")
    inode = version.lstat().st_ino
    with pytest.raises((ValueError, OSError)):
        model.install_model(manifest, source, store)
    assert version.lstat().st_ino == inode


def test_atomic_activation_and_explicit_qualification(candidate, monkeypatch):
    source, manifest, store = candidate
    version = model.install_model(manifest, source, store)
    (store / "current").symlink_to("prior-version")
    real_replace = os.replace
    observed = []

    def replace(src, dst):
        observed.append(os.readlink(store / "current"))
        assert Path(src).is_symlink()
        real_replace(src, dst)

    monkeypatch.setattr(model.os, "replace", replace)
    model.activate_model(version.name, store)
    assert observed == ["prior-version"]
    assert os.readlink(store / "current") == version.name
    assert not (store / "known-good").exists()
    model.qualify_model(version.name, store)
    assert os.readlink(store / "known-good") == version.name


def test_failed_replace_keeps_current(candidate, monkeypatch):
    source, manifest, store = candidate
    version = model.install_model(manifest, source, store)
    (store / "current").symlink_to("prior-version")

    def fail(*args):
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr(model.os, "replace", fail)
    with pytest.raises(OSError):
        model.activate_model(version.name, store)
    assert os.readlink(store / "current") == "prior-version"
    assert not list(store.glob(".pointer-*"))


@pytest.mark.parametrize("target", ["missing", "../escape", "/outside", ".stage-partial"])
def test_invalid_or_staging_activation_preserves_current(candidate, target):
    _, _, store = candidate
    (store / "current").symlink_to("prior-version")
    (store / ".stage-partial").mkdir()
    with pytest.raises((ValueError, OSError)):
        model.activate_model(target, store)
    assert os.readlink(store / "current") == "prior-version"


def test_rollback_uses_qualified_model(candidate):
    source, manifest, store = candidate
    version = model.install_model(manifest, source, store)
    model.qualify_model(version.name, store)
    (store / "current").symlink_to("failed-version")
    model.rollback_model(store)
    assert os.readlink(store / "current") == version.name
    assert os.readlink(store / "known-good") == version.name


@pytest.mark.parametrize("target", [None, "missing", "../source", "/outside", "current"])
def test_broken_known_good_preserves_current(candidate, target):
    _, _, store = candidate
    (store / "current").symlink_to("prior-version")
    if target is not None:
        (store / "known-good").symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        model.rollback_model(store)
    assert os.readlink(store / "current") == "prior-version"


def test_corrupt_qualified_model_cannot_rollback(candidate):
    source, manifest, store = candidate
    version = model.install_model(manifest, source, store)
    model.qualify_model(version.name, store)
    (version / model.SELECTED["artifact"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        model.rollback_model(store)
    assert not (store / "current").exists()


def test_install_rename_is_same_filesystem_and_post_validation(candidate, monkeypatch):
    source, manifest, store = candidate
    rename = os.rename

    def observe(src, dst):
        assert Path(src).parent == store
        assert not Path(dst).exists()
        model.validate_model(Path(src) / "manifest.json", Path(src))
        rename(src, dst)

    monkeypatch.setattr(model.os, "rename", observe)
    model.install_model(manifest, source, store)


def test_failed_copy_leaves_no_version_or_pointer_change(candidate, monkeypatch):
    source, manifest, store = candidate
    (store / "current").symlink_to("prior-version")

    def partial_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError("synthetic full disk")

    monkeypatch.setattr(model.shutil, "copyfile", partial_copy)
    with pytest.raises(OSError):
        model.install_model(manifest, source, store)
    assert not (store / model.SELECTED["model_id"]).exists()
    assert os.readlink(store / "current") == "prior-version"
    assert not list(store.glob(".stage-*"))


def test_admin_commands_refuse_overlapping_writer(candidate):
    source, manifest, store = candidate
    with model._store_lock(store), pytest.raises(BlockingIOError):
        model.install_model(manifest, source, store)


@pytest.mark.parametrize("name", ["manifest.json", "rave_yolo26n_960.hef"])
def test_symlinked_candidate_files_rejected(candidate, name):
    source, manifest, store = candidate
    path = source / name
    real = source / ("real-" + name)
    path.rename(real)
    path.symlink_to(real.name)
    with pytest.raises(ValueError):
        model.install_model(manifest, source, store)


def test_model_store_image_definition_and_binary_prohibition():
    import subprocess

    import yaml

    layer = yaml.safe_load((REPO / "image/layer/rave-base.yaml").read_text())
    hooks = "\n".join(layer["mmdebstrap"]["customize-hooks"])
    assert 'install -d -o 0 -g 0 -m 0755 "$rootfs/opt/rave/models"' in hooks
    assert 'scripts/rave_model.py" "$rootfs/usr/libexec/rave/rave-model"' in hooks
    subprocess.run(["bash", "-n"], input=hooks, text=True, check=True)
    result = subprocess.run(
        ["bash", "scripts/check-repository-safety.sh", "--artifact-paths-from-stdin"],
        input="models/rave_yolo26n_960.hef\n",
        text=True,
        capture_output=True,
        cwd=REPO,
        check=False,
    )
    assert result.returncode == 1
    ignored = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        input="models/rave_yolo26n_960.hef\n",
        text=True,
        capture_output=True,
        cwd=REPO,
        check=False,
    )
    assert ignored.returncode == 0
    tracked = subprocess.check_output(["git", "ls-files", "*.hef"], cwd=REPO, text=True)
    assert tracked == ""


@pytest.mark.parametrize(
    ("mode", "uid", "gid", "content", "valid"),
    [
        (0o755, 0, 0, False, True),
        (0o775, 0, 0, False, False),
        (0o755, 1001, 0, False, False),
        (0o755, 0, 1001, False, False),
        (0o755, 0, 0, True, False),
    ],
)
def test_generated_image_model_store(tmp_path, monkeypatch, mode, uid, gid, content, valid):
    from scripts.verify_rave_image import VerificationError, verify_model_store

    store = tmp_path / "opt/rave/models"
    store.mkdir(parents=True)
    store.chmod(mode)
    if content:
        (store / "unexpected.hef").write_bytes(FAKE_HEF)
    original = Path.lstat

    def target_stat(path):
        info = original(path)
        if path == store:
            values = list(info)
            values[4:6] = [uid, gid]
            return os.stat_result(values)
        return info

    monkeypatch.setattr(Path, "lstat", target_stat)
    if valid:
        verify_model_store(tmp_path)
    else:
        with pytest.raises(VerificationError):
            verify_model_store(tmp_path)


def test_generated_image_missing_or_symlink_store_rejected(tmp_path):
    from scripts.verify_rave_image import VerificationError, verify_model_store

    with pytest.raises(VerificationError):
        verify_model_store(tmp_path)
    store = tmp_path / "opt/rave/models"
    store.parent.mkdir(parents=True)
    store.symlink_to(tmp_path)
    with pytest.raises(VerificationError):
        verify_model_store(tmp_path)


@pytest.mark.parametrize("damage", ["missing-manifest", "missing-hef", "corrupt-hef"])
def test_damaged_selected_version_preserves_current(candidate, damage):
    source, manifest, store = candidate
    version = model.install_model(manifest, source, store)
    (store / "current").symlink_to("prior-version")
    if damage == "missing-manifest":
        (version / "manifest.json").unlink()
    elif damage == "missing-hef":
        (version / model.SELECTED["artifact"]).unlink()
    else:
        (version / model.SELECTED["artifact"]).write_bytes(b"corrupt")
    with pytest.raises((ValueError, OSError)):
        model.activate_model(version.name, store)
    assert os.readlink(store / "current") == "prior-version"
