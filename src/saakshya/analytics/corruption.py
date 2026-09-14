"""Detect a stream that decodes successfully into garbage.

cam21 delivered 1,628 frames over fourteen minutes, 777 of them analysed, and
produced **zero** observations. The decoder reported no errors at all. The frames
were badly corrupted: heavy 16-pixel blocking, smeared luminance, and rows of
green macroblocks where chroma had been lost.

This is ordinary H.264 behaviour on a lossy link. When reference frames go
missing the decoder *conceals* rather than failing — it emits a plausible-shaped
picture built from stale data. Every counter the pipeline had said the camera was
healthy: frames arrived, decode succeeded, no warnings. Only the absence of
detections hinted at it, and "no detections" is also what an empty road looks
like.

That ambiguity is the problem worth solving. An investigator told a camera saw
no vehicles will conclude the road was clear. The truth was that the camera could
not be seen through at all, and those are opposite findings.

Two signals, both cheap and both computed from the frame itself:

  * **blockiness** — corruption from concealment lands on the codec's 16-pixel
    macroblock grid, so discontinuity at multiples of 16 rises far above
    discontinuity elsewhere. A clean frame has no reason to prefer that grid.
  * **chroma loss** — concealment frequently drops chroma planes for whole
    macroblock rows, leaving saturated green or magenta bands that no street
    scene produces.

Neither is a certainty on its own, and neither is treated as one.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: The macroblock grid H.264 and H.265 both use.
MACROBLOCK = 16

#: Ratio of on-grid to off-grid discontinuity above which a frame **carries
#: macroblock artefacts**. Note carefully what that does and does not mean: a
#: frame can carry visible artefacts on one vehicle and still be a good picture
#: of a junction. Per-frame, this is a symptom, not a verdict.
BLOCKINESS_SUSPECT = 1.45

#: Fraction of rows carrying implausible saturated chroma before it counts.
CHROMA_BAND_SUSPECT = 0.06


@dataclass(frozen=True)
class Corruption:
    blockiness: float
    chroma_band_fraction: float
    suspect: bool
    reason: str

    def to_dict(self) -> dict[str, float | bool | str]:
        return {"blockiness": round(self.blockiness, 3),
                "chroma_band_fraction": round(self.chroma_band_fraction, 4),
                "suspect": self.suspect, "reason": self.reason}


#: A ratio is meaningless when both sides are near zero. Two guards, both found
#: by tests on synthetic frames before they could mislead on a real one:
#:
#:  * a smooth gradient quantised to 8 bits has stair-steps but almost no
#:    off-grid variation, and measured **4.01** — a flat wall or a heavily
#:    denoised stream would have been reported as corrupt;
#:  * perfectly constant blocks have *zero* off-grid variation, so the guard
#:    returned 1.0 and read as clean — the very artefact being looked for.
#:
#: So the denominator has a floor, and a frame must carry real discontinuity on
#: the grid before any ratio is believed. A picture with no edges anywhere is
#: not corrupt; it is empty, and that is a different finding.
_OFF_GRID_FLOOR = 0.35
_MIN_ON_GRID = 1.5
#: Grey levels by which on-grid discontinuity must exceed off-grid before any
#: ratio is believed. Below this the artefact is invisible whatever the ratio.
_MIN_ABSOLUTE_GAP = 1.5


def _grid_ratio(g: np.ndarray) -> float:
    """On-grid discontinuity over off-grid discontinuity, both axes."""
    if g.shape[0] < MACROBLOCK * 3 or g.shape[1] < MACROBLOCK * 3:
        return 1.0
    d_col = np.abs(np.diff(g.astype(np.float32), axis=1))
    d_row = np.abs(np.diff(g.astype(np.float32), axis=0))

    on_cols = d_col[:, MACROBLOCK - 1::MACROBLOCK]
    on_rows = d_row[MACROBLOCK - 1::MACROBLOCK, :]
    mask_c = np.ones(d_col.shape[1], bool)
    mask_c[MACROBLOCK - 1::MACROBLOCK] = False
    mask_r = np.ones(d_row.shape[0], bool)
    mask_r[MACROBLOCK - 1::MACROBLOCK] = False

    on = float(on_cols.mean() + on_rows.mean()) / 2.0
    off = float(d_col[:, mask_c].mean() + d_row[mask_r, :].mean()) / 2.0
    if on < _MIN_ON_GRID:
        return 1.0                      # no edges on the grid: nothing to judge
    # A ratio alone is not enough. Measured on this grid:
    #
    #   corrupted cam21   on 4.11  off 1.85  gap 2.26  ratio 2.22
    #   clean     cam16   on 1.64  off 1.23  gap 0.42  ratio 1.34
    #   clean     cam04   on 5.83  off 4.92  gap 0.91  ratio 1.19
    #
    # A near-noiseless frame can show a large ratio over an absolute difference
    # of a third of one grey level, which is invisible and means nothing. Both
    # tests must pass, so the finding rests on a difference a person could see.
    if (on - off) < _MIN_ABSOLUTE_GAP:
        return 1.0
    return on / max(off, _OFF_GRID_FLOOR)


def _chroma_bands(image: np.ndarray) -> float:
    """Fraction of rows dominated by an implausible saturated hue.

    Concealment drops chroma for whole macroblock rows, which shows as bands of
    saturated green or magenta. A real scene has green — foliage, signage — but
    not as a band spanning the frame with almost no luminance variation.
    """
    if image.ndim != 3 or image.shape[2] != 3:
        return 0.0
    f = image.astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    # Green far above both neighbours, or magenta: the two concealment leaves.
    green = (g - np.maximum(b, r)) > 60
    magenta = (np.minimum(b, r) - g) > 60
    per_row = (green | magenta).mean(axis=1)
    # Flatness is a property of the *luminance* across the row, not of the
    # spread between channels. Measuring `std` over both axes at once meant a
    # uniformly saturated green row — precisely the artefact — scored a high
    # deviation and was rejected as "detailed", so the check could never fire
    # on the thing it was written for.
    luma = 0.114 * b + 0.587 * g + 0.299 * r
    flat = luma.std(axis=1) < 22
    return float((per_row > 0.5)[flat].sum() / max(1, image.shape[0]))


#: Side of the sample taken from a large frame. Measured on real frames from
#: this grid: a full 1080p assessment costs 25 ms, which at two analysed frames
#: per second across thirty cameras is 1.5 seconds of CPU per second — more than
#: the detector itself. A 512px sample costs 3 ms and preserves the signal
#: (corrupted cam21 2.22 against clean cam16 1.34).
SAMPLE = 512


def _sample(image: np.ndarray) -> np.ndarray:
    """A centre crop **aligned to the macroblock grid**.

    Alignment is the whole trick. Downscaling instead of cropping was tried
    first and destroyed the signal outright — corrupted cam21 measured 1.42 and
    read as clean — because scaling moves the 16-pixel discontinuities off the
    grid the detector looks on. A crop keeps them, but only if its origin is
    itself a multiple of 16; otherwise the sample runs a fixed phase off and
    measures the wrong columns.
    """
    h, w = image.shape[:2]
    if h <= SAMPLE or w <= SAMPLE:
        return image
    y = ((h - SAMPLE) // 2) // MACROBLOCK * MACROBLOCK
    x = ((w - SAMPLE) // 2) // MACROBLOCK * MACROBLOCK
    return image[y:y + SAMPLE, x:x + SAMPLE]


def assess_corruption(image: np.ndarray, *, full: bool = False) -> Corruption:
    """Is this frame plausibly what the camera saw, or decoder concealment?

    Samples a grid-aligned crop by default; `full=True` assesses the whole
    frame, which is eight times the cost and is worth it only when a decision
    rests on one frame rather than on a rate across many.
    """
    if not full:
        image = _sample(image)
    if image.ndim == 3:
        g = (0.114 * image[..., 0] + 0.587 * image[..., 1]
             + 0.299 * image[..., 2]).astype(np.float32)
    else:
        g = image.astype(np.float32)

    blockiness = _grid_ratio(g)
    bands = _chroma_bands(image)

    reasons = []
    if blockiness >= BLOCKINESS_SUSPECT:
        reasons.append(f"macroblock artefacts present: discontinuity on the "
                       f"{MACROBLOCK}px grid is {blockiness:.2f}x the "
                       f"discontinuity elsewhere")
    if bands >= CHROMA_BAND_SUSPECT:
        reasons.append(f"{bands:.0%} of rows carry saturated chroma bands with "
                       "no scene detail")
    return Corruption(
        blockiness=blockiness, chroma_band_fraction=bands,
        suspect=bool(reasons),
        reason=("; ".join(reasons) if reasons
                else "no macroblock or chroma artefact detected"))


#: Rate of flagged frames at which a stream is no longer describing the road.
#: cam21 sat at 97%; cam16, which produced 375 usable observations in the same
#: run, sat at 27%. The bar is set with margin on both sides of that gap.
STREAM_CORRUPT_RATE = 0.80
STREAM_DEGRADED_RATE = 0.35
#: Below this many samples, a rate is not evidence. The first live run declared
#: cam16 corrupt on 10 of 15 samples — an unlucky draw from a 27% rate, and a
#: working camera reported as broken.
STREAM_MIN_SAMPLES = 25


def stream_verdict(checked: int, suspect: int) -> tuple[str, str]:
    """Turn a rate of flagged frames into a verdict about the stream.

    Returns (state, reason) where state is CORRUPT, DEGRADED, OK or UNKNOWN.
    UNKNOWN is returned for a sample too small to support any of the others —
    it is never reported as OK, because "we did not look hard enough" and "it
    is fine" are different findings.
    """
    if checked < STREAM_MIN_SAMPLES:
        return ("UNKNOWN",
                f"only {checked} frame(s) sampled; {STREAM_MIN_SAMPLES} are "
                "needed before a rate means anything")
    rate = suspect / checked
    if rate >= STREAM_CORRUPT_RATE:
        return ("CORRUPT",
                f"{rate:.0%} of {checked} sampled frames are decoder "
                "concealment. This stream's observations, and its silences, "
                "describe the decode and not the road.")
    if rate >= STREAM_DEGRADED_RATE:
        return ("DEGRADED",
                f"{rate:.0%} of {checked} sampled frames carry macroblock "
                "artefacts. Usable, with losses; treat gaps with caution.")
    return ("OK", f"{rate:.0%} of {checked} sampled frames carry macroblock "
                  "artefacts, which is ordinary packet loss on a live link")
