"""Per-observation quality.

Camera-level capability answers "can this camera generally do ANPR?". It is the
wrong granularity for ranking, because a grade-C camera still produces occasional
excellent crops and a grade-A camera produces poor ones at the edge of frame.
Scoring both alike throws away the information that decides a close call.

So quality is measured **per observation**, from the pixels that produced it.
Everything here is a cheap classical measure — no model, no training, nothing
that can suffer domain shift. That matters: this is the term that discounts a
model score, so it must be more reliable than the thing it is discounting.

The dominant term for ANPR viability is **plate pixel width**. It is not a
heuristic preference: character legibility is bounded by how many pixels the
characters occupy, and no OCR model recovers information that is not there.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Below this, a 10-character Indian mark cannot be read reliably by any model.
#: Roughly 6 px per character plus separators.
PLATE_WIDTH_UNUSABLE = 60.0
#: Above this, plate width stops being the binding constraint.
PLATE_WIDTH_GOOD = 140.0


@dataclass
class ObservationQuality:
    """0..1 per factor. `score` is the aggregate actually used for weighting."""

    score: float
    sharpness: float
    #: Exposure *quality*, peaking at mid-grey and falling off towards both
    #: crushed blacks and blown highlights. It is not brightness, and using it
    #: as brightness reads a well-exposed night scene as daylight.
    luminance: float
    #: Mean luma of the crop, 0..1. This is the brightness measurement, kept
    #: separate because the two answer different questions and conflating them
    #: silently mislabelled every observation's illumination band.
    mean_luma: float
    #: Mean chroma, 0..1. A camera in infrared night mode delivers a colour
    #: frame with no colour in it — every channel carries the same value. Found
    #: on the live Gujarat grid, where several cameras switch to IR overnight.
    #: Reading a vehicle colour from such a frame produces a confident answer
    #: that is pure fabrication, so the estimator has to be able to tell.
    mean_chroma: float
    contrast: float
    plate_pixel_width: float | None = None
    plate_legibility: float | None = None
    vehicle_pixel_area: float | None = None
    factors: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.score >= 0.75:
            return "HIGH"
        if self.score >= 0.5:
            return "MEDIUM"
        if self.score >= 0.25:
            return "LOW"
        return "VERY_LOW"

    def explain(self) -> str:
        if self.reasons:
            return f"{self.band} ({self.score:.2f}) — " + "; ".join(self.reasons)
        return f"{self.band} ({self.score:.2f})"


#: Below this mean channel spread a frame carries no usable colour. Measured on
#: the live grid: IR-mode cameras sit near 0.005-0.02, colour cameras at night
#: are an order of magnitude above it.
MONOCHROME_CHROMA = 0.04


def _luma(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img.astype(np.float32)
    # BT.601 on BGR.
    return (img[:, :, 0].astype(np.float32) * 0.114
            + img[:, :, 1].astype(np.float32) * 0.587
            + img[:, :, 2].astype(np.float32) * 0.299)


def _laplacian_var(g: np.ndarray) -> float:
    """Variance of the Laplacian — the standard sharpness proxy.

    Computed with numpy rather than cv2 so this module stays out of the
    PyAV/OpenCV native-library conflict.
    """
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    lap = (-4.0 * g[1:-1, 1:-1]
           + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def _crop(img: np.ndarray, box: tuple[float, float, float, float] | None) -> np.ndarray:
    if box is None:
        return img
    h, w = img.shape[:2]
    x1, y1, x2, y2 = (int(max(0, box[0])), int(max(0, box[1])),
                      int(min(w, box[2])), int(min(h, box[3])))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return img
    return img[y1:y2, x1:x2]


def assess(image: np.ndarray,
           plate_box: tuple[float, float, float, float] | None = None,
           vehicle_box: tuple[float, float, float, float] | None = None
           ) -> ObservationQuality:
    """Measure the quality of one observation from its own pixels."""
    region = _crop(image, vehicle_box if vehicle_box else plate_box)
    g = _luma(region)

    # Sharpness — normalised so it is comparable across resolutions.
    lv = _laplacian_var(g)
    sharpness = float(np.clip(lv / 400.0, 0.0, 1.0))

    # Luminance — penalise both crushed blacks and blown highlights.
    mean_l = float(g.mean()) / 255.0
    luminance = float(np.clip(1.0 - abs(mean_l - 0.45) / 0.45, 0.0, 1.0))

    # Contrast — a flat crop carries little information regardless of sharpness.
    contrast = float(np.clip((g.max() - g.min()) / 255.0, 0.0, 1.0))

    # Chroma — how far the channels diverge from each other. Near zero means a
    # monochrome or IR frame, whatever its brightness.
    if region.ndim == 3 and region.shape[2] >= 3:
        r = region.astype(np.float32)
        spread = r.max(axis=2) - r.min(axis=2)
        mean_chroma = float(spread.mean()) / 255.0
    else:
        mean_chroma = 0.0

    factors = {"sharpness": sharpness, "luminance": luminance,
               "mean_luma": mean_l, "mean_chroma": mean_chroma,
               "contrast": contrast}
    reasons: list[str] = []

    plate_w: float | None = None
    plate_legibility: float | None = None
    if plate_box is not None:
        plate_w = float(plate_box[2] - plate_box[0])
        plate_legibility = float(np.clip(
            (plate_w - PLATE_WIDTH_UNUSABLE) / (PLATE_WIDTH_GOOD - PLATE_WIDTH_UNUSABLE),
            0.0, 1.0))
        factors["plate_legibility"] = plate_legibility
        if plate_w < PLATE_WIDTH_UNUSABLE:
            reasons.append(f"plate only {plate_w:.0f} px wide — below readable width")

    if mean_chroma < MONOCHROME_CHROMA:
        reasons.append("monochrome or infrared frame — no colour to read")
    if sharpness < 0.25:
        reasons.append("soft focus or motion blur")
    if mean_l < 0.20:
        reasons.append("underexposed")
    elif mean_l > 0.80:
        reasons.append("overexposed or glare")
    if contrast < 0.30:
        reasons.append("low contrast")

    vehicle_area = None
    if vehicle_box is not None:
        vehicle_area = float((vehicle_box[2] - vehicle_box[0])
                             * (vehicle_box[3] - vehicle_box[1]))

    # Weighted aggregate. Plate legibility dominates when a plate is present,
    # because it is the binding constraint on the only signal that identifies a
    # vehicle uniquely.
    if plate_legibility is not None:
        score = (0.45 * plate_legibility + 0.25 * sharpness
                 + 0.15 * luminance + 0.15 * contrast)
    else:
        score = 0.50 * sharpness + 0.25 * luminance + 0.25 * contrast

    return ObservationQuality(
        score=float(np.clip(score, 0.0, 1.0)),
        sharpness=sharpness, luminance=luminance, mean_luma=mean_l,
        mean_chroma=mean_chroma, contrast=contrast,
        plate_pixel_width=plate_w, plate_legibility=plate_legibility,
        vehicle_pixel_area=vehicle_area, factors=factors, reasons=reasons,
    )
