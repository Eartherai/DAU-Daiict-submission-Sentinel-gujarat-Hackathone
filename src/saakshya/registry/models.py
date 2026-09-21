"""Model 1 — the camera registry.

Model 1 is compulsory for every submission and must be combined with at least
one other model. It is treated here as the spine of the system rather than a map
screen: every other plane reads camera identity, geometry, health and
*capability* from this registry.

The distinction that matters: most registries record what a camera **is**
(vendor, resolution, location). This one also records what a camera can
currently **do**, measured continuously from its own stream. On an estate where
most cameras were installed by Health, Panchayat, GSRTC and Municipal
departments for local supervision — never for plate reading — that difference is
the whole point.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from saakshya.common.clock import utc_now


class Grade(StrEnum):
    """Capability grade. UNKNOWN is a first-class value, not a failure.

    A camera with too few samples is reported as UNKNOWN with an explicit
    evidence count. Fabricating a grade from three frames would be exactly the
    kind of false confidence this system exists to avoid.
    """

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


class Analytic(StrEnum):
    PRESENCE = "PRESENCE"
    VEHICLE_DETECT = "VEHICLE_DETECT"
    VEHICLE_REID = "VEHICLE_REID"
    ANPR = "ANPR"


class ComplianceStatus(StrEnum):
    """MeitY Essential Requirements / STQC status.

    Network CCTV cameras and recorders sold, manufactured or imported in India
    must be ER-compliant and STQC-certified; the concession for older stock was
    withdrawn in January 2026. A statewide estate therefore has to be able to
    answer "which of these 80,000 devices are non-compliant" — and no VMS tracks
    it. We carry it as first-class registry metadata.

    NOT_ASSESSED is the honest default. We do not infer compliance.
    """

    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    EXEMPT = "EXEMPT"
    NOT_ASSESSED = "NOT_ASSESSED"


class TimeBand(StrEnum):
    """Capability varies by lighting. Grading a camera once, at noon, is useless."""

    DAY = "DAY"
    NIGHT = "NIGHT"
    LOW_LIGHT = "LOW_LIGHT"


class CapabilityVector(BaseModel):
    """What this camera can actually deliver, measured — not declared."""

    model_config = ConfigDict(extra="forbid")

    time_band: TimeBand = TimeBand.DAY
    samples: int = Field(0, description="Frames behind these numbers")

    sharpness: float | None = Field(None, ge=0.0, le=1.0)
    luminance: float | None = Field(None, ge=0.0, le=1.0)
    glare: float | None = Field(None, ge=0.0, le=1.0)
    scene_stability: float | None = Field(None, ge=0.0, le=1.0)
    contrast: float | None = Field(None, ge=0.0, le=1.0)

    vehicle_yield: float | None = Field(None, description="Vehicle detections per minute")
    plate_yield: float | None = Field(
        None, ge=0.0, le=1.0,
        description="Reads above confidence threshold per vehicle detection",
    )

    anpr_grade: Grade = Grade.UNKNOWN
    vehicle_reid_grade: Grade = Grade.UNKNOWN
    overall: float | None = Field(None, ge=0.0, le=1.0)
    usable_for: list[Analytic] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    #: Minimum samples before we are willing to publish a grade at all.
    MIN_SAMPLES: int = Field(120, exclude=True)

    @property
    def sufficient_evidence(self) -> bool:
        return self.samples >= self.MIN_SAMPLES

    def explain(self) -> str:
        if not self.sufficient_evidence:
            return (f"Insufficient evidence — {self.samples} samples "
                    f"(need {self.MIN_SAMPLES}). No grade asserted.")
        bits = []
        if self.sharpness is not None:
            bits.append(f"sharpness {self.sharpness:.2f}")
        if self.luminance is not None:
            bits.append(f"luminance {self.luminance:.2f}")
        if self.plate_yield is not None:
            bits.append(f"plate yield {self.plate_yield:.2f}")
        return f"ANPR {self.anpr_grade} ({self.time_band}): " + ", ".join(bits)


class StreamHealth(BaseModel):
    """Live transport health. Every field is a real counter from the stream layer."""

    model_config = ConfigDict(extra="forbid")

    state: str = "unknown"
    reachable: bool = False
    connects: int = 0
    reconnects: int = 0
    frames: int = 0
    decoder_errors: int = 0
    pts_regressions: int = 0
    pts_forward_jumps: int = 0
    segment_breaks: int = 0
    scene_cuts: int = 0
    warmup_frames_suppressed: int = 0
    open_failures: int = 0
    declared_fps: float | None = None
    measured_fps: float | None = None
    clock_drift_s: float = 0.0
    last_seen: datetime | None = None
    last_error: str | None = None

    @property
    def fps_discrepancy(self) -> float | None:
        """Declared vs measured. The guide warns declared fps is not trustworthy;
        we surface the gap instead of silently believing either number."""
        if self.declared_fps and self.measured_fps:
            return round(abs(self.declared_fps - self.measured_fps), 2)
        return None

    @property
    def timestamp_health(self) -> Literal["OK", "DRIFTING", "SUSPECT", "UNKNOWN"]:
        if self.frames == 0:
            return "UNKNOWN"
        if self.pts_regressions > 0 and self.segment_breaks == 0:
            return "SUSPECT"
        if abs(self.clock_drift_s) > 2.0:
            return "DRIFTING"
        return "OK"


class Camera(BaseModel):
    """A camera as the registry knows it."""

    model_config = ConfigDict(extra="forbid")

    camera_id: str
    name: str | None = None
    department: str | None = None
    district: str | None = None
    site: str | None = None

    lat: float | None = Field(None, ge=-90.0, le=90.0)
    lon: float | None = Field(None, ge=-180.0, le=180.0)

    vendor: str | None = None
    model_name: str | None = None
    camera_type: str | None = None          # fixed | ptz | anpr | dome | analog+dvr
    vms: str | None = None                  # owning VMS/NVR, if any

    #: The catalogue is the contract; the URL pattern is not. We store all
    #: offered transports and choose at connect time.
    rtsp_url: str | None = None
    hls_url: str | None = None
    whep_url: str | None = None
    protocol: str = "rtsp"

    codec: str | None = None
    width: int | None = None
    height: int | None = None
    declared_fps: float | None = None
    bitrate_kbps: float | None = None

    storage_location: str | None = None
    retention_days: int | None = None

    compliance_er_stqc: ComplianceStatus = ComplianceStatus.NOT_ASSESSED
    compliance_note: str | None = None

    tier: Literal["A", "B", "C", "UNASSIGNED"] = "UNASSIGNED"
    enabled: bool = True

    health: StreamHealth = Field(default_factory=StreamHealth)
    capability: dict[TimeBand, CapabilityVector] = Field(default_factory=dict)

    quality_note: str | None = None
    owner: str | None = None
    region: str | None = None
    road: str | None = None
    integration_model: str | None = None  # direct_whep | rtsp_bridge | rtsp_ai | mock
    maintenance_status: str | None = None
    access_state: str | None = None
    source_domain: str | None = None  # GOVERNMENT | OWN_FEED | SYNTHETIC_CONTROL
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def resolution(self) -> str | None:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return None

    def current_capability(self, band: TimeBand = TimeBand.DAY) -> CapabilityVector:
        return self.capability.get(band, CapabilityVector(time_band=band))

    def can(self, analytic: Analytic, band: TimeBand = TimeBand.DAY) -> bool:
        """Whether this camera is worth spending compute on for this analytic.

        Returns False when evidence is insufficient *for the expensive analytics*
        but stays permissive for cheap ones — we must be able to bootstrap.
        """
        cap = self.current_capability(band)
        if analytic in (Analytic.PRESENCE, Analytic.VEHICLE_DETECT):
            return self.enabled and self.health.reachable
        if not cap.sufficient_evidence:
            return False
        return analytic in cap.usable_for

    def compute_tier(self, band: TimeBand = TimeBand.DAY) -> Literal["A", "B", "C", "UNASSIGNED"]:
        """Capability drives compute allocation, not uniform GPU per camera.

        This is what makes 80,000 cameras affordable: a camera that can never
        read a plate does not get an OCR budget.
        """
        cap = self.current_capability(band)
        if not cap.sufficient_evidence:
            return "UNASSIGNED"
        if Analytic.ANPR in cap.usable_for and cap.anpr_grade in (Grade.A, Grade.B):
            return "A"
        if Analytic.VEHICLE_REID in cap.usable_for:
            return "B"
        return "C"
