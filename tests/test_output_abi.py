"""Host contracts and checker behavior using a synthetic native API, not Hailo hardware."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "RAVE-2026.09.02-001"
SHA = "913053bb96815b16b79093924ed563844f8edbc02ef6d40129a290eff3e32aea"
SIDECAR = ROOT / f"models/{MODEL_ID}.output-abi.json"
SOURCE = ROOT / "scripts/rave_hef_abi_check.cpp"
ROWS = [
    ("input_layer1", [960, 960, 3], "UINT8", "NHWC", [0, 1, 0, 255]),
    ("conv61", [120, 120, 4], "UINT16", "NHWC", [5475, 0.0001895461901, -1.037765384, 5.173094749]),
    ("conv77", [60, 60, 4], "UINT16", "FCR", [1367, 0.0003041393065, -0.415758431, 9.549974442]),
    ("conv91", [30, 30, 4], "UINT16", "FCR", [0, 0.0003050283703, 0, 9.994864464]),
    ("conv64", [120, 120, 2], "UINT16", "NHWC", [30696, 0.001581834396, -48.55598831, 3.275979042]),
    ("conv80", [60, 60, 2], "UINT16", "FCR", [31952, 0.004313362297, -137.8205566, 3.515390158]),
    ("conv94", [30, 30, 2], "UINT16", "FCR", [31835, 0.003570360132, -113.6624146, 3.327575684]),
]
FIELDS = [
    "shape.height",
    "shape.width",
    "shape.features",
    "format.type",
    "format.order",
    "quant_info.qp_zp",
    "quant_info.qp_scale",
    "quant_info.limvals_min",
    "quant_info.limvals_max",
]


def test_sidecar_identity_and_interface():
    data = json.loads(SIDECAR.read_text())
    assert data["model_id"] == MODEL_ID
    assert data["sha256"] == SHA
    assert data["artifact"] == "rave_yolo26n_960.hef"
    assert data["network_groups"] == [
        {
            "name": "rave_yolo26n_960",
            "networks": ["rave_yolo26n_960/rave_yolo26n_960"],
        }
    ]
    assert data["hailort"] == "4.23.0"
    assert data["accelerator"] == "HAILO8"
    assert data["interface"] == "application-facing Hailo VStreams (not physical hardware Streams)"
    assert data["shape_axes"] == ["height", "width", "features"]
    assert len(data["inputs"]) == 1
    assert len(data["outputs"]) == 6
    streams = data["inputs"] + data["outputs"]
    assert len({s["name"] for s in streams}) == 7
    assert data["observed_parse_hef_output_order"] == [s["name"] for s in data["outputs"]]


@pytest.mark.parametrize("row", ROWS, ids=[r[0] for r in ROWS])
def test_exact_qualified_metadata_and_cpp_table(row):
    suffix, shape, dtype, order, quant = row
    data = json.loads(SIDECAR.read_text())
    name = "rave_yolo26n_960/" + suffix
    streams = {s["name"]: s for s in data["inputs"] + data["outputs"]}
    assert streams[name] == {
        "name": name,
        "shape": shape,
        "type": dtype,
        "order": order,
        "quantization": dict(zip(["qp_zp", "qp_scale", "limvals_min", "limvals_max"], quant)),
    }
    # Bind the independently specified evidence to the compiled constant table as well.
    text = SOURCE.read_text()
    pattern = (
        r'\{"' + re.escape(name) + r'",\s*\{\{([^}]+)\},\s*'
        r"HAILO_FORMAT_TYPE_(\w+),\s*HAILO_FORMAT_ORDER_(\w+),\s*\{([^}]+)\}\}\}"
    )
    found = re.findall(pattern, text)
    assert len(found) == 1
    dims, actual_type, actual_order, numbers = found[0]
    assert [int(v) for v in dims.split(",")] == shape
    assert (actual_type, actual_order) == (dtype, order)
    assert [float(v.strip().removesuffix("f")) for v in numbers.split(",")] == quant


def test_image_build_contract_and_m2b1_boundary():
    text = (ROOT / "image/layer/rave-runtime.yaml").read_text()
    hook = yaml.safe_load(text)["mmdebstrap"]["customize-hooks"][0]
    assert "# X-Env-Layer-Version: 0.2.0" in text
    assert "# X-Env-Layer-Requires: rave-base,rave-hailo" in text
    assert 'chroot "$rootfs" g++ -std=c++17' in hook
    assert "-lhailort" in hook
    assert 'install -o 0 -g 0 -m 0755 "$build_dir/rave-hef-abi-check"' in hook
    assert '"$rootfs/usr/libexec/rave/rave-hef-abi-check"' in hook
    assert 'install -o 0 -g 0 -m 0644 "$repository_root/models/' + MODEL_ID in hook
    assert '"$rootfs/usr/share/rave/models/' + MODEL_ID + '.output-abi.json"' in hook
    assert 'touch "$rootfs/opt/rave/runtime/PERCEPTION_NOT_INTEGRATED"' in hook
    assert '\'${Version}\' hailort)" = "4.23.0"' in hook
    subprocess.run(["bash", "-n"], input=hook, text=True, check=True)
    manifest = json.loads((ROOT / f"models/{MODEL_ID}.manifest.json").read_text())
    assert manifest["output_abi"] is None
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            "HEAD",
            "--",
            "scripts/rave_model.py",
            f"models/{MODEL_ID}.manifest.json",
        ],
        cwd=ROOT,
        check=True,
    )
    assert ".hef" not in hook
    tracked = subprocess.check_output(["git", "ls-files", "*.hef"], cwd=ROOT, text=True)
    assert not tracked
    result = subprocess.run(
        ["bash", "scripts/check-repository-safety.sh", "--artifact-paths-from-stdin"],
        input="models/rave_yolo26n_960.hef\n",
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1


@pytest.fixture(scope="module")
def checker(tmp_path_factory):
    """Compile production checker against a tiny fake Hailo API; no vendor headers."""
    compiler = shutil.which("g++")
    assert compiler, "C++17 host compiler required for native checker behavior tests"
    directory = tmp_path_factory.mktemp("synthetic-hailo-api")
    include = directory / "hailo"
    include.mkdir()
    header = r"""
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <string>
#include <vector>
enum hailo_format_type_t { HAILO_FORMAT_TYPE_UINT8, HAILO_FORMAT_TYPE_UINT16 };
enum hailo_format_order_t { HAILO_FORMAT_ORDER_NHWC, HAILO_FORMAT_ORDER_FCR };
struct hailo_network_info_t { char name[128]; };
struct hailo_3d_image_shape_t { unsigned height, width, features; };
struct hailo_quant_info_t { float qp_zp, qp_scale, limvals_min, limvals_max; };
struct hailo_vstream_info_t {
    char name[128];
    hailo_3d_image_shape_t shape;
    struct { hailo_format_type_t type; hailo_format_order_t order; } format;
    hailo_quant_info_t quant_info;
};
namespace hailort {
template <typename T> struct Expected {
    T item; bool ok = true;
    explicit operator bool() const { return ok; }
    int status() const { return 99; }
    T &value() { return item; }
};
class Hef {
    std::string scenario;
public:
    static Expected<Hef> create(const std::string &path) {
        Hef hef; hef.scenario = path; return {hef, path != "create-error"};
    }
    std::vector<std::string> get_network_groups_names() const {
        if (scenario == "no-groups") return {};
        if (scenario == "extra-group") return {"rave_yolo26n_960", "extra"};
        if (scenario == "wrong-group") return {"wrong"};
        return {"rave_yolo26n_960"};
    }
    Expected<std::vector<hailo_network_info_t>> get_network_infos(const std::string &group) const {
        if (group != "rave_yolo26n_960") return {{}, false};
        if (scenario == "network-error") return {{}, false};
        if (scenario == "no-networks") return {{}};
        if (scenario == "extra-network")
            return {{{"rave_yolo26n_960/rave_yolo26n_960"}, {"extra"}}};
        if (scenario == "wrong-network") return {{{"wrong"}}};
        return {{{"rave_yolo26n_960/rave_yolo26n_960"}}};
    }
    Expected<std::vector<hailo_vstream_info_t>> get_input_vstream_infos(const std::string &group) const {
        if (group != "rave_yolo26n_960") return {{}, false};
        return infos(true);
    }
    Expected<std::vector<hailo_vstream_info_t>> get_output_vstream_infos(const std::string &group) const {
        if (group != "rave_yolo26n_960") return {{}, false};
        return infos(false);
    }
    Expected<std::vector<hailo_vstream_info_t>> infos(bool input) const {
        std::vector<hailo_vstream_info_t> all = {
"""
    for suffix, shape, dtype, order, quant in ROWS:
        header += (
            '{"rave_yolo26n_960/'
            + suffix
            + '", {'
            + ",".join(map(str, shape))
            + "}, {HAILO_FORMAT_TYPE_"
            + dtype
            + ", HAILO_FORMAT_ORDER_"
            + order
            + "}, {"
            + ",".join(repr(float(v)) + "f" for v in quant)
            + "}},\n"
        )
    header += """};
        std::vector<hailo_vstream_info_t> result(all.begin() + (input ? 0 : 1),
                                               input ? all.begin() + 1 : all.end());
        const std::string side = input ? "input" : "output";
        if (scenario == side + "-error") return {result, false};
        if (scenario == side + "-missing") result.pop_back();
        if (scenario == side + "-extra") result.push_back(result.front());
        if (scenario == side + "-unexpected") std::snprintf(result[0].name, 128, "unexpected");
        if (scenario == "output-duplicate" && !input) result[1] = result[0];
        if (scenario == "reordered") std::reverse(result.begin(), result.end());
"""
    for index in range(7):
        side = "input" if index == 0 else "output"
        slot = max(index - 1, 0)
        for field in FIELDS:
            entry = f"result[{slot}].{field}"
            if field == "format.type":
                change = f"{entry} = static_cast<hailo_format_type_t>(99);"
            elif field == "format.order":
                change = f"{entry} = static_cast<hailo_format_order_t>(99);"
            elif field.startswith("quant_info"):
                change = (
                    f"{entry} = std::nextafter({entry}, std::numeric_limits<float>::infinity());"
                )
            else:
                change = f"++{entry};"
            header += f'if (scenario == "{index}-{field}" && side == "{side}") {{ {change} }}\n'
    header += """
        if (scenario == "nan") result[0].quant_info.qp_scale = std::nanf("");
        if (scenario == "infinity") result[0].quant_info.qp_scale = INFINITY;
        return {result};
    }
};
}
"""
    (include / "hef.hpp").write_text(header)
    binary = directory / "checker"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(directory),
            str(SOURCE),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


@pytest.mark.parametrize("scenario", ["valid", "reordered"])
def test_checker_accepts_exact_metadata_independent_of_reporting_order(checker, scenario):
    result = subprocess.run([str(checker), scenario], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "VStream ABI matches" in result.stdout


@pytest.mark.parametrize(
    "scenario",
    [
        "create-error",
        "input-error",
        "output-error",
        "input-missing",
        "input-extra",
        "input-unexpected",
        "output-missing",
        "output-extra",
        "output-unexpected",
        "output-duplicate",
        "nan",
        "infinity",
    ]
    + [f"{index}-{field}" for index in range(7) for field in FIELDS],
)
def test_checker_rejects_wrong_sets_and_each_tensor_property(checker, scenario):
    result = subprocess.run([str(checker), scenario], text=True, capture_output=True, check=False)
    assert result.returncode == 1
    assert "HEF ABI check failed:" in result.stderr
    assert not result.stdout


def test_checker_requires_exactly_one_path(checker):
    for arguments in ([], ["one", "two"]):
        result = subprocess.run([str(checker), *arguments], capture_output=True, check=False)
        assert result.returncode == 2
        assert b"usage:" in result.stderr


@pytest.mark.parametrize(
    ("scenario", "diagnostic"),
    [
        ("wrong-group", "network-group name mismatch"),
        ("no-groups", "network-group count mismatch"),
        ("extra-group", "network-group count mismatch"),
        ("wrong-network", "network name mismatch"),
        ("no-networks", "network count mismatch"),
        ("extra-network", "network count mismatch"),
        ("network-error", "network metadata failed"),
        ("valid", None),
    ],
)
def test_checker_requires_exact_qualified_network_topology(checker, scenario, diagnostic):
    result = subprocess.run([str(checker), scenario], text=True, capture_output=True, check=False)
    if diagnostic is None:
        assert result.returncode == 0, result.stderr
        assert "VStream ABI matches" in result.stdout
    else:
        assert result.returncode == 1
        assert diagnostic in result.stderr
        assert not result.stdout
