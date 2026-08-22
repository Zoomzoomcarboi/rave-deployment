"""Reproduce the RAVE V5 Pi camera-to-Hailo raw-inference benchmark.

This is a validation/benchmark utility, not the production RAVE runtime.
It intentionally stops at raw Hailo output tensors and does not implement YOLO26
postprocessing, tracking, temporal state, danger-zone logic, or metadata transport.

Validated baseline (2026-08-22):
- Arducam B0589: 1920x1080 MJPEG @ 60 FPS
- Native 1/2 JPEG decode: 960x540
- Half-scale RAVE crop: y=150:346 -> 960x196
- 960x960 RGB UINT8 letterbox, value 114
- Capture-driven latest-frame scheduler
- ~30 Hz acceptance rate
- Drop frames older than 5 ms at decode eligibility
- Hailo-8 YOLO26n HEF, raw six-tensor output
"""

from __future__ import annotations

import hashlib
import threading
import time

import cv2
import gi
import numpy as np
from hailo_platform import (
    HEF,
    ConfigureParams,
    HailoStreamInterface,
    InferVStreams,
    InputVStreamParams,
    OutputVStreamParams,
    VDevice,
)

gi.require_version("Gst", "1.0")
from gi.repository import Gst

HEF_PATH = "best.hef"
VALIDATED_HEF_SHA256 = "ebcda77f0694db7023dfd3926a357a8097e714cbc5985fe094a46805d3f48c19"
CAMERA = "/dev/video0"
DURATION_S = 20.0
TARGET_FPS = 30.0
PERIOD_S = 1.0 / TARGET_FPS
MAX_DECODE_START_AGE_MS = 5.0
CAMERA_START_TIMEOUT_S = 2.0
CAMERA_STALL_TIMEOUT_S = 1.0

stop_event = threading.Event()
frame_event = threading.Event()
compressed_lock = threading.Lock()
prepared_lock = threading.Lock()

latest_compressed: tuple[bytes, float] | None = None
latest_prepared: tuple[np.ndarray, float] | None = None
last_capture_time: float | None = None

stats = {
    "captured": 0,
    "compressed_overwrites": 0,
    "rate_limited": 0,
    "stale_drops": 0,
    "decode_attempts": 0,
    "decode_failures": 0,
    "prepared": 0,
    "prepared_overwrites": 0,
    "inferred": 0,
}

decode_start_age: list[float] = []
decode_ms: list[float] = []
preprocess_ms: list[float] = []
infer_start_age: list[float] = []
infer_ms: list[float] = []
result_age: list[float] = []

Gst.init(None)

pipeline = Gst.parse_launch(
    f"v4l2src device={CAMERA} ! "
    "image/jpeg,width=1920,height=1080,framerate=60/1 ! "
    "appsink name=sink sync=false max-buffers=1 drop=true"
)
sink = pipeline.get_by_name("sink")


def verify_validated_hef() -> None:
    """Refuse to reproduce V5 results with a different model artifact."""
    digest = hashlib.sha256()

    try:
        with open(HEF_PATH, "rb") as hef_file:
            for chunk in iter(lambda: hef_file.read(1024 * 1024), b""):
                digest.update(chunk)
    except FileNotFoundError as error:
        raise RuntimeError(f"Validated V5 HEF not found: {HEF_PATH}") from error

    actual_sha256 = digest.hexdigest()

    if actual_sha256 != VALIDATED_HEF_SHA256:
        raise RuntimeError(
            "HEF SHA-256 mismatch: this benchmark reproduces the frozen V5 "
            f"baseline only. expected={VALIDATED_HEF_SHA256} "
            f"actual={actual_sha256}"
        )

    print(f"Validated HEF SHA-256: {actual_sha256}")


def capture_worker() -> None:
    global last_capture_time, latest_compressed

    while not stop_event.is_set():
        sample = sink.emit("try-pull-sample", 100_000_000)
        if sample is None:
            continue

        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            continue

        try:
            jpeg = bytes(mapinfo.data)
        finally:
            buf.unmap(mapinfo)

        arrival = time.perf_counter()
        last_capture_time = arrival

        with compressed_lock:
            if latest_compressed is not None:
                stats["compressed_overwrites"] += 1
            latest_compressed = (jpeg, arrival)

        stats["captured"] += 1
        frame_event.set()



def raise_on_gstreamer_error() -> None:
    """Raise immediately if GStreamer reports a pipeline error."""
    bus = pipeline.get_bus()
    message = bus.pop_filtered(Gst.MessageType.ERROR)

    if message is None:
        return

    error, debug = message.parse_error()
    detail = f"{error.message}"
    if debug:
        detail += f" ({debug})"

    raise RuntimeError(f"GStreamer pipeline error: {detail}")


def wait_for_camera_start() -> None:
    """Require at least one real camera frame before timing the benchmark."""
    deadline = time.perf_counter() + CAMERA_START_TIMEOUT_S

    while time.perf_counter() < deadline:
        raise_on_gstreamer_error()

        if stats["captured"] > 0:
            return

        time.sleep(0.01)

    raise RuntimeError(
        f"No camera frames received within {CAMERA_START_TIMEOUT_S:.1f}s"
    )


def verify_camera_not_stalled(now: float) -> None:
    """Fail a reproduction run if an active camera stream stops producing frames."""
    if last_capture_time is None:
        raise RuntimeError("Camera stream has not produced a frame")

    age = now - last_capture_time
    if age > CAMERA_STALL_TIMEOUT_S:
        raise RuntimeError(
            f"Camera stream stalled for {age:.3f}s "
            f"(limit {CAMERA_STALL_TIMEOUT_S:.1f}s)"
        )

def decode_worker() -> None:
    global latest_compressed, latest_prepared

    next_due: float | None = None

    while not stop_event.is_set():
        frame_event.wait(timeout=0.1)
        frame_event.clear()

        if stop_event.is_set():
            break

        with compressed_lock:
            item = latest_compressed
            latest_compressed = None

        if item is None:
            continue

        jpeg, arrival = item

        if next_due is None:
            next_due = arrival

        if arrival < next_due:
            stats["rate_limited"] += 1
            continue

        now = time.perf_counter()
        age_ms = (now - arrival) * 1000.0

        if age_ms > MAX_DECODE_START_AGE_MS:
            stats["stale_drops"] += 1
            continue

        next_due += PERIOD_S
        while next_due < now - PERIOD_S:
            next_due += PERIOD_S

        stats["decode_attempts"] += 1
        t_decode_start = time.perf_counter()
        decode_start_age.append((t_decode_start - arrival) * 1000.0)

        encoded = np.frombuffer(jpeg, dtype=np.uint8)

        t0 = time.perf_counter()
        half = cv2.imdecode(encoded, cv2.IMREAD_REDUCED_COLOR_2)
        t1 = time.perf_counter()

        if half is None:
            stats["decode_failures"] += 1
            continue

        decode_ms.append((t1 - t0) * 1000.0)

        t0 = time.perf_counter()
        crop = half[150:346, :, :]
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        prepared = cv2.copyMakeBorder(
            rgb,
            382,
            382,
            0,
            0,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        prepared = np.ascontiguousarray(prepared[None, ...], dtype=np.uint8)
        t1 = time.perf_counter()

        preprocess_ms.append((t1 - t0) * 1000.0)

        with prepared_lock:
            if latest_prepared is not None:
                stats["prepared_overwrites"] += 1
            latest_prepared = (prepared, arrival)

        stats["prepared"] += 1


def report(name: str, values: list[float]) -> None:
    if not values:
        print(f"{name}: no samples")
        return

    data = np.asarray(values)
    print(
        f"{name:<31}"
        f" p50={np.percentile(data, 50):7.3f}"
        f" p95={np.percentile(data, 95):7.3f}"
        f" p99={np.percentile(data, 99):7.3f} ms"
    )


def main() -> None:
    verify_validated_hef()
    hef = HEF(HEF_PATH)
    configure_params = ConfigureParams.create_from_hef(
        hef=hef,
        interface=HailoStreamInterface.PCIe,
    )

    print("=== RAVE V5 — HARD FRESHNESS GUARD ===")
    print("Camera:        1920x1080 MJPEG @ 60")
    print("Decode:        native JPEG 1/2 -> 960x540")
    print("Scheduler:     capture-driven latest-frame")
    print(f"Rate target:   {TARGET_FPS:.0f} Hz")
    print(f"Max input age: {MAX_DECODE_START_AGE_MS:.1f} ms")
    print("Model:         YOLO26n 960 Hailo-8")
    print(f"Duration:      {DURATION_S:.0f}s")
    print()

    with VDevice() as device:
        network_group = device.configure(hef, configure_params)[0]
        network_group_params = network_group.create_params()
        input_params = InputVStreamParams.make(network_group, quantized=True)
        output_params = OutputVStreamParams.make(network_group, quantized=True)

        with InferVStreams(
            network_group,
            input_params,
            output_params,
        ) as infer, network_group.activate(network_group_params):
            warm = np.zeros((1, 960, 960, 3), dtype=np.uint8)
            for _ in range(10):
                infer.infer(warm)

            state_result = pipeline.set_state(Gst.State.PLAYING)
            if state_result == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("GStreamer pipeline failed to enter PLAYING")

            capture_thread = threading.Thread(target=capture_worker, daemon=True)
            decode_thread = threading.Thread(target=decode_worker, daemon=True)

            try:
                capture_thread.start()
                decode_thread.start()

                wait_for_camera_start()

                start = time.perf_counter()
                end = start + DURATION_S

                while time.perf_counter() < end:
                    raise_on_gstreamer_error()
                    verify_camera_not_stalled(time.perf_counter())

                    global latest_prepared
                    with prepared_lock:
                        item = latest_prepared
                        latest_prepared = None

                    if item is None:
                        time.sleep(0.00025)
                        continue

                    prepared, arrival = item
                    t0 = time.perf_counter()
                    infer_start_age.append((t0 - arrival) * 1000.0)
                    infer.infer(prepared)
                    t1 = time.perf_counter()

                    infer_ms.append((t1 - t0) * 1000.0)
                    result_age.append((t1 - arrival) * 1000.0)
                    stats["inferred"] += 1

                duration = time.perf_counter() - start

                raise_on_gstreamer_error()

                if stats["inferred"] == 0:
                    raise RuntimeError(
                        "Benchmark completed without any Hailo inference results"
                    )
            finally:
                stop_event.set()
                frame_event.set()

                if capture_thread.is_alive():
                    capture_thread.join(timeout=2.0)
                if decode_thread.is_alive():
                    decode_thread.join(timeout=2.0)

                pipeline.set_state(Gst.State.NULL)

    print()
    print("=== COUNTS ===")
    print(f"Wall time:                 {duration:.3f} s")
    print(f"Captured:                  {stats['captured']}")
    print(f"Capture rate:              {stats['captured'] / duration:.2f} FPS")
    print(f"Compressed overwrites:     {stats['compressed_overwrites']}")
    print(f"Rate-limited arrivals:     {stats['rate_limited']}")
    print(f"Stale-frame drops:         {stats['stale_drops']}")
    print(f"Decode attempts:           {stats['decode_attempts']}")
    print(f"Decode rate:               {stats['decode_attempts'] / duration:.2f} FPS")
    print(f"Decode failures:           {stats['decode_failures']}")
    print(f"Prepared:                  {stats['prepared']}")
    print(f"Prepared overwrites:       {stats['prepared_overwrites']}")
    print(f"Inferred:                  {stats['inferred']}")
    print(f"RAVE result rate:          {stats['inferred'] / duration:.2f} FPS")

    print()
    print("=== LATENCY ===")
    report("Arrival -> decode start:", decode_start_age)
    report("Half JPEG decode:", decode_ms)
    report("RAVE preprocess:", preprocess_ms)
    report("Arrival -> inference start:", infer_start_age)
    report("Hailo inference:", infer_ms)
    report("Arrival -> result:", result_age)

    print()
    print("NOTE:")
    print("Frames older than 5 ms at decode eligibility are discarded.")
    print("They are never queued and never inferred.")
    print("Sensor exposure and USB/UVC transport are not included.")


if __name__ == "__main__":
    main()
