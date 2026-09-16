"""ANPR: plate detection, OCR, and multi-frame voting.

Three measured findings shaped this module. All were found by inspecting output
on the local corpus rather than trusting defaults.

1. **Resolution must be normalised before detection.** On a 1920x1080 frame the
   plate detector returned *zero* detections; the identical frame downscaled to
   1280x720, 960x540 or 640x360 returned the same plate at ~0.66 confidence.
   Since our estate is explicitly heterogeneous, feeding native resolution
   straight to the detector means a camera's resolution silently decides whether
   ANPR works. Every frame is therefore scaled to a fixed detection width and
   detections are mapped back to full-resolution coordinates.

2. **The tiny model beats the small model here.** ``yolo-v9-t-640`` scored
   0.83-0.86 where ``yolo-v9-s-608`` scored 0.30-0.44 on the same frames. For
   small objects, detector input resolution dominates parameter count.

3. **OCR slot count is a hard ceiling.** ``global-plates-mobile-vit-v2`` has
   ``max_plate_slots = 9`` and therefore *cannot represent* a 10-character
   Indian registration mark — it truncates structurally, producing confident
   wrong reads like ``GJ05AB1``. ``cct-s-v2-global`` has 10 slots and reads the
   full mark. This is the kind of defect that looks like poor accuracy and is
   actually a wrong model choice.

Crops for OCR are taken from the **full-resolution** frame, not the downscaled
detection frame, so character detail is preserved.
"""
from __future__ import annotations

import logging
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saakshya.analytics.plates import PlateRead, parse
from saakshya.models.registry import ANPR_CPU, ModelRecord
from saakshya.runtime.backend import BACKENDS, InferenceBackend

log = logging.getLogger(__name__)

# ONNX Runtime is noisy about shape merges on these graphs; they are benign.
os.environ.setdefault("ORT_LOGGING_LEVEL", "3")


def prepare_ocr_crop(crop: np.ndarray, *, min_height: int = 48) -> np.ndarray:
    """Upscale a tiny plate crop before OCR. Never interpolates a new plate.

    The crop is the detector box on the full-resolution frame. If that box is
    shorter than ``min_height``, bicubic resize is the same image at a size the
    OCR backbone can actually tokenise. Characters are not hallucinated; a
    20 px smear is still a smear, just large enough to attempt a read.
    """
    if crop is None or crop.size == 0:
        return crop
    h = int(crop.shape[0])
    if h >= min_height:
        return crop
    scale = min_height / float(h)
    nw = max(1, round(int(crop.shape[1]) * scale))
    from PIL import Image

    rgb = Image.fromarray(crop[:, :, ::-1]).resize(
        (nw, min_height), Image.BICUBIC)  # type: ignore[attr-defined]
    return np.asarray(rgb)[:, :, ::-1].copy()


@dataclass(slots=True)
class AnprConfig:
    """Analytics-layer configuration.

    Deliberately holds no model names or execution providers: which weights run
    and on what hardware is the registry's and the router's decision, not this
    module's. What stays here is the behaviour that must be identical on every
    profile — resolution normalisation, voting, thresholds.
    """

    #: Frames are scaled so the longest side is at most this, before detection.
    detection_max_width: int = 1280
    detector_conf: float = 0.40

    #: A single frame never *confirms* a plate. Reads are accumulated per track
    #: and voted; this is the minimum agreeing frames for a CONFIRMED read.
    min_votes: int = 2
    #: Minimum mean OCR confidence for a voted (>=min_votes) read to publish.
    min_confidence: float = 0.55

    #: When a track yields only one valid read — which is the common case at the
    #: per-camera frame rate a large estate can afford — that read is published
    #: as a LEAD rather than discarded, if it clears this higher bar. A lead is
    #: never a confirmation: it carries votes=1, and every downstream surface
    #: labels a one-vote plate REQUIRES_VERIFICATION. Discarding it entirely was
    #: the difference between a route and a blank screen when a vehicle crossed
    #: a camera once. The bar is high because there is no corroboration to lean
    #: on — only format validity and this confidence.
    enable_single_read_leads: bool = True
    single_read_lead_confidence: float = 0.82
    #: Reads are held per track for at most this many seconds of stream time.
    vote_window_s: float = 12.0
    #: Smallest plate-crop height sent to OCR. Detection already maps boxes
    #: back to the full-resolution frame; government mounts still often yield
    #: 20-40 px of plate. The OCR backbone was trained nearer 48 px. Stretching
    #: the crop is the same pixels, larger — it does not invent characters.
    ocr_min_height: int = 48


@dataclass
class RawRead:
    text: str
    confidence: float
    box: tuple[int, int, int, int]
    det_confidence: float
    pts_s: float


@dataclass
class VotedPlate:
    """The published result of voting across frames."""

    plate: PlateRead
    confidence: float
    votes: int
    total_reads: int
    first_pts_s: float
    last_pts_s: float
    best_box: tuple[int, int, int, int]
    runners_up: list[tuple[str, int]] = field(default_factory=list)
    #: One valid read, published as a lead. votes==1 already says this, but the
    #: flag makes the intent explicit at every read site.
    provisional: bool = False

    @property
    def unanimity(self) -> float:
        return self.votes / max(1, self.total_reads)

    def status(self) -> str:
        return plate_status(votes=self.votes)

    def explain(self) -> str:
        if self.provisional:
            return (f"{self.plate.canonical} — LEAD from a single read at "
                    f"OCR {self.confidence:.2f}; not corroborated across frames "
                    f"and requires verification")
        base = (f"{self.plate.canonical} from {self.votes}/{self.total_reads} "
                f"agreeing frames, mean OCR {self.confidence:.2f}")
        if self.runners_up:
            alts = ", ".join(f"{t}x{n}" for t, n in self.runners_up[:2])
            return f"{base}; competing reads: {alts}"
        return base


def plate_status(*, votes: int | None) -> str:
    """How a stored plate may be shown.

    Derived from the vote count so search, trajectory and alerts agree without
    a schema change. A single-read lead is never a confirmation: that is the
    whole point of publishing it at all.
    """
    if (votes or 0) >= 2:
        return "CONFIRMED_BY_PLATE"
    return "REQUIRES_VERIFICATION"


class AnprEngine:
    """Plate detection + OCR, executed through an :class:`InferenceBackend`.

    This class owns the *meaning*: resolution normalisation, crop geometry,
    confidence handling. The backend owns only where the arithmetic happens.
    That split is what lets DEV_CPU, CLOUD_GPU and TARGET_GPU share one
    implementation and produce comparable results.
    """

    def __init__(self, config: AnprConfig | None = None,
                 record: ModelRecord | None = None,
                 backend: InferenceBackend | None = None) -> None:
        self.cfg = config or AnprConfig()
        self.record = record or ANPR_CPU
        self._backend = backend
        self.version = self.record.key
        #: Crops the OCR stage refused. Non-zero is normal; a spike is not.
        self.ocr_crop_failures = 0

    @property
    def backend(self) -> InferenceBackend:
        if self._backend is None:
            self._backend = BACKENDS.get(self.record)
        return self._backend

    def provenance(self) -> dict:
        """Written into every event this engine contributes to."""
        p = self.record.provenance()
        p["backend"] = self.backend.name
        return p

    def _scaled(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """Downscale for detection. Returns the image and the scale factor."""
        h, w = image.shape[:2]
        if w <= self.cfg.detection_max_width:
            return image, 1.0
        scale = self.cfg.detection_max_width / float(w)
        nh, nw = max(1, round(h * scale)), self.cfg.detection_max_width
        # PIL is already a dependency and avoids pulling cv2 into this path.
        from PIL import Image

        # Pillow's stubs omit the module-level resampling aliases; the
        # attribute is present at runtime and covered by the ANPR tests.
        small = Image.fromarray(image[:, :, ::-1]).resize(
            (nw, nh), Image.BILINEAR)  # type: ignore[attr-defined]
        return np.asarray(small)[:, :, ::-1].copy(), scale

    def read_frame(self, image: np.ndarray, pts_s: float) -> list[RawRead]:
        """Detect plates in one frame and OCR each, at full resolution."""
        det_img, scale = self._scaled(image)
        out: list[RawRead] = []
        H, W = image.shape[:2]

        for d in self.backend.detect(det_img):
            bx1, by1, bx2, by2 = d.box
            inv = 1.0 / scale
            x1, y1 = int(bx1 * inv), int(by1 * inv)
            x2, y2 = int(bx2 * inv), int(by2 * inv)
            # Small pad; plate detectors often crop the border characters tight.
            pad_x = max(2, int((x2 - x1) * 0.04))
            pad_y = max(2, int((y2 - y1) * 0.10))
            x1, y1 = max(0, x1 - pad_x), max(0, y1 - pad_y)
            x2, y2 = min(W, x2 + pad_x), min(H, y2 + pad_y)
            if x2 - x1 < 8 or y2 - y1 < 5:
                continue

            crop = prepare_ocr_crop(
                image[y1:y2, x1:x2], min_height=self.cfg.ocr_min_height)
            try:
                res = self.backend.ocr(crop)
            except (ValueError, RuntimeError, IndexError):
                # Deliberately narrow. A malformed crop is expected and skippable;
                # an AttributeError or TypeError here is a *bug in this code* and
                # must surface loudly. An earlier version caught bare Exception
                # and silently swallowed a refactor error, turning a broken
                # pipeline into "zero detections" with no diagnostic.
                log.debug("OCR rejected crop at %s", (x1, y1, x2, y2), exc_info=True)
                self.ocr_crop_failures += 1
                continue
            if res is None or not res.text:
                continue
            out.append(RawRead(
                text=res.text, confidence=res.confidence,
                box=(x1, y1, x2, y2), det_confidence=d.score, pts_s=pts_s,
            ))
        return out


class PlateVoter:
    """Accumulates reads per track and publishes only corroborated plates.

    A single OCR result is never trusted. On the hard camera in the corpus the
    engine returns nothing at all, which is the correct behaviour — but a
    degraded camera can also return *confident garbage*, and voting plus format
    validation is what stops that entering the evidence record.
    """

    def __init__(self, config: AnprConfig | None = None) -> None:
        self.cfg = config or AnprConfig()
        self._reads: dict[str, list[RawRead]] = defaultdict(list)
        self.rejected_invalid = 0
        self.rejected_low_votes = 0
        self.rejected_low_conf = 0

    def add(self, track_key: str, reads: list[RawRead]) -> None:
        if not reads:
            return
        bucket = self._reads[track_key]
        bucket.extend(reads)
        cutoff = max(r.pts_s for r in bucket) - self.cfg.vote_window_s
        self._reads[track_key] = [r for r in bucket if r.pts_s >= cutoff]

    def resolve(self, track_key: str) -> VotedPlate | None:
        reads = self._reads.get(track_key, [])
        if not reads:
            return None

        valid: list[tuple[PlateRead, RawRead]] = []
        for r in reads:
            pr = parse(r.text)
            if pr.valid:
                valid.append((pr, r))
            else:
                self.rejected_invalid += 1
        if not valid:
            return None

        counts = Counter(pr.canonical for pr, _ in valid)
        best, votes = counts.most_common(1)[0]
        members = [(pr, r) for pr, r in valid if pr.canonical == best]
        conf = float(np.mean([r.confidence for _, r in members]))

        provisional = False
        if votes < self.cfg.min_votes:
            # Not corroborated. Publish as a lead only if it is a single dominant
            # read that clears the higher single-read bar; otherwise reject.
            competing = any(n >= votes for c, n in counts.items() if c != best)
            if (not self.cfg.enable_single_read_leads or competing
                    or conf < self.cfg.single_read_lead_confidence):
                self.rejected_low_votes += 1
                return None
            provisional = True
        elif conf < self.cfg.min_confidence:
            self.rejected_low_conf += 1
            return None

        best_read = max(members, key=lambda m: m[1].det_confidence)[1]
        return VotedPlate(
            plate=members[0][0],
            confidence=conf,
            votes=votes,
            provisional=provisional,
            total_reads=len(valid),
            first_pts_s=min(r.pts_s for _, r in members),
            last_pts_s=max(r.pts_s for _, r in members),
            best_box=best_read.box,
            runners_up=[(t, n) for t, n in counts.most_common()[1:4]],
        )

    def resolve_all(self, track_key: str) -> list[VotedPlate]:
        """Every *corroborated* plate in this bucket, not just the top one.

        This is the camera-level evaluation path. It deliberately does **not**
        publish single-read leads: at camera granularity a high-confidence OCR
        is one read among many vehicles, and promoting it would flood a
        degraded camera (C-033) with false plates. Leads are a per-track
        decision — see :meth:`resolve`, which the live pipeline uses.

        Without a tracker, all vehicles crossing one camera land in a single
        bucket; returning only the modal plate would silently discard every
        other vehicle on that camera.
        """
        reads = self._reads.get(track_key, [])
        if not reads:
            return []
        valid = [(parse(r.text), r) for r in reads]
        valid = [(pr, r) for pr, r in valid if pr.valid]
        if not valid:
            return []

        counts = Counter(pr.canonical for pr, _ in valid)
        out: list[VotedPlate] = []
        for canon, votes in counts.most_common():
            if votes < self.cfg.min_votes:
                continue
            members = [(pr, r) for pr, r in valid if pr.canonical == canon]
            conf = float(np.mean([r.confidence for _, r in members]))
            if conf < self.cfg.min_confidence:
                continue
            best_read = max(members, key=lambda m: m[1].det_confidence)[1]
            out.append(VotedPlate(
                plate=members[0][0], confidence=conf, votes=votes,
                total_reads=len(valid),
                first_pts_s=min(r.pts_s for _, r in members),
                last_pts_s=max(r.pts_s for _, r in members),
                best_box=best_read.box,
                runners_up=[(t, n) for t, n in counts.most_common() if t != canon][:3],
            ))
        return out

    def drop(self, track_key: str) -> None:
        self._reads.pop(track_key, None)

    def forensic_rows(self, track_key: str) -> list[dict[str, Any]]:
        """Every OCR attempt still on this track, including rejected format.

        Voting decides what is published on an observation. Forensics needs
        the discarded reads too — Overview's ``raw_ocr_read_records`` is this
        table, not the plated-observation count.
        """
        out: list[dict[str, Any]] = []
        for r in self._reads.get(track_key, []):
            pr = parse(r.text)
            width = None
            if r.box is not None:
                width = float(r.box[2] - r.box[0])
            out.append({
                "pts_s": r.pts_s,
                "raw_text": (r.text or "")[:48],
                "canonical": (pr.canonical[:24] if pr.canonical else None),
                "valid": bool(pr.valid),
                "reject_reason": (None if pr.valid
                                  else (pr.reason or "rejected")[:120]),
                "ocr_confidence": r.confidence,
                "det_confidence": r.det_confidence,
                "plate_pixel_width": width,
            })
        return out

    def stats(self) -> dict[str, int]:
        return {
            "tracks_pending": len(self._reads),
            "rejected_invalid_format": self.rejected_invalid,
            "rejected_insufficient_votes": self.rejected_low_votes,
            "rejected_low_confidence": self.rejected_low_conf,
        }


def temporal_ocr_consensus(
    reads: list[RawRead],
    *,
    config: AnprConfig | None = None,
    track_key: str = "evaluation-track",
) -> VotedPlate | None:
    """Resolve OCR observations using the live track voter semantics.

    This adapter deliberately contains no alternate voting rules.  It is safe
    for offline evaluation because :class:`PlateVoter` still validates plate
    structure, applies the PTS window, and preserves conservative unreadable
    behaviour for weak or competing reads.
    """
    voter = PlateVoter(config)
    voter.add(track_key, reads)
    return voter.resolve(track_key)
