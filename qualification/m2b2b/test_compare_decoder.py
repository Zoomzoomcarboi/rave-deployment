import numpy as np
from compare_decoder import decode, sigmoid, two_stage_top300


def test_sigmoid_has_expected_low_medium_high_values() -> None:
    actual = sigmoid(np.array([-8.0, 0.0, 8.0], dtype=np.float32))
    np.testing.assert_allclose(actual, [0.00033535, 0.5, 0.99966466], rtol=0, atol=1e-7)


def test_decode_uses_ltrb_anchor_and_stride_at_all_scales() -> None:
    regression = []
    logits = []
    for size in (120, 60, 30):
        reg = np.zeros((size, size, 4), dtype=np.float32)
        reg[0, 0] = [1.0, 2.0, 3.0, 4.0]
        regression.append(reg)
        logits.append(np.full((size, size, 2), -20.0, dtype=np.float32))
    boxes, _ = decode(regression, logits)
    np.testing.assert_array_equal(boxes[0], [-4.0, -12.0, 28.0, 36.0])
    np.testing.assert_array_equal(boxes[120 * 120], [-8.0, -24.0, 56.0, 72.0])
    np.testing.assert_array_equal(boxes[120 * 120 + 60 * 60], [-16.0, -48.0, 112.0, 144.0])


def test_two_stage_topk_can_emit_both_classes_for_one_location() -> None:
    boxes = np.zeros((301, 4), dtype=np.float32)
    scores = np.zeros((301, 2), dtype=np.float32)
    scores[7] = [0.99, 0.98]
    scores[8:, 0] = np.linspace(0.97, 0.01, 293)
    _, identities = two_stage_top300(boxes, scores)
    assert identities[0].tolist() == [7, 0]
    assert identities[1].tolist() == [7, 1]


def test_nhwc_element_offset_contract() -> None:
    height, width, channels = 3, 5, 4
    tensor = np.arange(height * width * channels, dtype=np.uint16).reshape(height, width, channels)
    for y in range(height):
        for x in range(width):
            for channel in range(channels):
                offset = ((y * width) + x) * channels + channel
                assert tensor.reshape(-1)[offset] == tensor[y, x, channel]
