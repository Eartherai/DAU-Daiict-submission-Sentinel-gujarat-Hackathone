#!/usr/bin/env python3
"""Score the plate recognisers against plates read by eye, on the same crops.

    python tools/bench/ocr_compare.py DIR [--truth DIR/truth.json] [--json out.json]
    python tools/bench/ocr_compare.py DIR --parity   # PyTorch port vs PaddlePaddle

DIR holds plate crops named crop_NN.png, as the pipeline hands them to OCR
(after `prepare_ocr_crop`), and truth.json maps NN to the mark read by eye.
Crops with no entry are unreadable to a person and are scored separately: a
recogniser that reads nothing there is right, and one that returns a valid
mark has invented a vehicle.

For each recogniser it reports exact-plate matches, character error rate,
exact matches after the positions of an Indian mark are typed
(`plates.slot_typed`, which the pipeline applies before voting), valid marks
invented on unreadable crops, and milliseconds per crop.

`--parity` runs the Indian recogniser's weights through PaddlePaddle's own
network and through the PyTorch port the pipeline uses, on the same crops,
and reports the largest probability difference and any change in the text.
It needs `paddlepaddle` and PaddleOCR's `ppocr` package (SAAKSHYA_PPOCR_DIR).

The crops are real plates from the deployment's footage and are not
committed; keep them with the footage.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def cer(a: str, b: str) -> float:
    """Levenshtein distance over the truth's length."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(1, len(b))


def recognisers(names: list[str]) -> dict:
    out = {}
    for n in names:
        if n == "awiros":
            from saakshya.analytics import ocr_indian
            if ocr_indian.available():
                out[n] = ocr_indian.IndianPlateOcr()
        elif n == "apple-vision":
            from saakshya.analytics import ocr_vision
            if ocr_vision.available():
                out[n] = ocr_vision.AppleVisionOcr()
        elif n == "cct-onnx":
            from saakshya.models.registry import ANPR_CPU
            from saakshya.runtime.backend import BACKENDS
            out[n] = BACKENDS.get(ANPR_CPU)
    return out


def parity(crops: list[Path]) -> int:
    import cv2
    import numpy as np
    import torch

    from saakshya.analytics import ocr_indian as oi
    from saakshya.runtime.backend import device_lock

    x = np.stack([oi.preprocess(cv2.imread(str(f))) for f in crops])
    want = oi.paddle_reference()(x)
    rec = oi.IndianPlateOcr()
    model = rec._ensure()  # Warm-up takes the device lock itself; load before locking.
    with device_lock(rec.device), torch.inference_mode():
        got = model(torch.from_numpy(x).to(rec.device)).float().cpu().numpy()
    a, b = oi.ctc_decode(want, rec.charset), oi.ctc_decode(got, rec.charset)
    same = sum(p[0] == q[0] for p, q in zip(a, b, strict=True))
    diff = float(np.abs(want - got).max())
    print(f"PyTorch ({rec.device}) vs PaddlePaddle on {len(crops)} crops: "
          f"max |probability difference| {diff:.2e}, same text on {same}/{len(crops)}")
    return 0 if same == len(crops) and diff < 1e-3 else 1


def main() -> int:
    import cv2

    from saakshya.analytics.plates import normalise, slot_typed

    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--truth", type=Path)
    ap.add_argument("--only", default="awiros,apple-vision,cct-onnx")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args()
    if a.parity:
        return parity(sorted(a.dir.glob("crop_*.png")))
    truth = json.loads((a.truth or a.dir / "truth.json").read_text())
    crops = sorted(a.dir.glob("crop_*.png"))
    rows: dict[str, dict] = {}
    for name, rec in recognisers(a.only.split(",")).items():
        rec.ocr(cv2.imread(str(crops[0])))           # load / warm up, untimed
        exact = typed = invented = 0
        errs, per, dt = [], {}, 0.0
        for f in crops:
            key = str(int(f.stem.split("_")[1]))
            img = cv2.imread(str(f))
            t = time.perf_counter()
            res = rec.ocr(img)
            dt += time.perf_counter() - t
            got = normalise(res.text) if res else ""
            st = slot_typed(got) if got else None
            final = st.canonical if st is not None and st.valid else got
            per[key] = {"raw": got, "typed": final,
                        "conf": round(res.confidence, 3) if res else None}
            if key in truth:
                exact += got == truth[key]
                typed += final == truth[key]
                errs.append(cer(got, truth[key]))
            elif st is not None and st.valid:
                invented += 1
        n = len(truth)
        rows[name] = {"exact": exact, "exact_after_typing": typed, "labelled": n,
                      "cer": round(sum(errs) / max(1, len(errs)), 3),
                      "invented_on_unreadable": invented,
                      "unreadable": len(crops) - n,
                      "ms_per_crop": round(1000 * dt / len(crops), 1), "reads": per}
    w = max(len(k) for k in rows) if rows else 10
    print(f"{'recogniser':<{w}}  exact   typed   CER    invented  ms/crop")
    for k, r in rows.items():
        n = r["labelled"]
        print(f"{k:<{w}}  {r['exact']:>2}/{n:<3} {r['exact_after_typing']:>2}/{n:<3}"
              f" {r['cer']:.3f}  {r['invented_on_unreadable']}/{r['unreadable']}"
              f"       {r['ms_per_crop']}")
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
