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
pipeline keeps its previous recogniser.

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
        return choice
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


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
    out = []
    for seq in probs:
        idx = seq.argmax(axis=1)
        p = seq.max(axis=1)
        keep = np.ones(len(idx), dtype=bool)
        keep[1:] = idx[1:] != idx[:-1]
        keep &= idx != 0
        chars = [charset[i] for i in idx[keep]]
        conf = float(p[keep].mean()) if keep.any() else 0.0
        out.append(("".join(chars), conf))
    return out


class IndianPlateOcr:
    """`ocr(crop) -> OcrResult | None`, the call the other recognisers answer.

    `ocr_many(crops)` reads a frame's plates in one pass; the ANPR engine uses
    it when the recogniser has it.
    """

    name = "awiros-anpr-ocr"

    def __init__(self, device: str | None = None) -> None:
        self._lock = threading.Lock()
        self._model: Any = None
        self._choice = device or os.environ.get("SAAKSHYA_INDIAN_OCR_DEVICE") or "auto"
        self.device = ""
        self.charset: list[str] = []

    def _ensure(self) -> Any:
        if self._model is None:
            from saakshya.analytics import ocr_indian_net

            self.device = _device(self._choice)
            self._model = ocr_indian_net.load(WEIGHTS, self.device)
            self.charset = charset()
            log.info("Indian plate OCR loaded on %s", self.device)
        return self._model

    def read(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        """Raw readings for a batch of BGR crops, in order."""
        import torch

        if not crops:
            return []
        x = np.stack([preprocess(c) for c in crops])
        with self._lock:
            model = self._ensure()
            with torch.inference_mode():
                probs = model(torch.from_numpy(x).to(self.device)).float().cpu().numpy()
        return ctc_decode(probs, self.charset)

    def ocr_many(self, crops: list[np.ndarray]) -> list[OcrResult | None]:
        """Each crop's reading, normalised; an abstention is None, not a guess."""
        from saakshya.analytics.plates import normalise

        for c in crops:
            if c is None or c.size == 0 or c.ndim != 3:
                raise ValueError("empty or non-colour plate crop")
        out: list[OcrResult | None] = []
        for text, conf in self.read(crops):
            text = normalise(text)
            out.append(OcrResult(text=text, confidence=conf) if text else None)
        return out

    def ocr(self, crop: np.ndarray) -> OcrResult | None:
        return self.ocr_many([crop])[0]


def paddle_reference() -> Any:
    """The same weights under PaddlePaddle's own network, for the parity check.

    Needs `paddlepaddle` and PaddleOCR's `ppocr` package at PPOCR_DIR; returns
    a callable (N, 3, 48, 320) float32 -> (N, 40, 64) probabilities.
    """
    import copy

    # PaddlePaddle 3 answers a later `import torch` with its own stand-in;
    # the real PyTorch has to be bound first.
    import torch  # noqa: F401

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
        return (p.get("ctc") if isinstance(p, dict) else p).numpy()

    return run
