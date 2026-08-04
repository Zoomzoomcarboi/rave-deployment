from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import time

# Internal mock/debug JSON schema version. This is not a network protocol version.
MOCK_JSON_VERSION = 1


@dataclass(frozen=True)
class Detection:
    track_id: int
    object_class: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    zone: str
    risk: str


@dataclass(frozen=True)
class FrameMessage:
    protocol_version: int
    device_id: str
    model_version: str
    frame_id: int
    captured_monotonic_ns: int
    processing_latency_ms: float
    detections: tuple[Detection, ...]

    def to_json(self) -> bytes:
        return json.dumps(asdict(self), separators=(",", ":")).encode("utf-8")


def mock_message(frame_id: int) -> FrameMessage:
    return FrameMessage(
        protocol_version=MOCK_JSON_VERSION,
        device_id="rave-edge-dev",
        model_version="mock-0.0.1",
        frame_id=frame_id,
        captured_monotonic_ns=time.monotonic_ns(),
        processing_latency_ms=12.5,
        detections=(),
    )
