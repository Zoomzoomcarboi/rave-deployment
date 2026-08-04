import json

from rave_edge.messages import PROTOCOL_VERSION, mock_message


def test_mock_message_is_versioned_json() -> None:
    payload = json.loads(mock_message(42).to_json())
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["frame_id"] == 42
    assert payload["detections"] == []
