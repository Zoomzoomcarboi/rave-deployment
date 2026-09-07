// M2B.2b qualification utility. This is not production runtime code.
#include <hailo/hailort.hpp>

#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;

template <typename T>
T unwrap(hailort::Expected<T> result, const std::string &operation)
{
    if (!result) {
        throw std::runtime_error(operation + " failed, Hailo status " +
                                 std::to_string(result.status()));
    }
    return std::move(result.value());
}

void check(hailo_status status, const std::string &operation)
{
    if (HAILO_SUCCESS != status) {
        throw std::runtime_error(operation + " failed, Hailo status " +
                                 std::to_string(status));
    }
}

struct AlignedBuffer {
    explicit AlignedBuffer(size_t frame_size) : size(frame_size)
    {
        // HailoRT 4.23.0 warns that output buffers should be 16 KiB aligned.
        constexpr size_t alignment = 16384;
        const size_t allocation_size = ((size + alignment - 1) / alignment) * alignment;
        data = std::aligned_alloc(alignment, allocation_size);
        if (nullptr == data) {
            throw std::bad_alloc();
        }
    }
    ~AlignedBuffer() { std::free(data); }
    AlignedBuffer(const AlignedBuffer &) = delete;
    AlignedBuffer &operator=(const AlignedBuffer &) = delete;
    void *data = nullptr;
    size_t size = 0;
};

std::string order_name(hailo_format_order_t order)
{
    switch (order) {
    case HAILO_FORMAT_ORDER_NHWC: return "NHWC";
    case HAILO_FORMAT_ORDER_FCR: return "FCR";
    default: return "OTHER_" + std::to_string(static_cast<int>(order));
    }
}

std::string type_name(hailo_format_type_t type)
{
    switch (type) {
    case HAILO_FORMAT_TYPE_UINT8: return "UINT8";
    case HAILO_FORMAT_TYPE_UINT16: return "UINT16";
    case HAILO_FORMAT_TYPE_FLOAT32: return "FLOAT32";
    default: return "OTHER_" + std::to_string(static_cast<int>(type));
    }
}

void write_binary(const fs::path &path, const void *data, size_t size)
{
    std::ofstream output(path, std::ios::binary);
    output.write(static_cast<const char *>(data), static_cast<std::streamsize>(size));
    if (!output) {
        throw std::runtime_error("write failed: " + path.string());
    }
}

void capture(const fs::path &hef_path, const fs::path &input_path, const fs::path &output_dir,
             hailo_format_type_t output_type)
{
    auto device = unwrap(hailort::VDevice::create(), "create VDevice");
    auto model = unwrap(device->create_infer_model(hef_path.string()), "create infer model");

    auto input_stream = unwrap(model->input(), "get input stream");
    input_stream.set_format_type(HAILO_FORMAT_TYPE_UINT8);
    input_stream.set_format_order(HAILO_FORMAT_ORDER_NHWC);

    for (const auto &name : model->get_output_names()) {
        auto stream = unwrap(model->output(name), "get output stream " + name);
        stream.set_format_type(output_type);
        // Retain the HEF-selected order. HailoRT 4.23.0 defines both host-side
        // NHWC and host-side FCR as [N,H,W,C]. Runtime metadata is recorded below.
    }

    auto configured = unwrap(model->configure(), "configure model");
    auto bindings = unwrap(configured.create_bindings(), "create bindings");

    const auto input_size = input_stream.get_frame_size();
    AlignedBuffer input(input_size);
    std::ifstream input_file(input_path, std::ios::binary | std::ios::ate);
    if (!input_file || static_cast<size_t>(input_file.tellg()) != input_size) {
        throw std::runtime_error("input must contain exactly " + std::to_string(input_size) + " bytes");
    }
    input_file.seekg(0);
    input_file.read(static_cast<char *>(input.data), static_cast<std::streamsize>(input.size));
    check(unwrap(bindings.input(), "get input binding").set_buffer(
              hailort::MemoryView(input.data, input.size)), "bind input");

    std::map<std::string, std::unique_ptr<AlignedBuffer>> outputs;
    for (const auto &name : model->get_output_names()) {
        auto stream = unwrap(model->output(name), "get output stream " + name);
        auto buffer = std::make_unique<AlignedBuffer>(stream.get_frame_size());
        check(unwrap(bindings.output(name), "get output binding " + name).set_buffer(
                  hailort::MemoryView(buffer->data, buffer->size)), "bind output " + name);
        outputs.emplace(name, std::move(buffer));
    }

    check(configured.run(bindings, std::chrono::seconds(30)), "run inference");
    fs::create_directories(output_dir);

    std::ofstream metadata(output_dir / "capture-metadata.json");
    metadata << "{\n  \"schema_version\": 1,\n  \"input\": {\"name\": \""
             << input_stream.name() << "\", \"bytes\": " << input_size << "},\n  \"outputs\": [\n";
    bool first = true;
    for (const auto &name : model->get_output_names()) {
        auto stream = unwrap(model->output(name), "get output stream " + name);
        const auto shape = stream.shape();
        const auto format = stream.format();
        const auto suffix = (HAILO_FORMAT_TYPE_UINT16 == output_type) ? ".u16le" : ".f32le";
        const auto filename = name.substr(name.find_last_of('/') + 1) + suffix;
        write_binary(output_dir / filename, outputs.at(name)->data, outputs.at(name)->size);
        if (!first) metadata << ",\n";
        first = false;
        metadata << "    {\"name\": \"" << name << "\", \"file\": \"" << filename
                 << "\", \"bytes\": " << outputs.at(name)->size
                 << ", \"shape\": [" << shape.height << ", " << shape.width << ", "
                 << shape.features << "], \"format_type\": \"" << type_name(format.type)
                 << "\", \"format_order\": \"" << order_name(format.order)
                 << "\", \"format_flags\": " << format.flags << "}";
    }
    metadata << "\n  ]\n}\n";
    if (!metadata) {
        throw std::runtime_error("metadata write failed");
    }
}
} // namespace

int main(int argc, char **argv)
{
    if (argc != 5) {
        std::cerr << "usage: rave-hailo-capture HEF INPUT_RGB_UINT8 OUTPUT_DIRECTORY u16|f32\n";
        return 2;
    }
    try {
        const std::string output_type(argv[4]);
        if (("u16" != output_type) && ("f32" != output_type)) {
            throw std::runtime_error("output type must be u16 or f32");
        }
        capture(argv[1], argv[2], argv[3],
                ("u16" == output_type) ? HAILO_FORMAT_TYPE_UINT16 : HAILO_FORMAT_TYPE_FLOAT32);
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "capture failed: " << error.what() << '\n';
        return 1;
    }
}
