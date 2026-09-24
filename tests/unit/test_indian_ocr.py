"""The Indian-trained plate recogniser: its preprocessing, decode, port and wiring.

The preprocessing test is the one that matters most. The inference script
published with the weights pads crops with black pixels; the model was trained
with PaddleOCR's `resize_norm_img`, which pads after scaling, i.e. with grey.
On this deployment's crops the black edge was read as characters and exact
plates fell from 17 of 21 to 6.
"""
from __future__ import annotations

import numpy as np
import pytest

from saakshya.analytics import ocr_indian as oi
from saakshya.analytics.anpr import AnprConfig, AnprEngine
from saakshya.runtime.backend import OcrResult

needs_weights = pytest.mark.skipif(not oi.available(), reason="Indian OCR weights not installed")


def test_padding_is_grey_after_scaling_not_black() -> None:
    crop = np.full((60, 120, 3), 255, dtype=np.uint8)          # a white plate, 2:1
    x = oi.preprocess(crop)
    assert x.shape == (3, 48, 320) and x.dtype == np.float32
    assert np.allclose(x[:, :, :96], 1.0)                      # 120 * 48/60 = 96 wide
    assert np.all(x[:, :, 96:] == 0.0)                         # 0 in [-1, 1] is mid-grey


def test_a_wide_crop_is_capped_at_the_trained_width() -> None:
    x = oi.preprocess(np.zeros((20, 400, 3), dtype=np.uint8))
    assert x.shape == (3, 48, 320) and np.allclose(x, -1.0)


def test_ctc_collapses_repeats_and_drops_blanks() -> None:
    charset = ["<blank>", "A", "B", " "]
    steps = [1, 1, 0, 1, 2, 2, 0, 0, 3]                         # A A _ A B B _ _ ' '
    probs = np.full((1, len(steps), 4), 0.01, dtype=np.float32)
    for t, c in enumerate(steps):
        probs[0, t, c] = 0.9
    probs[0, 3, 1] = 0.5
    [(text, conf)] = oi.ctc_decode(probs, charset)
    assert text == "AAB "
    assert conf == pytest.approx((0.9 + 0.5 + 0.9 + 0.9) / 4)


def test_all_blank_is_an_abstention() -> None:
    probs = np.zeros((1, 5, 3), dtype=np.float32)
    probs[0, :, 0] = 1.0
    assert oi.ctc_decode(probs, ["<blank>", "A", " "]) == [("", 0.0)]


@needs_weights
def test_the_port_has_every_checkpoint_tensor_it_uses() -> None:
    from safetensors.numpy import load_file

    from saakshya.analytics import ocr_indian_net as net

    model = net.AwirosRecogniser()
    mapped = net.paddle_to_torch(load_file(str(oi.WEIGHTS)), model)
    assert len(mapped) == len([k for k in model.state_dict() if "num_batches" not in k])
    assert mapped["head.ctc_head.fc.weight"].shape == (64, 120)   # Paddle stores (120, 64)


@needs_weights
def test_the_port_reads_a_rendered_mark() -> None:
    import cv2

    img = np.full((60, 260, 3), 235, dtype=np.uint8)
    cv2.putText(img, "GJ01AB1234", (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)
    res = oi.IndianPlateOcr(device="cpu").ocr(img)
    assert res is not None and res.text == "GJ01AB1234" and res.confidence > 0.8


def test_auto_prefers_the_indian_model_when_installed(monkeypatch) -> None:
    class Fake:
        name = "fake-onnx"
    monkeypatch.delenv("SAAKSHYA_OCR", raising=False)
    monkeypatch.setattr(oi, "available", lambda: True)
    eng = AnprEngine(AnprConfig(), backend=Fake())
    assert isinstance(eng.ocr_backend, oi.IndianPlateOcr)


def test_forcing_the_indian_model_without_weights_is_an_error(monkeypatch) -> None:
    class Fake:
        name = "fake-onnx"
    monkeypatch.setenv("SAAKSHYA_OCR", "indian")
    monkeypatch.setattr(oi, "available", lambda: False)
    with pytest.raises(RuntimeError, match="fetch_indian_ocr"):
        _ = AnprEngine(AnprConfig(), backend=Fake()).ocr_backend


def test_a_frames_plates_are_read_in_one_batch() -> None:
    from types import SimpleNamespace

    class Det:
        name = "fake"

        def detect(self, img):
            return [SimpleNamespace(box=(10, 10, 110, 40), score=0.9),
                    SimpleNamespace(box=(200, 10, 300, 40), score=0.8)]

    calls: list[int] = []

    class Batch:
        name = "batch"

        def ocr_many(self, crops):
            calls.append(len(crops))
            return [OcrResult("MH02EZ1785", 0.95), None]

        def ocr(self, crop):                                   # pragma: no cover
            raise AssertionError("per-crop path used")

    eng = AnprEngine(AnprConfig(ocr_engine="onnx", tile_min_width=10_000), backend=Det())
    eng._ocr = Batch()
    reads = eng.read_frame(np.zeros((100, 400, 3), dtype=np.uint8), 1.0)
    assert calls == [2]
    assert [r.text for r in reads] == ["MH02EZ1785"] and reads[0].box[0] < 10
