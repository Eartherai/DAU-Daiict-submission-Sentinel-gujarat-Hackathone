"""Camera analytics pipeline: frames in, vehicle observations out.

This is where the multi-vehicle ANPR defect is fixed. The earlier design voted
plates per *camera*, so three vehicles crossing one camera collapsed into one
published plate and the other two were silently lost. Voting is now per *track*:

    frame → detections → tracker → per-track plate reads → vote → observation

A track is a vehicle's continuous presence in one camera's view, so per-track
voting is the correct granularity by construction rather than by tuning.

Two further properties matter as much as the plate:

* **Observations without a readable plate are first-class.** They carry
  appearance, attributes and quality, and they are what makes the unreadable-
  plate case recoverable at all. Discarding them would make the hard case
  impossible.
* **Every observation carries its own quality**, measured from the pixels that
  produced it — not inherited from a camera-level grade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from saakshya.analytics.anpr import AnprConfig, AnprEngine, PlateVoter, RawRead
from saakshya.analytics.attributes import (
    VehicleAttributes,
    implied_vehicle_box,
)
from saakshya.analytics.attributes import (
    extract as extract_attrs,
)
from saakshya.analytics.motion import MotionConfig, MotionDetector
from saakshya.analytics.quality import ObservationQuality, assess
from saakshya.analytics.tracker import Detection, Track, TrackerConfig, TrackerPool, iou
from saakshya.ingest.frame import Frame
from saakshya.runtime.inference_scheduler import AdaptiveInferenceScheduler
from saakshya.store import VehicleObservation, to_us

log = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    anpr: AnprConfig = field(default_factory=AnprConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    #: People are detected from the same forward pass as vehicles and tracked
    #: separately: a person is not a vehicle, must never reach plate voting, and
    #: must never be fused into a vehicle body.
    enable_person_detector: bool = True
    person_conf: float = 0.45
    #: A person present on one camera for longer than this is reported as a
    #: dwell. It is a *report*, not an accusation — "intrusion" is a judgement
    #: about permission that this system is not in a position to make, so the
    #: observation is published and the word is left to the officer.
    person_dwell_s: float = 12.0

    #: Vehicle detection is optional. On the synthetic corpus a COCO-trained
    #: detector performs poorly (crude shapes are not COCO vehicles), while the
    #: plate detector is reliable — so the plate can anchor tracks there. On real
    #: footage the vehicle detector carries it. Both paths are supported rather
    #: than tuning one corpus into looking correct.
    #: Prove the detector works before it is used. One forward pass on a
    #: synthetic frame, once per process. Disable only where the model has
    #: already been validated in the same process.
    validate_models: bool = True
    #: On by default. It was off, so the entire T1 tier was dead code — and
    #: on the synthetic corpus motion and plate detection covered for it, so
    #: nothing failed. On real night footage where plates are unreadable, the
    #: vehicle detector *is* the tier.
    enable_vehicle_detector: bool = True
    vehicle_detector_key: str | None = "vehicle-rtdetrv2-r18@0.1.0"
    vehicle_conf: float = 0.35
    #: Tier-0 presence. Always on by default: it is the only detection stage
    #: that cannot domain-shift, and without it the cameras that most need the
    #: appearance fallback produce no observations at all.
    enable_motion: bool = True
    motion: MotionConfig = field(default_factory=MotionConfig)
    #: Motion boxes enter the tracker at this score — above the tracker's low
    #: threshold (so they can sustain a track) but below its high threshold
    #: (so they do not, alone, create one on a good camera).
    motion_score_floor: float = 0.20
    #: Emit an observation for a track only once it has this many hits.
    min_track_hits: int = 2
    #: Skip analytics on warm-up frames — they arrive faster than real time.
    skip_warmup: bool = True
    #: Optional adaptive gate. ``None`` retains the historical every-frame
    #: behaviour and therefore keeps existing callers/API semantics unchanged.
    inference_scheduler: AdaptiveInferenceScheduler | None = None


@dataclass
class PipelineStats:
    frames_in: int = 0
    frames_analysed: int = 0
    frames_skipped_warmup: int = 0
    plate_detections: int = 0
    vehicle_detections: int = 0
    motion_detections: int = 0
    plates_fused: int = 0
    plates_unfused: int = 0
    tracks_created: int = 0
    observations_emitted: int = 0
    observations_with_plate: int = 0
    observations_without_plate: int = 0
    segment_breaks: int = 0
    #: Attribute extraction declined because no region on this track was shaped
    #: like a vehicle. Counted rather than silent: a camera where this climbs is
    #: one where motion segmentation is merging traffic, which is actionable.
    attrs_abstained_implausible_box: int = 0
    #: Frames the vehicle detector rejected as bad input. A *broken* detector
    #: raises instead of incrementing this.
    vehicle_detector_errors: int = 0
    #: People are counted separately from vehicles throughout. A single
    #: "objects detected" number would hide which of the two the estate is
    #: actually seeing.
    person_detections: int = 0
    person_observations: int = 0
    person_dwells: int = 0

    def snapshot(self) -> dict[str, int]:
        return dict(self.__dict__)



#: A single vehicle cannot fill the frame. Motion segmentation occasionally
#: merges several vehicles and the road between them into one blob, and the
#: result is well-lit and confidently coloured — so the lit-fraction and
#: colour-confidence gates added in CR-003 pass it happily.
#:
#: Measured symptom on the denser corpus: a yellow car at C-021 reported
#: **white at 0.73 confidence**, sampled from a box spanning the full 1280 px
#: width. The gates were asking "is this crop readable"; nothing was asking
#: "is this crop a car".
MAX_BODY_FRAME_WIDTH = 0.72     # fraction of frame width
MAX_BODY_FRAME_AREA = 0.45      # fraction of frame area
MAX_BODY_ASPECT = 6.0           # a blob wider than this is a queue, not a car


def _is_plausible_vehicle_box(box: tuple[float, float, float, float],
                              shape: tuple[int, ...]) -> bool:
    """Geometric sanity, not a quality judgement.

    Deliberately generous: this rejects only boxes that no single vehicle could
    produce. A tight bound here would start discarding legitimate close-range
    observations, which is the opposite of what the system needs.
    """
    h, w = shape[0], shape[1]
    if w <= 0 or h <= 0:
        return True
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw <= 0 or bh <= 0:
        return False
    if bw / w > MAX_BODY_FRAME_WIDTH:
        return False
    if (bw * bh) / (w * h) > MAX_BODY_FRAME_AREA:
        return False
    return not bw / bh > MAX_BODY_ASPECT


class CameraPipeline:
    """Analytics for one camera. Stateful across frames, reset on segment break."""

    def __init__(self, camera_id: str, config: PipelineConfig | None = None,
                 district: str | None = None, department: str | None = None,
                 lat: float | None = None, lon: float | None = None) -> None:
        self.camera_id = camera_id
        self.cfg = config or PipelineConfig()
        self.district, self.department = district, department
        self.lat, self.lon = lat, lon

        self.anpr = AnprEngine(self.cfg.anpr)
        self.tracks = TrackerPool(self.cfg.tracker)
        #: People get their own pool. Sharing one with vehicles would let a
        #: person inherit a vehicle's track id across a frame where the two
        #: overlap, and then a plate voted on the vehicle would be published
        #: against the person.
        self.people = TrackerPool(self.cfg.tracker)
        self.stats = PipelineStats()

        #: track_id -> voter. Per-track, which is the whole point.
        self._voters: dict[str, PlateVoter] = {}
        #: track_id -> best-quality assessment seen so far.
        self._best_quality: dict[str, ObservationQuality] = {}
        #: Attributes from the *highest-quality* frame of each track, not the
        #: last: a vehicle leaving frame gives a worse reading than mid-crossing.
        self._best_attrs: dict[str, tuple[float, VehicleAttributes]] = {}
        #: The frame of each track's best plate read, with its quality score.
        #: Evidence for an observation must show the vehicle whose plate was
        #: read. The frame in hand when the track *closes* is later - often
        #: after that vehicle has left - and sealing it put another car beside
        #: the record's plate: 26 sealed stills for one plate showed a second
        #: vehicle entirely.
        self._evidence_frames: dict[str, tuple[float, Any]] = {}
        #: dedup_key -> that frame, for observations emitted by the current
        #: process()/flush() call. Cleared at the start of the next call, so a
        #: frame is held only until the caller has had the chance to seal it.
        self._evidence_out: dict[str, Any] = {}
        self._seen_tracks: set[str] = set()
        self._sequence = 0
        self._vehicle_backend: Any = None
        #: People found in the most recent forward pass, held between the
        #: detection call and the tracking step in the same frame.
        self._people: list[Detection] = []
        self._person_seen: set[str] = set()
        self._motion = MotionDetector(self.cfg.motion) if self.cfg.enable_motion else None
        self._last_segment: str | None = None
        #: Raw OCR attempts drained into ``plate_reads``. Survives an
        #: observation that is not emitted (short track, no valid plate).
        self._forensic_reads: list[dict[str, Any]] = []

    def drain_plate_reads(self) -> list[dict[str, Any]]:
        """Take forensic OCR rows accumulated since the last drain."""
        rows, self._forensic_reads = self._forensic_reads, []
        return rows

    # -- vehicle detection (optional) --------------------------------------- #
    def _vehicle_detections(self, frame: Frame) -> list[Detection]:
        if not self.cfg.enable_vehicle_detector:
            return []
        if self._vehicle_backend is None:
            from saakshya.models.registry import get
            from saakshya.runtime.backend import BACKENDS

            key = self.cfg.vehicle_detector_key
            if not key:
                raise ValueError(
                    "PipelineConfig.vehicle_detector_key is unset; model "
                    "selection comes from the registry, never from a default")
            rec = get(key)
            if rec is None:
                raise KeyError(
                    f"no model registered under {key!r}; "
                    "the registry is the source of truth for model selection")
            # Prove it works before pointing it at thirty cameras. Cheap: one
            # forward pass on a synthetic frame, once per process. It exists
            # because a detector that had never produced a detection ran in
            # this codebase for weeks behind a flag and a broad except.
            if self.cfg.validate_models:
                from saakshya.models.validation import active_or_raise
                active_or_raise(key)
            self._vehicle_backend = BACKENDS.get(rec)
        out: list[Detection] = []
        people: list[Detection] = []
        try:
            # One forward pass serves both consumers. The detector is
            # COCO-trained and returns people alongside vehicles; running it
            # twice to get them would double the GPU cost of the whole estate
            # for a result the first pass already computed.
            for d in self._vehicle_backend.detect(frame.image):
                lab = (d.label or "").lower()
                if lab == "motorbike":
                    lab = "motorcycle"
                if lab in {"car", "motorcycle", "bus", "truck", "bicycle"}:
                    thr = 0.18 if lab in {"motorcycle", "bicycle"} else self.cfg.vehicle_conf
                    if d.score >= thr:
                        out.append(Detection(box=d.box, score=d.score, label=lab,
                                             source="vehicle"))
                elif lab == "person" and d.score >= self.cfg.person_conf:
                    people.append(Detection(box=d.box, score=d.score,
                                            label="person", source="person"))
            self._people = people
        except (ValueError, RuntimeError, IndexError) as exc:
            # Bad input for one frame: count it and carry on.
            self.stats.vehicle_detector_errors += 1
            if self.stats.vehicle_detector_errors <= 3:
                log.warning("vehicle detector rejected a frame on %s: %s",
                            self.camera_id, exc)
        except Exception:
            # Anything else is a programming or model-loading error, and
            # swallowing it reports a broken detector as an empty road. That
            # exact substitution cost a day on the synthetic corpus (CR-001) and
            # cost another on the live grid, where the detector had been loading
            # a detection checkpoint into a bare backbone and raising on every
            # single frame while the pipeline logged "0 vehicles".
            log.error("vehicle detector is broken on %s — this is a fault, not "
                      "an empty scene", self.camera_id, exc_info=True)
            raise
        self.stats.vehicle_detections += len(out)
        return out

    @staticmethod
    def _view_score(track: Track, frame: Frame) -> float:
        """How good a view of the vehicle this frame gives, 0..1.

        A vehicle entering or leaving the field of view is clipped at the frame
        edge, so its box is mostly background. Sampling attributes there reads
        the road. This scores the frames where the vehicle is fully visible and
        large, which is exactly mid-crossing.
        """
        x1, y1, x2, y2 = track.box
        h, w = frame.image.shape[:2]
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)

        # Clipping penalty: touching any edge means part of the vehicle is
        # outside the frame and the box is padded with background.
        margin = 2.0
        clipped = (x1 <= margin) + (y1 <= margin) + (x2 >= w - margin) + (y2 >= h - margin)
        clip_factor = 0.15 ** clipped          # one clipped edge is already bad

        # Size, normalised against the largest plausible on-screen vehicle.
        size = min(1.0, (bw * bh) / (0.25 * w * h))

        # Centrality: the middle of frame is usually the least distorted view.
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        centre_d = ((cx - w / 2.0) / (w / 2.0)) ** 2 + ((cy - h / 2.0) / (h / 2.0)) ** 2
        centrality = max(0.0, 1.0 - centre_d / 2.0)

        return float(clip_factor * (0.65 * size + 0.35 * centrality))

    @staticmethod
    def _body_box(track: Track, frame: Frame
                  ) -> tuple[float, float, float, float] | None:
        """Best available estimate of the vehicle body for attribute extraction.

        Order matters. Reading colour from a plate crop returns the colour of the
        plate; reading size class from it returns the aspect of a rectangle. The
        measured symptom before this existed was every observation reporting
        colour "black" with a random size class.

            1. a real vehicle-detector or motion box, if this track ever had one
            2. otherwise, a body region implied by the plate's geometry
        """
        # Prefer the CURRENT box when it already is a body box. Plate/body fusion
        # makes that the normal case. Using "largest box ever seen" instead was a
        # measured bug: an early oversized motion blob covering road became the
        # attribute source for the whole track, and every colour read as black.
        shape = frame.image.shape
        if (track.source in {"vehicle", "motion", "plate_implied"}
                and _is_plausible_vehicle_box(track.box, shape)):
            return track.box
        if (track.best_body_box is not None
                and _is_plausible_vehicle_box(track.best_body_box, shape)):
            return track.best_body_box
        implied = implied_vehicle_box(track.box, shape)
        if _is_plausible_vehicle_box(implied, shape):
            return implied
        # Nothing here is shaped like a vehicle. Abstaining is the established
        # answer in this pipeline: no colour is strictly better than a confident
        # wrong one, because a wrong colour propagates into retrieval and into
        # an officer's belief about the vehicle.
        return None

    @staticmethod
    def _containment(inner: tuple, outer: tuple) -> float:
        """Fraction of ``inner`` inside ``outer``. Plates sit inside vehicles, so
        containment associates them far more reliably than IoU (a plate box is a
        tiny fraction of a vehicle box, which caps IoU at a low value)."""
        ix1, iy1 = max(inner[0], outer[0]), max(inner[1], outer[1])
        ix2, iy2 = min(inner[2], outer[2]), min(inner[3], outer[3])
        iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
        area = (inner[2] - inner[0]) * (inner[3] - inner[1])
        return (iw * ih) / area if area > 0 else 0.0

    def _assign_read_to_track(self, read: RawRead, tracks: list[Track]) -> Track | None:
        if not tracks:
            return None
        best, best_score = None, 0.0
        for t in tracks:
            s = self._containment(read.box, t.box)
            if s < 0.5:                       # fall back to IoU for plate-only tracks
                s = iou(read.box, t.box)
            if s > best_score:
                best, best_score = t, s
        return best if best_score >= 0.25 else None

    # -- main entry point --------------------------------------------------- #
    def process(self, frame: Frame) -> list[VehicleObservation]:
        """Analyse one frame, using an optional bounded scheduler slot.

        A full queue never causes evidence loss: the frame is processed
        synchronously as a fallback, outside the advisory queue.
        """
        self._evidence_out.clear()
        gate = self.cfg.inference_scheduler
        plan = gate.plan(self.stats.frames_in) if gate else None
        admitted = bool(plan and plan.sample and plan.infer and gate and
                        gate.admit(plan.mode))
        if plan and plan.sample and plan.infer and gate and not admitted:
            log.warning("scheduler queue full on %s; processing synchronously",
                        self.camera_id)
        try:
            return self._process(frame, plan)
        finally:
            if admitted and gate:
                gate.complete()

    def _process(
        self, frame: Frame, plan: Any = None
    ) -> list[VehicleObservation]:
        """Analyse one frame. Returns observations for tracks that just ended."""
        self.stats.frames_in += 1

        tracker = self.tracks.get(self.camera_id, frame.segment_id)
        if self._last_segment != frame.segment_id:
            if self._last_segment is not None:
                self.stats.segment_breaks += 1
            # The background model is scene-specific; a scene cut invalidates it.
            if self._motion is not None:
                self._motion.reset()
            self._last_segment = frame.segment_id

        if self.cfg.skip_warmup and frame.warmup:
            self.stats.frames_skipped_warmup += 1
            return []
        self.stats.frames_analysed += 1

        if plan is not None and not plan.sample:
            return []

        # 1. Detect. Plate reads come from the ANPR engine, which already does
        #    resolution normalisation and full-resolution cropping.
        reads = self.anpr.read_frame(frame.image, frame.pts_s) if (
            plan is None or plan.ocr) else []
        self.stats.plate_detections += len(reads)

        # Body candidates: the detector where it is usable, motion everywhere.
        bodies: list[Detection] = self._vehicle_detections(frame)
        if self._motion is not None:
            for box, score in self._motion.detect(frame.image):
                bodies.append(Detection(
                    box=box,
                    score=max(self.cfg.motion_score_floor,
                              min(score, self.cfg.tracker.high_thresh - 0.01)),
                    label="vehicle", source="motion"))
                self.stats.motion_detections += 1

        # Fuse each plate into the body that contains it, so the tracker sees ONE
        # detection per physical vehicle. Without this, a plate box and its own
        # vehicle's motion box compete as separate detections, the plate usually
        # wins on IoU continuity, and every downstream attribute is then read off
        # a plate crop - which measured as colour "black" on every observation.
        dets: list[Detection] = []
        used_bodies: set[int] = set()
        for r in reads:
            host, host_i, best = None, -1, 0.0
            for i, b in enumerate(bodies):
                c = self._containment(r.box, b.box)
                if c > best:
                    host, host_i, best = b, i, c
            if host is not None and best >= 0.6:
                dets.append(Detection(
                    box=host.box, score=max(host.score, r.det_confidence),
                    label=host.label, is_plate=False, source=host.source))
                used_bodies.add(host_i)
                self.stats.plates_fused += 1
            else:
                # No containing body: fall back to plate-implied geometry, which
                # is an estimate and is marked as one in provenance.
                dets.append(Detection(
                    box=implied_vehicle_box(r.box, frame.image.shape),
                    score=r.det_confidence, label="vehicle",
                    is_plate=False, source="plate_implied"))
                self.stats.plates_unfused += 1

        for i, b in enumerate(bodies):
            if i not in used_bodies:
                dets.append(b)

        # 2. Track.
        before = set(tracker.tracks)
        active = tracker.step(dets, frame.pts_s, frame.t_norm)
        self.stats.tracks_created += len(set(tracker.tracks) - before)

        # 3. Attribute plate reads to tracks, and vote per track.
        for r in reads:
            t = self._assign_read_to_track(r, active) or self._assign_read_to_track(
                r, list(tracker.tracks.values()))
            if t is None:
                continue
            self._voters.setdefault(t.track_id, PlateVoter(self.cfg.anpr)).add(
                t.track_id, [r])
            q = assess(frame.image, plate_box=r.box, vehicle_box=t.box)
            prev = self._best_quality.get(t.track_id)
            if prev is None or q.score > prev.score:
                self._best_quality[t.track_id] = q
            self._keep_evidence_frame(t.track_id, q.score, frame.image)
            self._seen_tracks.add(t.track_id)

        # Tracks with no plate at all still deserve a quality assessment, or the
        # unreadable-plate case has nothing to rank.
        for t in active:
            if t.track_id not in self._best_quality:
                q = assess(frame.image, plate_box=None, vehicle_box=t.box)
                self._best_quality[t.track_id] = q
                self._seen_tracks.add(t.track_id)

        # Attributes are the primary appearance signal. A DINOv2 embedding was
        # measured on the synthetic corpus and did not separate vehicles there;
        # re-measured on the live government feed (cam01, 60 frames, 17 tracks)
        # it does better but not well enough to confirm identity:
        #
        #     same vehicle       mean 0.830, p05 0.640
        #     different vehicles mean 0.576, p95 0.791
        #     best balanced accuracy 0.831 at threshold 0.74
        #
        # The distributions overlap, so an embedding can *rank* cross-camera
        # candidates for a human to review; it cannot assert that two sightings
        # are the same vehicle. It is therefore not stored as an identity
        # signal. See analytics/attributes.py and PERFORMANCE.md.
        #
        # Read attributes from the best VIEW of the vehicle,
        # not the best-quality frame: quality barely varies across a crossing,
        # so ties went to the last frame, which is systematically the worst one
        # (the vehicle half out of shot). Measured symptom: colour "black" on
        # every observation, sampled from road.
        if plan is None or plan.reid:
            for t in active:
                view = self._view_score(t, frame)
                best_view = self._best_attrs.get(t.track_id)
                if best_view is None or view > best_view[0]:
                    body = self._body_box(t, frame)
                    if body is None:
                        self.stats.attrs_abstained_implausible_box += 1
                        continue
                    self._best_attrs[t.track_id] = (view, extract_attrs(frame.image, body))

        # 4. Emit for tracks that ended this step.
        out: list[VehicleObservation] = []
        while tracker.finished:
            out.extend(self._emit(tracker.finished.pop(), frame))
        out.extend(self._people_step(frame))
        return out

    # -- people ------------------------------------------------------------- #
    def _people_step(self, frame: Frame) -> list[VehicleObservation]:
        """Track the people from this frame's forward pass and emit closures.

        Kept entirely apart from the vehicle path: people are never fused with
        plates, never voted, and never given a registration mark. What they get
        is a position, a time, and how long they stayed.
        """
        if not self.cfg.enable_person_detector:
            return []
        pt = self.people.get(self.camera_id, frame.segment_id)
        active = pt.step(self._people, frame.pts_s, frame.t_norm)
        self.stats.person_detections += len(self._people)
        for t in active:
            self._person_seen.add(t.track_id)
        out: list[VehicleObservation] = []
        while pt.finished:
            ob = self._emit_person(pt.finished.pop(), frame)
            if ob is not None:
                out.append(ob)
        return out

    def _emit_person(self, track: Track, frame: Frame | None
                     ) -> VehicleObservation | None:
        if track.hits < self.cfg.min_track_hits:
            return None
        dwell = max(0.0, track.last_pts_s - track.first_pts_s)
        self.stats.person_observations += 1
        if dwell >= self.cfg.person_dwell_s:
            self.stats.person_dwells += 1
        x1, y1, x2, y2 = track.box
        return VehicleObservation(
            camera_id=self.camera_id,
            pts_s=track.last_pts_s,
            t_norm=track.last_t_norm,
            t_ingest=frame.t_ingest if frame else track.last_t_norm,
            dedup_key=f"person:{self.camera_id}:{track.track_id}",
            track_id=track.track_id,
            segment_id=frame.segment_id if frame else None,
            department=self.department, district=self.district,
            lat=self.lat, lon=self.lon,
            object_type="person",
            bbox=(float(x1), float(y1), float(x2), float(y2)),
            detection_confidence=float(track.score),
            # Dwell travels as observation quality's sibling in provenance, not
            # as a verdict. The word "intrusion" is a judgement about
            # permission, and this system does not know who is permitted where.
            model_versions={"pipeline": "saakshya@0.1.0",
                            "detector": self.cfg.vehicle_detector_key or "",
                            "dwell_s": round(dwell, 2),
                            "dwell_exceeded": dwell >= self.cfg.person_dwell_s})

    def flush(self) -> list[VehicleObservation]:
        """Emit everything still open. Called at shutdown and on segment break.

        Both pools. Flushing only the vehicle pool silently discarded every
        person still in frame at shutdown — which, for a camera watching a
        pavement, is most of them.
        """
        self._evidence_out.clear()
        out: list[VehicleObservation] = []
        for tr in self.tracks._by_camera.values():
            for t in tr.close_segment():
                out.extend(self._emit(t, None))
            while tr.finished:
                out.extend(self._emit(tr.finished.pop(), None))
        for pr in self.people._by_camera.values():
            for t in pr.close_segment():
                ob = self._emit_person(t, None)
                if ob is not None:
                    out.append(ob)
            while pr.finished:
                ob = self._emit_person(pr.finished.pop(), None)
                if ob is not None:
                    out.append(ob)
        return out

    def _record_forensic(self, voter: PlateVoter, track: Track,
                         frame: Frame | None) -> None:
        """Keep every OCR attempt, including the ones voting discarded."""
        segment = frame.segment_id if frame is not None else None
        for r in voter.forensic_rows(track.track_id):
            dt = track.first_t_norm + timedelta(
                seconds=float(r["pts_s"]) - track.first_pts_s)
            self._forensic_reads.append({
                "camera_id": self.camera_id,
                "track_id": track.track_id,
                "segment_id": segment,
                "t_norm_us": to_us(dt),
                **r,
            })

    def _emit(self, track: Track, frame: Frame | None) -> list[VehicleObservation]:
        voter = self._voters.pop(track.track_id, None)
        quality = self._best_quality.pop(track.track_id, None)
        attrs = (self._best_attrs.pop(track.track_id, (0.0, None)))[1]
        read_frame = self._evidence_frames.pop(track.track_id, (0.0, None))[1]

        # Per-track resolve, not resolve_all. resolve_all is the camera-level
        # eval path and refuses to publish a single-read lead — at that
        # granularity the lead would be one OCR among many vehicles. A track
        # is one vehicle, so a single confident read is a LEAD.
        best = voter.resolve(track.track_id) if voter else None
        if voter is not None:
            self._record_forensic(voter, track, frame)

        # A one-hit track with no plate is still noise. A one-hit track that
        # produced a plate (almost always a lead at the frame rate a large
        # estate can afford) is a real crossing that used to vanish.
        if track.hits < self.cfg.min_track_hits and best is None:
            return []

        # A track whose box has grown beyond any single vehicle has absorbed
        # more than one, and we can no longer say which vehicle its attributes
        # describe. The plate read stands — it came from one plate, on one
        # vehicle, voted across frames — but the appearance does not.
        #
        # Measured symptom before this: a yellow car at C-021 published as
        # WHITE at 0.73 confidence, its colour sampled from a merged blob
        # spanning the full 1280 px frame width.
        if frame is not None and attrs is not None and not _is_plausible_vehicle_box(
                track.box, frame.image.shape):
            attrs = None
            self.stats.attrs_abstained_implausible_box += 1

        self._sequence += 1
        obs = VehicleObservation(
            camera_id=self.camera_id,
            department=self.department, district=self.district,
            lat=self.lat, lon=self.lon,
            track_id=track.track_id,
            segment_id=frame.segment_id if frame else None,
            pts_s=track.first_pts_s,
            t_norm=track.first_t_norm, t_ingest=track.last_t_norm,
            dedup_key=f"{self.camera_id}:{track.track_id}:{self._sequence}",
            object_type=(track.label if track.label != "vehicle"
                         else ((attrs.size_class if attrs else None) or "unknown")),
            bbox=track.box,
            detection_confidence=track.score,
            plate=best.plate.canonical if best else None,
            plate_raw=best.plate.raw if best else None,
            plate_confidence=best.confidence if best else None,
            plate_votes=best.votes if best else 0,
            colour=attrs.colour if attrs else None,
            colour_confidence=attrs.colour_confidence if attrs else None,
            direction_deg=track.direction_deg,
            observation_quality=quality.score if quality else None,
            plate_pixel_width=quality.plate_pixel_width if quality else None,
            sharpness=quality.sharpness if quality else None,
            luminance=quality.luminance if quality else None,
            mean_luma=quality.mean_luma if quality else None,
            mean_chroma=quality.mean_chroma if quality else None,
            model_versions=self.anpr.provenance(),
        )
        self.stats.observations_emitted += 1
        if obs.plate:
            self.stats.observations_with_plate += 1
            if read_frame is not None:
                self._evidence_out[obs.dedup_key] = read_frame
        else:
            self.stats.observations_without_plate += 1
        return [obs]

    #: Frames are megabytes each, so the held set is bounded even if a track
    #: were ever dropped without being emitted. Far above the plate-bearing
    #: tracks one camera has open at once.
    MAX_EVIDENCE_FRAMES = 16

    def _keep_evidence_frame(self, track_id: str, score: float, image: Any) -> None:
        """Hold ``image`` as the track's evidence frame if it is its best read.

        Only a reference: each decoded frame is its own array, so nothing is
        copied and nothing later overwrites it.
        """
        held = self._evidence_frames.get(track_id)
        if held is not None and score <= held[0]:
            return
        if held is None and len(self._evidence_frames) >= self.MAX_EVIDENCE_FRAMES:
            self._evidence_frames.pop(next(iter(self._evidence_frames)))
        self._evidence_frames[track_id] = (score, image)

    def evidence_frame(self, obs: VehicleObservation) -> Any | None:
        """The frame ``obs``'s plate was best read from, or None.

        Available for observations returned by the latest ``process`` or
        ``flush`` call - which is when a caller seals them.
        """
        return self._evidence_out.get(obs.dedup_key)

    def snapshot(self) -> dict[str, Any]:
        return {"camera_id": self.camera_id, **self.stats.snapshot(),
                "trackers": self.tracks.stats()}


def persist_pipeline(store: Any, observations: list[VehicleObservation] | None,
                     pipeline: CameraPipeline) -> int:
    """Write observations and drain forensic OCR rows into ``plate_reads``.

    Call after ``flush`` so closed tracks are included. Empty observations
    still persist rejected OCR — that is the table's reason to exist.
    """
    n = store.add_observations(observations) if observations else 0
    reads = pipeline.drain_plate_reads()
    if reads:
        store.add_plate_reads(reads)
    return n
