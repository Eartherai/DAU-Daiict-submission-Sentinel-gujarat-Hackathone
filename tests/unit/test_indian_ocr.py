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
from saakshya.runtime import backend as rt
from saakshya.runtime.backend import OcrResult

needs_weights = pytest.mark.skipif(not oi.available(), reason="Indian OCR weights not installed")


@pytest.fixture(autouse=True)
def _own_model_registry(monkeypatch):
    """Each test starts with no model loaded and no load failure remembered."""
    monkeypatch.setattr(oi, "_MODELS", {})
    monkeypatch.setattr(oi, "_FAILED", {})


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
    monkeypatch.setattr(oi, "_shared_model", lambda device: object())
    monkeypatch.setattr(oi, "charset", lambda: ["<blank>", " "])
    eng = AnprEngine(AnprConfig(), backend=Fake())
    assert isinstance(eng.ocr_backend, oi.IndianPlateOcr)


class _FakeNet:
    """Stands in for the network: records the lock state at each Metal-side call."""

    def __init__(self, lock) -> None:
        self.lock = lock
        self.moved_under_lock: list[bool] = []
        self.ran_under_lock: list[bool] = []

    def to(self, device):
        self.moved_under_lock.append(self.lock.held)
        return self

    def __call__(self, x):
        import torch

        self.ran_under_lock.append(self.lock.held)
        probs = torch.zeros((x.shape[0], 4, 3))
        probs[:, :, 0] = 1.0                                   # all blank: an abstention
        return probs


class _RecordingLock:
    def __init__(self) -> None:
        self.held = False
        self.devices: list[str] = []

    def __call__(self, device):
        self.devices.append(device)
        return self

    def __enter__(self):
        self.held = True
        return self

    def __exit__(self, *exc):
        self.held = False
        return False


def _fake_weights(monkeypatch, lock=None, fail: Exception | None = None) -> list[str]:
    """Replace the checkpoint load; returns the list of loads it was asked for."""
    pytest.importorskip("torch")
    from saakshya.analytics import ocr_indian_net

    loads: list[str] = []
    lock = lock or _RecordingLock()

    def load(weights, device="cpu"):
        loads.append(device)
        if fail is not None:
            raise fail
        return _FakeNet(lock)

    monkeypatch.setattr(ocr_indian_net, "load", load)
    monkeypatch.setattr(oi, "charset", lambda: ["<blank>", "A", " "])
    monkeypatch.setattr(oi, "available", lambda: True)
    monkeypatch.delenv("SAAKSHYA_OCR", raising=False)
    monkeypatch.delenv("SAAKSHYA_INDIAN_OCR_DEVICE", raising=False)
    from saakshya.analytics import ocr_vision
    monkeypatch.setattr(ocr_vision, "available", lambda: False)
    return loads


def test_every_camera_shares_one_model(monkeypatch) -> None:
    # Each camera's pipeline builds its own ANPR engine. Each engine used to
    # load its own copy of the 37M-parameter network onto the GPU.
    class Fake:
        name = "fake-onnx"
    loads = _fake_weights(monkeypatch)
    monkeypatch.setattr(oi, "_device", lambda choice: "cpu")
    a = AnprEngine(AnprConfig(), backend=Fake()).ocr_backend
    b = AnprEngine(AnprConfig(), backend=Fake()).ocr_backend
    assert isinstance(a, oi.IndianPlateOcr) and isinstance(b, oi.IndianPlateOcr)
    assert a._ensure() is b._ensure()
    assert loads == ["cpu"]


def test_cameras_starting_together_load_the_model_once(monkeypatch) -> None:
    import threading

    loads = _fake_weights(monkeypatch)
    models: list[object] = []
    go = threading.Barrier(8)

    def camera() -> None:
        go.wait()
        models.append(oi.IndianPlateOcr(device="cpu")._ensure())

    threads = [threading.Thread(target=camera) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loads == ["cpu"] and len({id(m) for m in models}) == 1


def test_reading_holds_the_process_mps_lock(monkeypatch) -> None:
    # Concurrent Metal calls from camera threads corrupted PyTorch's shader
    # cache and killed the process with SIGSEGV (runtime/backend.py). The
    # detector's calls take one process-wide lock; the recogniser must too,
    # around moving the model onto the device and around every forward pass.
    assert rt.device_lock("mps") is rt._MPS_LOCK
    lock = _RecordingLock()
    _fake_weights(monkeypatch, lock=lock)
    monkeypatch.setattr(rt, "device_lock", lock)
    rec = oi.IndianPlateOcr(device="cpu")
    assert rec.ocr_many([np.zeros((30, 100, 3), dtype=np.uint8)] * 2) == [None, None]
    net = rec._ensure()
    assert net.moved_under_lock == [True]
    assert net.ran_under_lock == [True, True]            # the warm-up pass, then the read
    assert lock.devices == ["cpu", "cpu"]


def test_the_cpu_switch_pins_the_recogniser_too(monkeypatch) -> None:
    pytest.importorskip("torch")
    monkeypatch.setenv("SAAKSHYA_FORCE_CPU", "1")
    assert oi._device("auto") == "cpu"
    assert oi._device("mps") == "mps"                          # an explicit choice still wins


def test_a_model_that_cannot_load_is_said_once_and_not_retried(monkeypatch, caplog) -> None:
    # A checkpoint with a mis-shaped tensor, or a device fault while loading,
    # used to be caught as a bad crop on every frame: zero plates, a DEBUG
    # line, and the weights reloaded each time.
    from types import SimpleNamespace

    class Det:
        name = "fake-onnx"

        def detect(self, img):
            return [SimpleNamespace(box=(10, 10, 110, 40), score=0.9)]

        def ocr(self, crop):
            return OcrResult("MH02EZ1785", 0.95)

    loads = _fake_weights(monkeypatch, fail=ValueError("head.fc.weight: checkpoint (64, 99)"))
    monkeypatch.setattr(oi, "_device", lambda choice: "cpu")
    caplog.set_level("DEBUG")
    engines = [AnprEngine(AnprConfig(tile_min_width=10_000), backend=Det()) for _ in range(2)]
    frame = np.zeros((100, 400, 3), dtype=np.uint8)
    for eng in engines:
        for i in range(3):
            assert [r.text for r in eng.read_frame(frame, float(i))] == ["MH02EZ1785"]
        assert eng.ocr_backend is eng.backend                  # the next recogniser reads
        assert eng.ocr_crop_failures == 0
    assert loads == ["cpu"]
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and "did not load" in errors[0].getMessage()


def test_forcing_the_indian_model_that_cannot_load_is_an_error(monkeypatch) -> None:
    class Fake:
        name = "fake-onnx"
    _fake_weights(monkeypatch, fail=RuntimeError("MPS backend out of memory"))
    monkeypatch.setattr(oi, "_device", lambda choice: "cpu")
    monkeypatch.setenv("SAAKSHYA_OCR", "indian")
    with pytest.raises(RuntimeError, match="did not load"):
        _ = AnprEngine(AnprConfig(), backend=Fake()).ocr_backend


def test_a_bad_crop_costs_that_crop_not_the_frame() -> None:
    # A batch fails whole when one crop in it is malformed. Before batching,
    # the other plates in the frame were still read; they still are.
    from types import SimpleNamespace

    class Det:
        name = "fake"

        def detect(self, img):
            return [SimpleNamespace(box=(10, 10, 110, 40), score=0.9),
                    SimpleNamespace(box=(200, 10, 300, 40), score=0.8)]

    class Batch:
        name = "batch"

        def ocr_many(self, crops):
            raise ValueError("empty or non-colour plate crop")

        def ocr(self, crop):
            if crop[0, 0, 0] == 0:                             # the left plate is the bad one
                raise ValueError("empty or non-colour plate crop")
            return OcrResult("MH02EZ1785", 0.95)

    img = np.zeros((100, 400, 3), dtype=np.uint8)
    img[:, 150:, :] = 255
    eng = AnprEngine(AnprConfig(ocr_engine="onnx", tile_min_width=10_000), backend=Det())
    eng._ocr = Batch()
    reads = eng.read_frame(img, 1.0)
    assert [r.text for r in reads] == ["MH02EZ1785"] and reads[0].box[0] > 150
    assert eng.ocr_crop_failures == 1


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
            return [OcrResult("MH02EZ1785", 0.95, weakest=0.41), None]

        def ocr(self, crop):                                   # pragma: no cover
            raise AssertionError("per-crop path used")

    eng = AnprEngine(AnprConfig(ocr_engine="onnx", tile_min_width=10_000), backend=Det())
    eng._ocr = Batch()
    reads = eng.read_frame(np.zeros((100, 400, 3), dtype=np.uint8), 1.0)
    assert calls == [2]
    assert [r.text for r in reads] == ["MH02EZ1785"] and reads[0].box[0] < 10
    assert reads[0].weakest == 0.41


def test_a_model_that_loads_but_cannot_run_is_a_load_error(monkeypatch) -> None:
    # A device can take the weights and fail every forward pass (a CUDA build
    # without this GPU's kernels, an op Metal lacks). That used to show only
    # as zero plates on every frame.
    loads = _fake_weights(monkeypatch)

    def broken(self, x):
        raise RuntimeError("no kernel image is available for execution on the device")
    monkeypatch.setattr(_FakeNet, "__call__", broken)
    with pytest.raises(oi.LoadError, match="no kernel image"):
        oi._shared_model("cpu")
    with pytest.raises(oi.LoadError):                         # reported once, not retried
        oi._shared_model("cpu")
    assert loads == ["cpu"]


def test_an_explicit_choice_that_cannot_be_met_fails_every_time(monkeypatch) -> None:
    # It used to raise once and then read plates with the ONNX recogniser,
    # writing that recogniser into the provenance of every later event.
    class Fake:
        name = "fake-onnx"
    _fake_weights(monkeypatch, fail=OSError("weights truncated"))
    monkeypatch.setenv("SAAKSHYA_OCR", "indian")
    eng = AnprEngine(AnprConfig(), backend=Fake())
    for _ in range(3):
        with pytest.raises(RuntimeError, match="SAAKSHYA_OCR=indian"):
            _ = eng.ocr_backend


def test_every_spelling_of_the_metal_device_takes_the_lock() -> None:
    pytest.importorskip("torch")
    assert rt.device_lock("mps:0") is rt._MPS_LOCK and rt.device_lock("mps") is rt._MPS_LOCK
    assert rt.device_lock("cpu") is not rt._MPS_LOCK
    assert oi._device("mps:0") == "mps"                         # one model, not two


def test_the_parity_pin_is_the_one_the_fetch_script_checks_out() -> None:
    from pathlib import Path
    script = (Path(__file__).resolve().parents[2]
              / "tools/models/fetch_indian_ocr.sh").read_text(encoding="utf-8")
    assert f"PPOCR_COMMIT={oi.PPOCR_COMMIT}" in script


def test_a_lead_is_only_as_sure_as_its_weakest_character() -> None:
    from saakshya.analytics.anpr import PlateVoter, RawRead
    shaky = PlateVoter(AnprConfig())
    shaky.add("T1", [RawRead("KA209790", 0.87, (0, 0, 10, 5), 0.9, 0.0, weakest=0.41)])
    assert shaky.resolve("T1") is None
    sure = PlateVoter(AnprConfig())
    sure.add("T1", [RawRead("GJ05AB1234", 0.97, (0, 0, 10, 5), 0.9, 0.0, weakest=0.93)])
    lead = sure.resolve("T1")
    assert lead is not None and lead.provisional and lead.votes == 1
    legacy = PlateVoter(AnprConfig())                           # a recogniser with no weakest
    legacy.add("T1", [RawRead("GJ05AB1234", 0.9, (0, 0, 10, 5), 0.9, 0.0)])
    assert legacy.resolve("T1") is not None


def test_explicit_failure_does_not_accumulate_tracebacks(monkeypatch) -> None:
    import traceback

    monkeypatch.setenv("SAAKSHYA_OCR", "indian")
    monkeypatch.setattr(oi, "available", lambda: False)
    eng = AnprEngine(AnprConfig(), backend=object())
    depths = []
    for _ in range(20):
        with pytest.raises(RuntimeError) as caught:
            _ = eng.ocr_backend
        depths.append(len(traceback.extract_tb(caught.value.__traceback__)))
    assert len(set(depths[1:])) == 1


@pytest.mark.parametrize("vision", [False, True])
def test_bad_dictionary_uses_auto_fallback(monkeypatch, vision) -> None:
    from saakshya.analytics import ocr_vision

    monkeypatch.delenv("SAAKSHYA_OCR", raising=False)
    monkeypatch.setattr(oi, "available", lambda: True)
    monkeypatch.setattr(oi, "_shared_model", lambda device: object())

    def broken_charset():
        raise UnicodeError("invalid dictionary encoding")

    monkeypatch.setattr(oi, "charset", broken_charset)
    monkeypatch.setattr(ocr_vision, "available", lambda: vision)
    apple = object()
    monkeypatch.setattr(ocr_vision, "AppleVisionOcr", lambda: apple)
    eng = AnprEngine(AnprConfig(), backend=object())
    assert eng.ocr_backend is (apple if vision else eng.backend)
    monkeypatch.setenv("SAAKSHYA_OCR", "indian")
    eng = AnprEngine(AnprConfig(), backend=object())
    for _ in range(2):
        with pytest.raises(RuntimeError, match="dictionary"):
            _ = eng.ocr_backend


def test_corroborated_reads_do_not_use_the_weakest_character_gate() -> None:
    from saakshya.analytics.anpr import PlateVoter, RawRead

    voter = PlateVoter(AnprConfig())
    voter.add("T", [RawRead("GJ05AB1234", 0.9, (0, 0, 10, 5), 0.9, i, weakest=0.4)
                    for i in (0.0, 0.1)])
    result = voter.resolve("T")
    assert result is not None and result.votes == 2 and not result.provisional


def test_parity_inference_holds_device_lock_after_loading(monkeypatch, tmp_path) -> None:
    import importlib.util
    from pathlib import Path

    import cv2

    spec = importlib.util.spec_from_file_location(
        "ocr_compare", Path(__file__).resolve().parents[2] / "tools/bench/ocr_compare.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    lock = _RecordingLock()
    _fake_weights(monkeypatch, lock=lock)
    monkeypatch.setenv("SAAKSHYA_INDIAN_OCR_DEVICE", "cpu")
    monkeypatch.setattr(rt, "device_lock", lock)
    rec = oi.IndianPlateOcr(device="cpu")
    original_ensure = rec._ensure

    def ensure():
        assert not lock.held                 # loading itself acquires the device lock
        return original_ensure()

    monkeypatch.setattr(rec, "_ensure", ensure)
    monkeypatch.setattr(oi, "IndianPlateOcr", lambda: rec)
    probs = np.zeros((1, 4, 3), dtype=np.float32)
    probs[:, :, 0] = 1.0
    monkeypatch.setattr(oi, "paddle_reference", lambda: lambda x: probs)
    crop = tmp_path / "crop_01.png"
    assert cv2.imwrite(str(crop), np.zeros((30, 100, 3), dtype=np.uint8))
    assert bench.parity([crop]) == 0
    assert rec._model.ran_under_lock == [True, True]
