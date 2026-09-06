// M2B.2: application VStream metadata only; no device configuration or inference.
// Selected SHA256: 913053bb96815b16b79093924ed563844f8edbc02ef6d40129a290eff3e32aea
// HEF identity is checked separately by the unchanged M2B.1 model validator.
#include <hailo/hef.hpp>

#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {
struct Contract {
    hailo_3d_image_shape_t shape;
    hailo_format_type_t type;
    hailo_format_order_t order;
    hailo_quant_info_t quant;
};
using Contracts = std::map<std::string, Contract>;

// Decimal evidence rounded to the native float32 fields; no comparison tolerance.
const Contracts kInputs = {
    {"rave_yolo26n_960/input_layer1", {{960, 960, 3},
        HAILO_FORMAT_TYPE_UINT8, HAILO_FORMAT_ORDER_NHWC,
        {0.0f, 1.0f, 0.0f, 255.0f}}},
};

const Contracts kOutputs = {
    {"rave_yolo26n_960/conv61", {{120, 120, 4},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_NHWC,
        {5475.0f, 0.0001895461901f, -1.037765384f, 5.173094749f}}},
    {"rave_yolo26n_960/conv77", {{60, 60, 4},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_FCR,
        {1367.0f, 0.0003041393065f, -0.415758431f, 9.549974442f}}},
    {"rave_yolo26n_960/conv91", {{30, 30, 4},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_FCR,
        {0.0f, 0.0003050283703f, 0.0f, 9.994864464f}}},
    {"rave_yolo26n_960/conv64", {{120, 120, 2},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_NHWC,
        {30696.0f, 0.001581834396f, -48.55598831f, 3.275979042f}}},
    {"rave_yolo26n_960/conv80", {{60, 60, 2},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_FCR,
        {31952.0f, 0.004313362297f, -137.8205566f, 3.515390158f}}},
    {"rave_yolo26n_960/conv94", {{30, 30, 2},
        HAILO_FORMAT_TYPE_UINT16, HAILO_FORMAT_ORDER_FCR,
        {31835.0f, 0.003570360132f, -113.6624146f, 3.327575684f}}},
};

template <typename T>
void require_equal(const T actual, const T expected, const std::string &field)
{
    if (actual != expected) {
        throw std::runtime_error(field + " mismatch");
    }
}

template <typename T>
T unwrap(hailort::Expected<T> result, const std::string &operation)
{
    if (!result) {
        throw std::runtime_error(operation + " failed, Hailo status " +
                                 std::to_string(result.status()));
    }
    return std::move(result.value());
}

void check_properties(const hailo_vstream_info_t &info, const Contract &expected)
{
    const std::string name(info.name);
    require_equal(info.shape.height, expected.shape.height, name + " height");
    require_equal(info.shape.width, expected.shape.width, name + " width");
    require_equal(info.shape.features, expected.shape.features, name + " features");
    require_equal(info.format.type, expected.type, name + " type");
    require_equal(info.format.order, expected.order, name + " order");
    require_equal(info.quant_info.qp_zp, expected.quant.qp_zp, name + " qp_zp");
    require_equal(info.quant_info.qp_scale, expected.quant.qp_scale, name + " qp_scale");
    require_equal(info.quant_info.limvals_min, expected.quant.limvals_min, name + " limvals_min");
    require_equal(info.quant_info.limvals_max, expected.quant.limvals_max, name + " limvals_max");
}

void check_names_and_properties(const std::vector<hailo_vstream_info_t> &infos,
                                const Contracts &expected, const std::string &direction)
{
    require_equal(infos.size(), expected.size(), direction + " VStream count");
    std::set<std::string> seen;
    for (const auto &info : infos) {
        const std::string name(info.name);
        if (!seen.insert(name).second) {
            throw std::runtime_error("duplicate VStream: " + name);
        }
        const auto found = expected.find(name);
        if (found == expected.end()) {
            throw std::runtime_error("unexpected VStream: " + name);
        }
        check_properties(info, found->second);
    }
    // Equal counts + unique expected names also prove that no expected name is missing.
}

void check_hef(const std::string &path)
{
    auto hef = unwrap(hailort::Hef::create(path), "read HEF");
    const auto groups = hef.get_network_groups_names();
    require_equal<std::size_t>(groups.size(), 1, "network-group count");
    const auto &group = groups.front();
    require_equal(group, std::string("rave_yolo26n_960"), "network-group name");
    const auto networks = unwrap(hef.get_network_infos(group), "network metadata");
    require_equal<std::size_t>(networks.size(), 1, "network count");
    require_equal(std::string(networks.front().name),
                  std::string("rave_yolo26n_960/rave_yolo26n_960"), "network name");
    const auto inputs = unwrap(hef.get_input_vstream_infos(group), "input VStream metadata");
    const auto outputs = unwrap(hef.get_output_vstream_infos(group), "output VStream metadata");
    check_names_and_properties(inputs, kInputs, "input");
    check_names_and_properties(outputs, kOutputs, "output");
}
} // namespace

int main(int argc, char **argv)
{
    if (argc != 2) {
        std::cerr << "usage: rave-hef-abi-check HEF_PATH\n";
        return 2;
    }
    try {
        check_hef(argv[1]);
        std::cout << "RAVE-2026.09.02-001 VStream ABI matches; "
                     "HEF SHA256 must be verified separately.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "HEF ABI check failed: " << error.what() << '\n';
        return 1;
    }
}
