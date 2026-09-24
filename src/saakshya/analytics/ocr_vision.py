"""Plate OCR on Apple's on-device text recogniser, where the hardware has it.

The portable OCR model (CCT, ONNX) was trained on plates from about sixty
regions, and India is not one of them. Scored against 21 plate crops read by
eye from the Mumbai signal-queue footage it read 1 exactly, with 49% of
characters wrong. Apple Vision's recogniser, on the same crops, got 25% of
characters wrong - and most of its errors are the O/0 and 8/B confusions that
the positions of an Indian mark resolve (`plates.slot_typed`).

It runs on the machine's Neural Engine and GPU; no pixel leaves the host, so
the rule that detection and ANPR stay on the deployment's own hardware holds.
It exists only on macOS, which makes it the development hardware's OCR, not
the target's: on a Linux GPU server the ONNX model remains the fallback, and
an Indian-trained recogniser is what that hardware should carry.

The recogniser is a small Swift program (`tools/ocr/vision_ocr.swift`), built
on first use with the system compiler and kept running: one process, crops
passed by path, one JSON line back per crop.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

import numpy as np

from saakshya.runtime.backend import OcrResult

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "tools" / "ocr" / "vision_ocr.swift"
BINARY = ROOT / "var" / "run" / "bin" / "vision_ocr"


def available() -> bool:
    """macOS with the recogniser built, or buildable here."""
    if sys.platform != "darwin":
        return False
    if BINARY.is_file():
        return True
    return SOURCE.is_file() and any(
        (Path(d) / "swiftc").is_file() for d in os.environ.get("PATH", "").split(os.pathsep))


def _build() -> None:
    BINARY.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["swiftc", "-O", str(SOURCE), "-o", str(BINARY)], check=True,
                   capture_output=True, timeout=300)


class AppleVisionOcr:
    """`ocr(crop) -> OcrResult | None`, the same call the ONNX backend answers."""

    name = "apple-vision"

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._tmp = Path(tempfile.mkdtemp(prefix="saakshya-ocr-"))
        self._n = 0

    def _ensure(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        if not BINARY.is_file() or (SOURCE.is_file()
                                    and SOURCE.stat().st_mtime > BINARY.stat().st_mtime):
            _build()
        self._proc = subprocess.Popen([str(BINARY)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True, bufsize=1)
        return self._proc

    def candidates(self, crop: np.ndarray) -> list[dict[str, Any]]:
        from PIL import Image

        with self._lock:
            self._n += 1
            path = self._tmp / f"c{self._n % 64}.png"
            Image.fromarray(np.ascontiguousarray(crop[:, :, ::-1])).save(path)
            proc = self._ensure()
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(f"{path}\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
        try:
            return list(json.loads(line).get("candidates") or [])
        except (json.JSONDecodeError, AttributeError):
            return []

    def ocr(self, crop: np.ndarray) -> OcrResult | None:
        """The recogniser's best reading that is an Indian mark, else its best.

        Vision returns up to five readings per line of text. Choosing the most
        confident one that is a valid mark (directly, or with the positions
        typed) is choosing among the recogniser's own answers - the vote across
        frames, unchanged, still decides what is published.
        """
        from saakshya.analytics.plates import normalise, slot_typed

        cands = self.candidates(crop)
        if not cands:
            return None
        scored = []
        for c in cands:
            text = normalise(str(c.get("text", "")))
            if not text:
                continue
            conf = float(c.get("confidence") or 0.0)
            # The IND strip at the left of a plate is read as stray letters
            # ("FMHO2F65664"). Up to two characters may be left out at the left
            # only, when what remains is a whole valid mark of nine or more.
            # Never at the right: "MH02F13523" less its last digit is the valid
            # but wrong MH02F1352, so trimming there manufactures a plate.
            best_cut = None
            for lead in range(0, 3):
                part = text[lead:]
                if len(part) >= 9 and slot_typed(part).valid:
                    best_cut = (lead, part)
                    break
            if best_cut is not None:
                scored.append((True, -best_cut[0], conf, best_cut[1]))
            else:
                scored.append((False, 0, conf, text))
        if not scored:
            return None
        scored.sort(key=lambda s: (s[0], s[1], s[2]), reverse=True)
        _, _, conf, text = scored[0]
        return OcrResult(text=text, confidence=conf)

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            self._proc = None
