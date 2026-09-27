"""Plate OCR trained on Indian plates: Awiros-ANPR-OCR (Apache-2.0).

Neither recogniser the pipeline had was trained on Indian plates. The portable
CCT model covers about sixty regions and India is not one of them; Apple
Vision is a general text recogniser. This one is PP-OCRv5's recogniser
(SVTR_HGNet on a PPHGNetV2_B4 backbone, 37M parameters) fine-tuned on 558,767
Indian plates, single-row and dual-row, with unreadable plates trained to
abstain rather than guess. Its authors report 98.42% exact-plate accuracy on a
held-out set covering every state code. `tools/bench/ocr_compare.py` measures
it against the other recognisers on crops from this deployment's own footage.

It runs on the host, like the rest of detection and ANPR: no crop leaves the
machine. The network is restated in PyTorch (`ocr_indian_net`) and the
published weights load into it unchanged, so it runs on the GPU the detector
uses - Metal here, CUDA in deployment - at 6.6 ms a plate when a frame's
plates go as one batch, against 50 ms on one CPU core under PaddlePaddle.
The weights are fetched once by `tools/models/fetch_indian_ocr.sh` into
var/models/ (not committed); without them `available()` is False and the
pipeline keeps its previous recogniser. Weights that are present but will not
load are reported once, at ERROR, and the pipeline does the same. The process
holds one copy of the model per device, however many cameras read plates.

The CTC decode is PaddleOCR's CTCLabelDecode: best class per step, repeats
collapsed, blanks dropped, confidence the mean probability of the characters
kept.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np

from saakshya.runtime import backend as _backend
from saakshya.runtime.backend import OcrResult

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = Path(os.environ.get("SAAKSHYA_INDIAN_OCR_DIR")
                 or ROOT / "var" / "models" / "awiros-anpr-ocr")
#: PaddleOCR's model code: needed only to check the port against PaddlePaddle.
PPOCR_DIR = Path(os.environ.get("SAAKSHYA_PPOCR_DIR") or ROOT / "var" / "models" / "PaddleOCR")
WEIGHTS = MODEL_DIR / "model.safetensors"
DICT = MODEL_DIR / "en_dict.txt"

#: Input the recogniser was trained at: 48 px high, up to 320 px wide.
SHAPE = (3, 48, 320)
#: PaddleOCR's description of the network, for the parity check.
ARCHITECTURE: dict[str, Any] = {
    "model_type": "rec",
    "algorithm": "SVTR_HGNet",
    "Transform": None,
    "Backbone": {"name": "PPHGNetV2_B4", "text_rec": True},
    "Head": {
        "name": "MultiHead",
        # 62 dictionary characters + space + CTC blank; the NRTR head (unused
        # at inference) adds its own bos/eos/pad.
        "out_channels_list": {"CTCLabelDecode": 64, "NRTRLabelDecode": 67},
        "head_list": [
            {"CTCHead": {"Neck": {"name": "svtr", "dims": 120, "depth": 2, "hidden_dims": 120,
                                  "kernel_size": [1, 3], "use_guide": True},
                         "Head": {"fc_decay": 1e-05}}},
            {"NRTRHead": {"nrtr_dim": 384, "max_text_length": 25}},
        ],
    },
}


def available() -> bool:
    """The weights are on this host, and PyTorch and safetensors to run them."""
    if not (WEIGHTS.is_file() and DICT.is_file()):
        return False
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "safetensors"))


def charset() -> list[str]:
    """CTC classes: blank, the 62 dictionary characters, space."""
    chars = [ln.rstrip("\r\n") for ln in DICT.read_text(encoding="utf-8").splitlines()]
    return ["<blank>", *chars, " "]


def _device(choice: str) -> str:
    import torch

    if choice != "auto":
        # One Metal device, one cache key: "mps:0" and "mps" must not load two
        # copies of the model.
        return "mps" if choice.split(":", 1)[0] == "mps" else choice
    # The switch that pins the detector to CPU pins this model too; an explicit
    # SAAKSHYA_INDIAN_OCR_DEVICE still wins.
    if os.environ.get("SAAKSHYA_FORCE_CPU", "").strip().lower() in {"1", "true", "yes", "on"}:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class LoadError(Exception):
    """The weights are on this host but the model would not load from them.

    Deliberately not a ValueError or RuntimeError: the ANPR engine skips a
    crop on those, and a model that cannot load is not a bad crop. Caught as
    one, a mis-shaped checkpoint or a device fault became zero plates on every
    frame, logged at DEBUG, with the weights reloaded each time.
    """


#: One model per device for the whole process, not one per camera. Every
#: camera pipeline builds its own ANPR engine, and each engine used to load its
#: own copy of the 37M-parameter network - N copies on the GPU for N cameras.
_MODELS: dict[str, Any] = {}
#: A load that failed, kept so it is reported once and not retried per frame.
_FAILED: dict[str, LoadError] = {}
_LOAD_LOCK = threading.Lock()


def _shared_model(device: str) -> Any:
    """The process's one model on `device`, loaded the first time it is asked for."""
    with _LOAD_LOCK:
        if device in _MODELS:
            return _MODELS[device]
        if device in _FAILED:
            # A fresh exception each time: re-raising one instance would grow
            # its traceback on every call.
            failed = _FAILED[device]
            raise LoadError(*failed.args) from failed.__cause__
        from saakshya.analytics import ocr_indian_net

        try:
            # Build on CPU; only the move and warm-up hold the Metal lock.
            # Callers must load before taking device_lock: it is not reentrant.
            model = ocr_indian_net.load(WEIGHTS, "cpu")
            import torch
            with _backend.device_lock(device), torch.inference_mode():
                model = model.to(device)
                # One forward pass before the model is called loaded. A device
                # can accept the weights and still fail every forward (a CUDA
                # build without this GPU's kernels, an op Metal lacks); that
                # used to surface only as zero plates on every frame.
                model(torch.zeros((1, *SHAPE), device=device))
        except Exception as exc:
            err = LoadError(f"Indian plate OCR did not load from {WEIGHTS} on {device}: "
                            f"{type(exc).__name__}: {exc}")
            _FAILED[device] = err
            log.error("%s", err, exc_info=exc)
            raise err from exc
        _MODELS[device] = model
        log.info("Indian plate OCR loaded on %s", device)
        return model


def preprocess(crop_bgr: np.ndarray) -> np.ndarray:
    """PaddleOCR's `resize_norm_img`: the preprocessing the model was trained on.

    Height 48 keeping the aspect, width capped at 320, scaled to [-1, 1], and
    only then padded with zeros - so the padding is mid-grey. The inference
    script published with the weights pads with black pixels *before* scaling;
    on this deployment's crops the model read that black edge as characters
    (MH47BL0485 came back "MH47BL0485JH") and got 6 of 21 plates exactly.
    Padded as in training it got 17 of 21.
    """
    import cv2

    _, h, w = SHAPE
    ih, iw = crop_bgr.shape[:2]
    nw = max(1, min(w, int(np.ceil(h * iw / float(ih)))))
    img = cv2.resize(crop_bgr, (nw, h)).astype(np.float32) / 255.0
    out = np.zeros(SHAPE, dtype=np.float32)
    out[:, :, :nw] = ((img - 0.5) / 0.5).transpose(2, 0, 1)
    return out


def ctc_decode(probs: np.ndarray, charset: list[str]) -> list[tuple[str, float]]:
    """Greedy CTC over a (batch, steps, classes) probability array."""
    return [(t, mean) for t, mean, _ in ctc_decode_detail(probs, charset)]


def ctc_decode_detail(probs: np.ndarray,
                      charset: list[str]) -> list[tuple[str, float, float]]:
    """As `ctc_decode`, with the weakest kept character's probability too.

    The mean says how sure the recogniser is on the whole; the weakest
    character says how sure it is of the plate, since one wrong character is
    a different vehicle. On the synthetic corpus, of 1,088 valid reads (1,032
    real, 56 invented) a mean of 0.82 kept every real read and 41 invented
    ones; a weakest character of 0.82 kept 852 real and 11 invented.
    """
    out = []
    for seq in probs:
        idx = seq.argmax(axis=1)
        p = seq.max(axis=1)
        keep = np.ones(len(idx), dtype=bool)
        keep[1:] = idx[1:] != idx[:-1]
        keep &= idx != 0
        chars = [charset[i] for i in idx[keep]]
        conf = float(p[keep].mean()) if keep.any() else 0.0
        weakest = float(p[keep].min()) if keep.any() else 0.0
        out.append(("".join(chars), conf, weakest))
    return out


class IndianPlateOcr:
    """`ocr(crop) -> OcrResult | None`, the call the other recognisers answer.

    `ocr_many(crops)` reads a frame's plates in one pass; the ANPR engine uses
    it when the recogniser has it. Instances are cheap: every instance on a
    device shares that device's one model.
    """

    name = "awiros-anpr-ocr"

    def __init__(self, device: str | None = None) -> None:
        self._model: Any = None
        self._choice = device or os.environ.get("SAAKSHYA_INDIAN_OCR_DEVICE") or "auto"
        self.device = ""
        self.charset: list[str] = []

    def load(self) -> None:
        """Load now, so a model that cannot load says so here - raising
        `LoadError` - rather than on the first frame that has a plate."""
        self._ensure()

    def _ensure(self) -> Any:
        if self._model is None:
            device = _device(self._choice)
            model = _shared_model(device)
            try:
                self.charset = charset()
            except (OSError, UnicodeError) as exc:
                raise LoadError(f"Indian plate OCR dictionary did not load from {DICT}: "
                                f"{type(exc).__name__}: {exc}") from exc
            self.device, self._model = device, model
        return self._model

    def read(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        """Raw readings for a batch of BGR crops, in order."""
        return [(t, mean) for t, mean, _ in self.read_detail(crops)]

    def read_detail(self, crops: list[np.ndarray]) -> list[tuple[str, float, float]]:
        """Readings with mean and weakest-character confidence, in order."""
        import torch

        if not crops:
            return []
        x = np.stack([preprocess(c) for c in crops])
        model = self._ensure()
        # PyTorch's Metal shader cache is not thread-safe, and every camera's
        # pipeline reads plates from its own thread: the copy in, the forward
        # pass and the copy out all hold the process's one MPS lock, the lock
        # the detector's calls take (runtime/backend.py). CPU and CUDA run
        # concurrently, as the detector does there.
        with _backend.device_lock(self.device), torch.inference_mode():
            probs = model(torch.from_numpy(x).to(self.device)).float().cpu().numpy()
        return ctc_decode_detail(probs, self.charset)

    def ocr_many(self, crops: list[np.ndarray]) -> list[OcrResult | None]:
        """Each crop's reading, normalised; an abstention is None, not a guess."""
        from saakshya.analytics.plates import normalise

        for c in crops:
            if c is None or c.size == 0 or c.ndim != 3:
                raise ValueError("empty or non-colour plate crop")
        out: list[OcrResult | None] = []
        for text, conf, weakest in self.read_detail(crops):
            text = normalise(text)
            out.append(OcrResult(text=text, confidence=conf, weakest=weakest)
                       if text else None)
        return out

    def ocr(self, crop: np.ndarray) -> OcrResult | None:
        return self.ocr_many([crop])[0]


#: The PaddleOCR commit the parity check was verified against. The fetch script
#: pins its checkout to the same commit (tools/models/fetch_indian_ocr.sh).
PPOCR_COMMIT = "dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf"


def _check_ppocr_pin() -> None:
    """Refuse to import PaddleOCR's code from any checkout but the pinned one.

    The parity check imports and runs that code. A clone made by an older
    version of the fetch script sits at whatever commit upstream had then.
    """
    import subprocess

    try:
        head = subprocess.run(["git", "-C", str(PPOCR_DIR), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"cannot verify the PaddleOCR checkout at {PPOCR_DIR}: {exc}") from exc
    if head != PPOCR_COMMIT:
        raise RuntimeError(f"PaddleOCR at {PPOCR_DIR} is at {head[:12]}, not the pinned "
                           f"{PPOCR_COMMIT[:12]}; run tools/models/fetch_indian_ocr.sh --parity")


def paddle_reference() -> Any:
    """The same weights under PaddlePaddle's own network, for the parity check.

    Needs `paddlepaddle` and PaddleOCR's `ppocr` package at PPOCR_DIR; returns
    a callable (N, 3, 48, 320) float32 -> (N, 40, 64) probabilities.
    """
    import copy

    # PaddlePaddle 3 answers a later `import torch` with its own stand-in;
    # the real PyTorch has to be bound first.
    import torch  # noqa: F401

    _check_ppocr_pin()
    if str(PPOCR_DIR) not in sys.path:
        sys.path.insert(0, str(PPOCR_DIR))
    import paddle
    from ppocr.modeling.architectures import build_model
    from safetensors.numpy import load_file

    paddle.set_device("cpu")
    model = build_model(copy.deepcopy(ARCHITECTURE))
    model.eval()
    model.set_state_dict({k: paddle.to_tensor(v) for k, v in load_file(str(WEIGHTS)).items()})

    def run(x: np.ndarray) -> np.ndarray:
        with paddle.no_grad():
            p = model(paddle.to_tensor(x))
        out = p["ctc"] if isinstance(p, dict) else p
        return np.asarray(out.numpy())

    return run
