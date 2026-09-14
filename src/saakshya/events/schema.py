"""CCTV-EVENT v1 — the canonical event schema.

This is the contract between the edge analytics plane and everything upstream.
It is frozen: additive changes only, and `schema_version` is mandatory so a
regional node running an older build stays readable by the centre.

Design notes that matter for the evaluation:

* `pts_s` and `t_norm` are both carried. `pts_s` is ground truth from the
  stream; `t_norm` is the projected normalised timeline. Downstream motion
  reasoning uses `t_norm`; forensic verification uses `pts_s` + `segment_id`.
* `source_quality` travels *with the event*. A consumer must never have to
  join back to the registry to know how much to trust a record — that is what
  makes quality-conditioned confidence cheap at query time.
* `embedding` is not inlined. Events are small and go over constrained links;
  vectors are referenced and shipped on a separate, droppable channel.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Literal["cctv-event/1"] = "cctv-event/1"


class EventType(StrEnum):
    CAMERA_HEALTH = "camera.health"
    SEGMENT_BREAK = "camera.segment_break"
    VEHICLE_DETECTED = "vehicle.detected"
    PLATE_READ = "plate.read"
    TRACK_CLOSED = "vehicle.track_closed"
    WATCHLIST_HIT = "watchlist.hit"
    ALERT_CREATED = "alert.created"
    EVIDENCE_CREATED = "evidence.created"


class ObjectType(StrEnum):
    CAR = "car"
    MOTORCYCLE = "motorcycle"
    BUS = "bus"
    TRUCK = "truck"
    AUTORICKSHAW = "autorickshaw"
    PERSON = "person"
    UNKNOWN = "unknown"


class SourceQuality(BaseModel):
    """Quality of the *source* at the moment of capture, not of the model.

    Kept deliberately separate from model confidence. Collapsing them into one
    number is the thing this system exists to avoid.
    """

    model_config = ConfigDict(extra="forbid")

    grade: Literal["A", "B", "C", "D", "UNKNOWN"] = "UNKNOWN"
    sharpness: float | None = Field(None, ge=0.0, le=1.0)
    luminance: float | None = Field(None, ge=0.0, le=1.0)
    glare: float | None = Field(None, ge=0.0, le=1.0)
    score: float | None = Field(None, ge=0.0, le=1.0, description="Aggregate 0-1")
    evidence_count: int = Field(
        0, description="Samples behind this grade; 0 => insufficient evidence"
    )

    @property
    def sufficient_evidence(self) -> bool:
        return self.evidence_count >= 30


class Attributes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: str | None = None
    colour_confidence: float | None = Field(None, ge=0.0, le=1.0)
    vehicle_type: ObjectType | None = None
    make: str | None = None
    model_name: str | None = None
    direction_deg: float | None = Field(None, ge=0.0, lt=360.0)
    speed_px_s: float | None = None


class ModelVersions(BaseModel):
    """Provenance. An investigator must be able to answer 'what produced this?'"""

    model_config = ConfigDict(extra="forbid")
    pipeline: str
    detector: str | None = None
    tracker: str | None = None
    plate_detector: str | None = None
    ocr: str | None = None
    embedder: str | None = None


class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)


class CanonicalEvent(BaseModel):
    """One observation on the wire. Target size < 1 KB excluding thumbnail."""

    model_config = ConfigDict(extra="forbid")

    # --- identity & ordering -------------------------------------------------
    event_id: str
    schema_version: Literal["cctv-event/1"] = SCHEMA_VERSION
    sequence: int = Field(..., description="Per-camera monotonic; drives idempotent ingest")

    # --- provenance of place & time -----------------------------------------
    camera_id: str
    department_id: str | None = None
    segment_id: str = Field(..., description="Changes on every stream discontinuity")
    pts_s: float = Field(..., description="Stream presentation timestamp, seconds")
    t_norm: datetime = Field(
        ..., description="Normalised timeline; use this for motion reasoning"
    )
    t_ingest: datetime = Field(
        ..., description="Wall-clock arrival; diagnostics only"
    )
    location: GeoPoint | None = None

    # --- what was seen -------------------------------------------------------
    event_type: EventType
    object_type: ObjectType = ObjectType.UNKNOWN
    track_id: str | None = Field(
        None, description="Local to camera+segment. NOT a statewide identity."
    )
    bbox: tuple[float, float, float, float] | None = Field(
        None, description="xyxy normalised 0-1"
    )
    detection_confidence: float | None = Field(None, ge=0.0, le=1.0)

    plate: str | None = Field(
        None, description="Canonical normalised form, e.g. GJ05AB1234"
    )
    plate_raw: str | None = Field(
        None, description="Exactly what OCR returned, before normalisation"
    )
    plate_confidence: float | None = Field(None, ge=0.0, le=1.0)
    plate_frame_votes: int = Field(
        0, description="Frames that contributed to the voted read"
    )

    attributes: Attributes = Field(default_factory=Attributes)

    # --- references (never inlined) -----------------------------------------
    embedding_ref: str | None = None
    evidence_ref: str | None = None

    # --- trust ---------------------------------------------------------------
    source_quality: SourceQuality = Field(default_factory=SourceQuality)
    model_versions: ModelVersions

    extra: dict[str, Any] = Field(default_factory=dict)

    def dedup_key(self) -> str:
        """Idempotency key for at-least-once delivery after an offline replay."""
        return f"{self.camera_id}:{self.segment_id}:{self.sequence}"
