"""Vehicle attributes — colour and size class.

Why classical measurement instead of a learned embedding
--------------------------------------------------------
We measured a DINOv2-base appearance embedding on our own corpus before adopting
it. Result, on ground-truth vehicle crops:

    same vehicle, different cameras   cosine 0.400 (min)
    different vehicles                cosine 0.941 (max)
    margin                            -0.541

The embedding scored the *decoy* white car at 0.941 against the target while
scoring the target against itself at 0.412. It was encoding scene and
illumination, not vehicle identity. Per-crop illumination normalisation made it
slightly worse (-0.581), so this is not a preprocessing problem.

Classical colour on the same crops scored 7/8. The single miss is the degraded
Panchayat camera returning "grey" for a white car — which is the honest answer
for that camera and is itself signal, because it is accompanied by a low quality
score rather than a confident wrong colour.

So attributes are the primary appearance signal and the embedding is not shipped
as an identity signal. This is a measured decision, not a preference, and it must
be re-measured on government footage where real vehicles carry far more
distinguishing texture than our synthetic corpus does.

Everything here is deliberately explainable: an investigator can be told "white,
car-sized, matched on colour" and can disagree with a specific claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Below this saturation the pixel is achromatic and only lightness matters.
ACHROMATIC_SAT = 0.18
#: Pixels darker than this are windows, tyres and shadow, not body colour.
DARK_FLOOR = 35.0

COLOUR_NEIGHBOURS: dict[str, set[str]] = {
    # Confusions that are *expected* on degraded cameras, used to soften scoring
    # rather than to assert equivalence.
    "white": {"grey", "silver"},
    "grey": {"white", "silver", "black"},
    "silver": {"white", "grey"},
    "black": {"grey"},
    "red": {"orange", "maroon"},
    "orange": {"red", "yellow"},
    "yellow": {"orange"},
    "blue": {"navy"},
    "green": set(),
}


@dataclass
class VehicleAttributes:
    colour: str | None = None
    colour_confidence: float = 0.0
    colour_bgr: tuple[float, float, float] | None = None
    size_class: str | None = None          # motorcycle | car | van | truck_bus
    aspect_ratio: float | None = None
    reasons: list[str] = field(default_factory=list)

    def explain(self) -> str:
        bits = []
        if self.colour:
            bits.append(f"colour {self.colour} ({self.colour_confidence:.2f})")
        if self.size_class:
            bits.append(f"size class {self.size_class}")
        return ", ".join(bits) or "no attributes recovered"


#: If fewer than this fraction of sampled pixels are lit, we are looking mostly
#: at glass, tyres or shadow rather than bodywork. The honest answer is then "I
#: do not know", not a confident "black".
MIN_LIT_FRACTION = 0.25

#: Below this confidence we decline to name a colour at all.
#:
#: Measured case: an over-merged motion box covering a bus *and* surrounding road
#: sampled 85% lit pixels whose median was road grey, yielding "black" for an
#: orange vehicle — at confidence 0.18. The estimator already knew it did not
#: know; it simply was not asked. A wrong colour propagates into retrieval and
#: outranks correct candidates, whereas an absent one merely carries no weight.
MIN_COLOUR_CONFIDENCE = 0.30


def _body_pixels(crop: np.ndarray) -> tuple[np.ndarray, float]:
    """Central band of the vehicle excluding dark regions, plus the lit fraction.

    The band avoids the roofline and wheel arches; the dark filter removes
    windscreen and tyres, which otherwise drag every vehicle toward black.

    The returned fraction is what lets the caller *abstain*. A crop that is
    mostly dark is usually a mis-framed box — a measured failure mode here was a
    box covering only a bus's cabin, which reported a confident "black" for an
    orange vehicle. Reporting no colour is strictly better than that.
    """
    h, w = crop.shape[:2]
    band = crop[int(h * 0.15):max(int(h * 0.60), int(h * 0.15) + 1),
                int(w * 0.10):max(int(w * 0.90), int(w * 0.10) + 1)]
    px = band.reshape(-1, 3).astype(np.float32)
    if px.size == 0:
        px = crop.reshape(-1, 3).astype(np.float32)
    lit = px[px.mean(axis=1) > DARK_FLOOR]
    frac = len(lit) / max(1, len(px))
    return (lit if len(lit) >= 20 else px), float(frac)


def classify_colour(bgr: np.ndarray) -> tuple[str, float]:
    """Map a median BGR to a colour name plus a confidence.

    Confidence reflects how far the pixel is from a decision boundary, so a
    washed-out or near-achromatic body reports low confidence rather than an
    arbitrary label.
    """
    b, g, r = float(bgr[0]), float(bgr[1]), float(bgr[2])
    mx, mn = max(b, g, r), min(b, g, r)
    sat = (mx - mn) / (mx + 1e-6)
    val = mx / 255.0

    if sat < ACHROMATIC_SAT:
        # Distance from the saturation boundary, scaled: a truly flat grey is
        # confident; something near the boundary is not.
        conf = float(np.clip((ACHROMATIC_SAT - sat) / ACHROMATIC_SAT, 0.0, 1.0))
        if val > 0.62:
            return "white", conf
        if val > 0.30:
            return "grey", conf
        return "black", conf

    conf = float(np.clip((sat - ACHROMATIC_SAT) / 0.35, 0.0, 1.0))
    if r >= g and r >= b:
        return ("red", conf) if (r - g) > 40 else ("orange", conf * 0.8)
    if g >= r and g >= b:
        return "green", conf
    if b >= r and b >= g:
        return "blue", conf
    return "yellow", conf * 0.7


#: Geometry of an Indian single-row plate relative to a car, used to recover a
#: body region when only the plate was detected. A plate is ~500 mm wide on a
#: ~1800 mm wide vehicle, and sits low and central.
PLATE_TO_BODY_WIDTH = 3.6
BODY_ASPECT = 1.9          # typical car body w/h in image space
PLATE_HEIGHT_FRACTION = 0.82   # how far down the body the plate sits


def implied_vehicle_box(plate_box: tuple[float, float, float, float],
                        frame_shape: tuple[int, int]
                        ) -> tuple[float, float, float, float]:
    """Estimate the vehicle body region from a detected plate.

    Needed because on cameras where the vehicle detector is unusable, tracks are
    anchored on plate detections — and reading colour or size from a plate crop
    yields the colour of the plate and the aspect of a rectangle, not of a
    vehicle. Measured symptom before this existed: every observation reported
    colour "black" and a random size class.

    This is an estimate and is treated as one: it feeds attributes, never
    geometry that anything depends on being exact.
    """
    px1, _py1, px2, py2 = plate_box
    pw = max(1.0, px2 - px1)
    cx = (px1 + px2) / 2.0

    bw = pw * PLATE_TO_BODY_WIDTH
    bh = bw / BODY_ASPECT
    # The plate sits low on the body, so the body extends upward from it.
    body_bottom = py2 + bh * (1.0 - PLATE_HEIGHT_FRACTION)
    body_top = body_bottom - bh

    h, w = frame_shape[:2]
    return (max(0.0, cx - bw / 2.0), max(0.0, body_top),
            min(float(w), cx + bw / 2.0), min(float(h), body_bottom))


def classify_size(box: tuple[float, float, float, float],
                  frame_shape: tuple[int, int]) -> tuple[str, float]:
    """Coarse size class from box geometry.

    Deliberately coarse. Without camera calibration, apparent size confounds
    vehicle size with distance, so anything finer than these four buckets would
    be false precision. Reported as a *class*, never as a make or model.
    """
    x1, y1, x2, y2 = box
    w, h = max(1.0, x2 - x1), max(1.0, y2 - y1)
    aspect = w / h
    frame_h, frame_w = frame_shape[:2]
    rel_area = (w * h) / float(frame_w * frame_h)

    if aspect < 1.0 and rel_area < 0.02:
        return "motorcycle", aspect
    if aspect > 2.6 or rel_area > 0.18:
        return "truck_bus", aspect
    if aspect > 2.0:
        return "van", aspect
    return "car", aspect


def extract(image: np.ndarray, box: tuple[float, float, float, float]
            ) -> VehicleAttributes:
    """Attributes for one vehicle box in one frame."""
    h, w = image.shape[:2]
    x1, y1 = int(max(0, box[0])), int(max(0, box[1]))
    x2, y2 = int(min(w, box[2])), int(min(h, box[3]))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return VehicleAttributes(reasons=["box too small for attribute extraction"])

    crop = image[y1:y2, x1:x2]
    px, lit_fraction = _body_pixels(crop)
    med = np.median(px, axis=0)
    colour, conf = classify_colour(med)
    size_class, aspect = classify_size((x1, y1, x2, y2), image.shape)

    reasons: list[str] = []
    if lit_fraction < MIN_LIT_FRACTION:
        # Abstain. A wrong colour propagates into retrieval and is far worse
        # than an absent one, which simply carries no weight.
        return VehicleAttributes(
            colour=None, colour_confidence=0.0,
            colour_bgr=(float(med[0]), float(med[1]), float(med[2])),
            size_class=size_class, aspect_ratio=float(aspect),
            reasons=[f"only {lit_fraction:.0%} of the sampled region is lit "
                     f"bodywork — declining to assert a colour"],
        )
    # Scale confidence by how much bodywork we actually saw.
    conf *= float(np.clip(lit_fraction / 0.6, 0.3, 1.0))
    if conf < MIN_COLOUR_CONFIDENCE:
        return VehicleAttributes(
            colour=None, colour_confidence=float(conf),
            colour_bgr=(float(med[0]), float(med[1]), float(med[2])),
            size_class=size_class, aspect_ratio=float(aspect),
            reasons=[f"colour confidence {conf:.2f} below the "
                     f"{MIN_COLOUR_CONFIDENCE:.2f} floor — declining to assert "
                     f"a colour rather than risk a wrong one"],
        )
    if float(px.mean()) < 60:
        reasons.append("dark crop; colour may be understated")

    return VehicleAttributes(
        colour=colour, colour_confidence=conf,
        colour_bgr=(float(med[0]), float(med[1]), float(med[2])),
        size_class=size_class, aspect_ratio=float(aspect), reasons=reasons,
    )


def colour_agreement(a: str | None, b: str | None) -> float:
    """1.0 exact, 0.5 an expected confusion, 0.0 incompatible.

    The middle value matters: on a degraded camera a white car legitimately
    reads as grey, and scoring that as a mismatch would penalise exactly the
    observations the appearance path exists to recover.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if b in COLOUR_NEIGHBOURS.get(a, set()) or a in COLOUR_NEIGHBOURS.get(b, set()):
        return 0.5
    return 0.0


def size_agreement(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    adjacent = {("car", "van"), ("van", "car"),
                ("van", "truck_bus"), ("truck_bus", "van")}
    return 0.5 if (a, b) in adjacent else 0.0
