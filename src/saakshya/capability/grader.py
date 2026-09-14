"""Camera capability, measured rather than declared.

The premise of this module is the single most important fact about the estate it
has to run on: most of these cameras were not installed to read registration
numbers. They were installed by Health, Panchayat, GSRTC and municipal bodies to
supervise a gate, a ward or a bus stand. A statewide system that assumes uniform
capability will confidently return nothing from half its cameras and never say
why.

So capability is treated as a measurement with three separable questions, graded
independently because they fail independently:

* **ANPR** — can a registration number be recovered here?
* **VEHICLE** — can this vehicle be told apart from another of the same class?
* **PRESENCE** — can we establish that *something* passed here?

A camera can be UNSUITABLE for the first, DEGRADED for the second and GOOD for
the third, and that combination is genuinely useful: it places a vehicle in a
corridor without pretending to identify it.

Two rules govern every grade produced here:

1. **Insufficient evidence is UNKNOWN, never UNSUITABLE.** A camera that has
   produced no observations may be pointed at an empty compound. Silence is not
   failure, and converting it into a poor grade would slander working equipment
   and, worse, teach operators to distrust the grades.
2. **Every grade carries the evidence that produced it** — sample count, the
   measured statistics, the policy version and the thresholds applied. A grade
   an engineer cannot audit is an opinion.
"""
from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from saakshya.store import SearchFilter, Store, VehicleObservation, from_us

#: Gujarat. India observes no daylight saving, so a fixed offset is exact rather
#: than an approximation — the usual reason to avoid fixed offsets does not apply.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


class Grade(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    UNSUITABLE = "UNSUITABLE"
    UNKNOWN = "UNKNOWN"


class TimeBand(StrEnum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    LOW_LIGHT = "LOW_LIGHT"
    ALL = "ALL"


@dataclass(frozen=True)
class GradePolicy:
    """Stated thresholds, versioned so a grade can be re-derived.

    These are engineering thresholds, not learned parameters. They were set
    against the local corpus, where ground truth exists, and they are expected to
    move once real government feeds have been profiled — which is exactly why
    they live in one versioned object that is stamped into every capability row
    rather than being scattered through the code as literals.
    """

    version: str = "grade-policy-1"

    #: Below this, the answer is UNKNOWN. Chosen so that a grade never rests on
    #: a handful of frames from one vehicle.
    min_samples_anpr: int = 20
    min_samples_vehicle: int = 20
    min_frames_presence: int = 200

    #: ANPR. Plate yield is per *vehicle observation*, so it measures the camera,
    #: not the traffic volume.
    anpr_good_yield: float = 0.35
    anpr_good_plate_px: float = 90.0
    anpr_degraded_yield: float = 0.08

    #: Appearance. Colour confidence is the primary signal because the DINOv2
    #: embedding baseline was measured and rejected (margin -0.541); see
    #: docs/MODEL_BENCHMARK.md. Grading against a rejected signal would be worse
    #: than not grading at all.
    #:
    #: Sharpness is the NORMALISED figure from `analytics.quality` — Laplacian
    #: variance divided by 400 and clipped to 0..1 — not raw variance. An
    #: earlier version of this policy carried a raw-units threshold of 45.0
    #: against a 0..1 measurement, so no camera could ever be graded GOOD for
    #: appearance. The suffix is part of the name now so the units cannot be
    #: misread again.
    vehicle_good_colour_yield: float = 0.50
    vehicle_good_sharpness_norm: float = 0.35
    vehicle_degraded_colour_yield: float = 0.15

    #: Presence. A stream that decodes and yields detections tells us something
    #: passed; that is a lower bar and most cameras clear it.
    presence_good_fps: float = 1.0
    presence_max_decoder_error_rate: float = 0.02
    presence_max_segment_breaks_per_hour: float = 6.0

    #: Illumination band split, on MEAN LUMA (brightness, 0..1) — not on the
    #: `luminance` field, which is an exposure *quality* score that peaks at
    #: mid-grey and therefore reads a well-exposed night scene as poor and a
    #: correctly exposed daylight scene as poor when it is bright. Using it here
    #: put every observation in the LOW_LIGHT band regardless of the hour.
    #:
    #: 0.22 mean luma is roughly the point at which a colour crop stops carrying
    #: usable chroma; it is an engineering threshold, and it is re-derivable
    #: from real feeds once they exist.
    low_light_mean_luma: float = 0.22
    day_start_hour: int = 6
    day_end_hour: int = 18

    #: This system does not classify weather. A RAIN band would need a measured
    #: signal it does not have, and inventing one from a drop in contrast would
    #: be a fabricated categorisation presented as a measurement.


DEFAULT_POLICY = GradePolicy()


def time_band(t: datetime, mean_luma: float | None,
              policy: GradePolicy = DEFAULT_POLICY) -> TimeBand:
    """Which illumination band a sample belongs to.

    Measured brightness wins over the clock. An underpass at noon is a low-light
    scene whatever the hour says, and grading it as DAY would produce a camera
    that looks capable in the summary and fails in use.

    ``mean_luma`` is brightness in 0..1. Passing the exposure-quality score here
    instead is the bug this signature was renamed to prevent.
    """
    if mean_luma is not None and mean_luma < policy.low_light_mean_luma:
        return TimeBand.LOW_LIGHT
    hour = t.astimezone(IST).hour
    return (TimeBand.DAY if policy.day_start_hour <= hour < policy.day_end_hour
            else TimeBand.NIGHT)


@dataclass
class CapabilityAssessment:
    camera_id: str
    band: TimeBand
    samples: int
    anpr: Grade
    vehicle: Grade
    presence: Grade
    #: Every number the grades were computed from.
    evidence: dict[str, Any] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    first_sample: datetime | None = None
    last_sample: datetime | None = None

    def usable_for(self) -> list[str]:
        out = []
        if self.anpr in (Grade.GOOD, Grade.DEGRADED):
            out.append("anpr")
        if self.vehicle in (Grade.GOOD, Grade.DEGRADED):
            out.append("appearance")
        if self.presence in (Grade.GOOD, Grade.DEGRADED):
            out.append("presence")
        return out

    def row(self) -> dict[str, Any]:
        e = self.evidence
        return {
            "samples": self.samples,
            "sharpness": e.get("median_sharpness"),
            "luminance": e.get("median_exposure_quality"),
            "mean_luma": e.get("median_mean_luma"),
            "contrast": e.get("median_contrast"),
            "scene_stability": e.get("scene_stability"),
            "vehicle_yield": e.get("colour_confident_yield"),
            "plate_yield": e.get("plate_yield"),
            # The rate alone is not honest at these sample sizes: one plate in
            # 411 observations renders as 0.00, which reads as "this camera has
            # never read a plate" when it demonstrably has. The count travels
            # with the rate so the reader can tell nought from nearly-nought.
            "plate_reads": e.get("plate_reads"),
            "anpr_grade": str(self.anpr),
            "vehicle_reid_grade": str(self.vehicle),
            "presence_grade": str(self.presence),
            "overall": e.get("overall"),
            "usable_for": json.dumps(self.usable_for()),
            "evidence": json.dumps({**e, "reasons": self.reasons}),
            "first_sample_us": (int(self.first_sample.timestamp() * 1e6)
                                if self.first_sample else None),
            "last_sample_us": (int(self.last_sample.timestamp() * 1e6)
                               if self.last_sample else None),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id, "time_band": str(self.band),
            "samples": self.samples,
            "anpr": str(self.anpr), "vehicle": str(self.vehicle),
            "presence": str(self.presence),
            "usable_for": self.usable_for(),
            "evidence": self.evidence, "reasons": self.reasons,
        }


class CapabilityGrader:
    """Grades cameras from observations already in the store.

    Deliberately offline and re-runnable: grading reads the same observations
    the investigator searches, so a grade can always be recomputed and defended
    from data that is still on disk.
    """

    #: The busiest government camera in the live store holds ~62k observations.
    #: A 20k window ordered by time silently dropped later plates, so a camera
    #: that had published a mark graded as if it never had.
    LOAD_LIMIT = 100_000

    def __init__(self, store: Store, policy: GradePolicy = DEFAULT_POLICY) -> None:
        self.store = store
        self.policy = policy

    # -- grading ------------------------------------------------------------ #
    def grade_camera(self, camera_id: str, *, band: TimeBand = TimeBand.ALL,
                     observations: Sequence[VehicleObservation] | None = None,
                     health: dict[str, Any] | None = None) -> CapabilityAssessment:
        p = self.policy
        obs = list(observations if observations is not None else
                   self.store.search(SearchFilter(
                       cameras=[camera_id], limit=self.LOAD_LIMIT)))
        if band is not TimeBand.ALL:
            obs = [o for o in obs if time_band(o.t_norm, o.mean_luma, p) is band]

        health = health if health is not None else \
            self.store.list_health([camera_id]).get(camera_id, {})

        persons = [o for o in obs if _is_person(o)]
        vehicles = [o for o in obs if not _is_person(o)]
        n_all = len(obs)
        n = len(vehicles)
        n_persons = len(persons)
        ev: dict[str, Any] = {
            "policy_version": p.version,
            "observations": n_all,
            "vehicle_observations": n,
            "person_observations": n_persons,
        }
        reasons: dict[str, str] = {}

        # ---- presence: does the stream work, and does anything get detected? #
        frames = int(health.get("frames") or 0)
        dec_err = int(health.get("decoder_errors") or 0)
        fps = health.get("measured_fps")
        breaks = int(health.get("segment_breaks") or 0)
        err_rate = (dec_err / frames) if frames else None
        ev.update({"frames": frames, "decoder_errors": dec_err,
                   "decoder_error_rate": _r(err_rate, 5),
                   "measured_fps": _r(fps, 2), "segment_breaks": breaks})

        if frames < p.min_frames_presence and n_all == 0:
            presence = Grade.UNKNOWN
            reasons["presence"] = (
                f"only {frames} frames decoded; {p.min_frames_presence} needed "
                "before this camera can be graded. Not a fault — not yet measured.")
        elif fps is not None and fps < p.presence_good_fps:
            presence = Grade.DEGRADED
            reasons["presence"] = (
                f"stream delivers {fps:.2f} fps, below {p.presence_good_fps} fps. "
                "Vehicles will be missed between frames.")
        elif err_rate is not None and err_rate > p.presence_max_decoder_error_rate:
            presence = Grade.DEGRADED
            reasons["presence"] = (
                f"{err_rate:.1%} of frames failed to decode. The feed is unstable, "
                "so absence of a detection here is not evidence of absence.")
        elif n_all == 0:
            # The rule that matters. A stable stream with nothing in it is a
            # camera we cannot yet grade, not a camera that failed.
            presence = Grade.UNKNOWN
            reasons["presence"] = (
                "stream is healthy but nothing has been observed. This may be "
                "a correctly working camera pointed at a quiet scene; it is not "
                "evidence of a fault. Grade withheld.")
        else:
            presence = Grade.GOOD
            mix = (f"{n} vehicle, {n_persons} person"
                   if n_persons else f"{n} vehicle")
            if frames < p.min_frames_presence:
                reasons["presence"] = (
                    f"decoder frame counter recorded {frames} "
                    f"(below {p.min_frames_presence}), but {mix} observations "
                    "are already stored. Presence is taken from those "
                    "detections, not from the missing counter.")
            else:
                reasons["presence"] = (
                    f"{frames:,} frames decoded at {fps:.1f} fps with "
                    f"{mix} observations." if fps else
                    f"{frames:,} frames decoded with {mix} observations.")

        # ---- ANPR: yield is per vehicle. Persons are never plated. ----------- #
        plated = [o for o in vehicles if o.plate]
        plate_px = [o.plate_pixel_width for o in vehicles if o.plate_pixel_width]
        yield_ = (len(plated) / n) if n else None
        med_px = statistics.median(plate_px) if plate_px else None
        ev.update({"plate_reads": len(plated), "plate_yield": _r(yield_, 3),
                   "median_plate_px": _r(med_px, 1)})

        if n == 0 and n_persons:
            anpr = Grade.UNKNOWN
            reasons["anpr"] = (
                f"{n_persons} person observations and no vehicles. People are "
                "never plated; plate capability is ungraded, not failed.")
        elif n < p.min_samples_anpr:
            anpr = Grade.UNKNOWN
            reasons["anpr"] = (
                f"{n} vehicle observations; {p.min_samples_anpr} needed to grade "
                "plate capability. Insufficient evidence, not poor performance.")
        elif yield_ is not None and yield_ >= p.anpr_good_yield and (
                med_px is None or med_px >= p.anpr_good_plate_px):
            anpr = Grade.GOOD
            reasons["anpr"] = (
                f"{len(plated)}/{n} vehicle observations yielded a valid "
                f"registration number ({yield_:.0%})"
                + (f", median plate width {med_px:.0f} px." if med_px else "."))
        elif yield_ is not None and yield_ >= p.anpr_degraded_yield:
            anpr = Grade.DEGRADED
            detail = (f"median plate width {med_px:.0f} px is below the "
                      f"{p.anpr_good_plate_px:.0f} px needed for reliable OCR"
                      if med_px and med_px < p.anpr_good_plate_px
                      else "reads are intermittent")
            anpr_note = (f"{yield_:.0%} plate yield over {n} vehicle observations; "
                         f"{detail}. Usable as corroboration, not as sole "
                         "identification.")
            reasons["anpr"] = anpr_note
        else:
            anpr = Grade.UNSUITABLE
            reasons["anpr"] = (
                f"{len(plated)}/{n} vehicle observations produced a readable "
                f"plate ({(yield_ or 0):.0%}). Plate reading is not viable at "
                "this camera; route ANPR work elsewhere. A mark that did appear "
                "is still a mark — the grade is about yield, not existence.")

        # ---- vehicle appearance ---------------------------------------------- #
        col_conf = [o.colour_confidence for o in vehicles
                    if o.colour_confidence is not None]
        coloured = [o for o in vehicles
                    if o.colour and (o.colour_confidence or 0) >= 0.30]
        sharp = [o.sharpness for o in vehicles if o.sharpness is not None]
        lum = [o.luminance for o in vehicles if o.luminance is not None]
        luma = [o.mean_luma for o in vehicles if o.mean_luma is not None]
        qual = [o.observation_quality for o in vehicles
                if o.observation_quality is not None]
        col_yield = (len(coloured) / n) if n else None
        med_sharp = statistics.median(sharp) if sharp else None
        ev.update({
            "colour_confident_yield": _r(col_yield, 3),
            "median_colour_confidence": _r(
                statistics.median(col_conf) if col_conf else None, 3),
            "median_sharpness": _r(med_sharp, 1),
            "median_exposure_quality": _r(
                statistics.median(lum) if lum else None, 3),
            "median_mean_luma": _r(
                statistics.median(luma) if luma else None, 3),
            "median_observation_quality": _r(
                statistics.median(qual) if qual else None, 3),
        })

        if n == 0 and n_persons:
            vehicle = Grade.UNKNOWN
            reasons["vehicle"] = (
                "person observations only. Appearance is graded on vehicles; "
                "this is ungraded, not unsuitable.")
        elif n < p.min_samples_vehicle:
            vehicle = Grade.UNKNOWN
            reasons["vehicle"] = (
                f"{n} vehicle observations; {p.min_samples_vehicle} needed to "
                "grade appearance capability.")
        elif (col_yield or 0) >= p.vehicle_good_colour_yield and (
                med_sharp is None or med_sharp >= p.vehicle_good_sharpness_norm):
            vehicle = Grade.GOOD
            reasons["vehicle"] = (
                f"{col_yield:.0%} of vehicle observations produced a confident "
                "colour"
                + (f" at median sharpness {med_sharp:.0f}." if med_sharp else "."))
        elif (col_yield or 0) >= p.vehicle_degraded_colour_yield:
            vehicle = Grade.DEGRADED
            reasons["vehicle"] = (
                f"only {col_yield:.0%} of vehicle observations produced a "
                "confident colour. Appearance narrows a candidate list here; "
                "it does not identify a vehicle.")
        else:
            vehicle = Grade.UNSUITABLE
            reasons["vehicle"] = (
                f"{(col_yield or 0):.0%} confident-colour yield over {n} "
                "vehicle observations. Appearance matching is not viable at "
                "this camera.")

        times = [o.t_norm for o in obs]
        ev["overall"] = _r(_overall(anpr, vehicle, presence), 3)
        return CapabilityAssessment(
            camera_id=camera_id, band=band, samples=n_all,
            anpr=anpr, vehicle=vehicle, presence=presence,
            evidence=ev, reasons=reasons,
            first_sample=min(times) if times else None,
            last_sample=max(times) if times else None)

    def grade_all(self, *, bands: Sequence[TimeBand] = (TimeBand.ALL,),
                  persist: bool = True) -> list[CapabilityAssessment]:
        """Grade every registered camera. One pass over observations per camera.

        Loading each camera's observations once and re-filtering per band in
        memory avoids the obvious N-bands x N-cameras query storm.
        """
        cams = self.store.list_cameras()
        health = self.store.list_health()
        out: list[CapabilityAssessment] = []
        for c in cams:
            cid = c["camera_id"]
            obs = self.store.search(SearchFilter(
                cameras=[cid], limit=self.LOAD_LIMIT))
            for band in bands:
                a = self.grade_camera(cid, band=band, observations=obs,
                                      health=health.get(cid, {}))
                out.append(a)
                if persist:
                    self.store.upsert_capability(cid, str(band), a.row())
        return out

    def summary(self) -> dict[str, Any]:
        rows = self.store.list_capability()
        tally: dict[str, dict[str, int]] = {"anpr": {}, "vehicle": {},
                                            "presence": {}}
        for r in rows:
            if r["time_band"] != str(TimeBand.ALL):
                continue
            for key, col in (("anpr", "anpr_grade"), ("vehicle", "vehicle_reid_grade"),
                             ("presence", "presence_grade")):
                g = r.get(col) or "UNKNOWN"
                tally[key][g] = tally[key].get(g, 0) + 1
        return {"policy": asdict(self.policy), "grades": tally,
                "cameras_graded": len({r["camera_id"] for r in rows})}


#: Weighting for the single "overall" number the map uses for shading. It exists
#: only for visual ordering; every decision in the system reads the three grades,
#: never this scalar, because collapsing three independent capabilities into one
#: number is exactly the kind of false summary this project avoids.
_GRADE_VALUE = {Grade.GOOD: 1.0, Grade.DEGRADED: 0.5,
                Grade.UNSUITABLE: 0.0, Grade.UNKNOWN: 0.0}


def _is_person(o: VehicleObservation) -> bool:
    return (o.object_type or "").lower() == "person"


def _overall(anpr: Grade, vehicle: Grade, presence: Grade) -> float | None:
    if Grade.UNKNOWN in (anpr, vehicle, presence):
        known = [g for g in (anpr, vehicle, presence) if g is not Grade.UNKNOWN]
        if not known:
            return None
        return sum(_GRADE_VALUE[g] for g in known) / len(known)
    return (0.5 * _GRADE_VALUE[anpr] + 0.3 * _GRADE_VALUE[vehicle]
            + 0.2 * _GRADE_VALUE[presence])


def _is_person(o: VehicleObservation) -> bool:
    return (o.object_type or "").lower() == "person"


def _r(v: Any, places: int) -> float | None:
    return None if v is None else round(float(v), places)


def utc(us: int | None) -> datetime | None:
    return from_us(us) if us else datetime.now(UTC)
