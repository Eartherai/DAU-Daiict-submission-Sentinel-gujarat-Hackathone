"""Physical schema.

One schema definition, two dialects. SQLite is the development store because
PostgreSQL cannot run on the development machine; PostgreSQL + PostGIS + pgvector
is the deployment store. Everything above this module talks to the repository
interface and never to a dialect.

Deliberate choices:

* **Vectors are stored as bytes, not as a native vector type.** At PoC scale
  (~10^4-10^5 observations) an exact numpy scan is sub-millisecond and *more*
  accurate than an ANN index. The pgvector / Qdrant path exists in
  ``migrations/postgres.sql`` and behind ``VectorIndex``; swapping it does not
  touch the query layer.
* **Times are stored as epoch microseconds (INTEGER), not as strings.** Ordering
  and range scans are the hot path, and dialect-dependent timestamp parsing is a
  reliable source of subtle bugs across SQLite and Postgres.
* **``dedup_key`` is UNIQUE.** Idempotent ingestion is not optional: offline
  districts replay their queue on reconnect, and at-least-once delivery must not
  duplicate observations.
"""
from __future__ import annotations

from sqlalchemy import (
    BLOB,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# --------------------------------------------------------------------------- #
# Model 1 — the registry. The spine: everything else references a camera.
# --------------------------------------------------------------------------- #
cameras = Table(
    "cameras", metadata,
    Column("camera_id", String(64), primary_key=True),
    Column("name", String(200)),
    Column("department", String(120), index=True),
    Column("district", String(120), index=True),
    Column("site", String(200)),
    Column("lat", Float), Column("lon", Float),
    #: How the coordinate was obtained, and how far to trust it. A position
    #: derived from a camera's name places it near the right junction; it is not
    #: a surveyed position and must never be read as evidence of where a vehicle
    #: was. CATALOGUE supersedes DERIVED_FROM_NAME whenever the authoritative
    #: catalogue becomes reachable.
    Column("location_basis", String(24), default="UNKNOWN"),
    #: LANDMARK ~150 m · LOCALITY ~1.5 km · CITY ~6 km · UNKNOWN
    Column("location_precision", String(16), default="UNKNOWN"),
    #: Free text recording what a position rests on, in the operator's words or
    #: the system's — for example signage read from the camera's own view that
    #: agrees, or conspicuously disagrees, with the recorded label. Kept beside
    #: the coordinates so anyone relying on a position can see its support
    #: without leaving the screen. Never itself a position.
    Column("location_note", Text),
    Column("vendor", String(120)), Column("model_name", String(120)),
    Column("camera_type", String(60)), Column("vms", String(120)),
    Column("rtsp_url", Text), Column("hls_url", Text), Column("whep_url", Text),
    Column("codec", String(24)), Column("width", Integer), Column("height", Integer),
    Column("declared_fps", Float),
    Column("storage_location", String(200)), Column("retention_days", Integer),
    Column("compliance_er_stqc", String(24), default="NOT_ASSESSED"),
    Column("tier", String(16), default="UNASSIGNED", index=True),
    Column("enabled", Boolean, default=True),
    Column("quality_note", Text),
    Column("owner", String(160)),
    Column("region", String(120), index=True),
    Column("road", String(200)),
    Column("integration_model", String(40)),
    Column("maintenance_status", String(40)),
    Column("access_state", String(40)),
    #: GOVERNMENT | OWN_FEED | SYNTHETIC_CONTROL — never implied by silence.
    Column("source_domain", String(32)),
    Column("created_at_us", Integer), Column("updated_at_us", Integer),
)

camera_health = Table(
    "camera_health", metadata,
    Column("camera_id", String(64), ForeignKey("cameras.camera_id"), primary_key=True),
    Column("state", String(24)), Column("reachable", Boolean),
    Column("connects", Integer, default=0), Column("reconnects", Integer, default=0),
    Column("frames", Integer, default=0), Column("decoder_errors", Integer, default=0),
    Column("pts_regressions", Integer, default=0),
    Column("pts_forward_jumps", Integer, default=0),
    Column("segment_breaks", Integer, default=0), Column("scene_cuts", Integer, default=0),
    Column("warmup_frames_suppressed", Integer, default=0),
    Column("open_failures", Integer, default=0),
    Column("measured_fps", Float), Column("clock_drift_s", Float, default=0.0),
    Column("last_seen_us", Integer), Column("last_error", Text),
    Column("updated_at_us", Integer),
)

#: Capability is per camera *and per time band* — a camera that reads plates at
#: noon may be useless at 21:00, and collapsing that into one grade is exactly
#: the false confidence this system exists to avoid.
# --------------------------------------------------------------------------- #
# Timebase health and time clustering.
#
# Discovered on the live Gujarat grid: twelve cameras replay a common window
# while others are hours or weeks apart, and ten burn no clock at all. Whether
# two observations may be correlated across cameras is therefore a *property of
# the pair*, not a global assumption — and getting it wrong produces a journey
# spanning seven weeks presented as evidence.
#
# Nothing here is ever used for ordering. Ordering is PTS, always.
# --------------------------------------------------------------------------- #
camera_timebase = Table(
    "camera_timebase", metadata,
    Column("camera_id", String(64), ForeignKey("cameras.camera_id"),
           primary_key=True),
    #: OK | DEGRADED | UNRELIABLE | UNKNOWN — from measured PTS behaviour.
    Column("pts_health", String(16), default="UNKNOWN"),
    Column("pts_regressions", Integer, default=0),
    Column("pts_forward_jumps", Integer, default=0),
    Column("realtime_ratio", Float),
    Column("measured_fps", Float),
    Column("mean_interframe_gap_s", Float),
    Column("max_interframe_gap_s", Float),
    #: PRESENT | ABSENT | UNKNOWN. A burned-in clock is the *scene's* time and
    #: is never authoritative; it is recorded because its absence or its
    #: disagreement is itself operational information.
    Column("overlay_clock", String(16), default="UNKNOWN"),
    Column("overlay_reading", String(64)),
    Column("overlay_read_at_us", Integer),
    #: Seconds the scene clock leads or lags the cluster reference, where it
    #: could be read at all. Diagnostic only.
    Column("scene_offset_s", Float),
    #: Cluster membership. NULL means "not established", which restricts
    #: cross-camera correlation rather than permitting it.
    Column("time_cluster", String(40)),
    Column("cluster_confidence", String(16), default="UNKNOWN"),
    Column("evidence", Text),
    Column("updated_at_us", Integer),
)

time_clusters = Table(
    "time_clusters", metadata,
    Column("cluster_id", String(40), primary_key=True),
    Column("label", String(120)),
    #: How membership was established: MEASURED_OVERLAY | DECLARED | INFERRED.
    #: Recorded because a declared cluster and a measured one carry different
    #: weight, and an investigator is entitled to know which they are relying on.
    Column("basis", String(24), default="DECLARED"),
    Column("reference_time", String(64)),
    Column("member_count", Integer, default=0),
    Column("max_skew_s", Float),
    Column("note", Text),
    Column("created_at_us", Integer), Column("updated_at_us", Integer),
)

camera_capability = Table(
    "camera_capability", metadata,
    Column("camera_id", String(64), ForeignKey("cameras.camera_id"), primary_key=True),
    Column("time_band", String(16), primary_key=True),   # DAY | NIGHT | LOW_LIGHT
    Column("samples", Integer, default=0),
    Column("sharpness", Float), Column("luminance", Float),
    Column("mean_luma", Float), Column("glare", Float),
    Column("contrast", Float), Column("scene_stability", Float),
    Column("vehicle_yield", Float), Column("plate_yield", Float),
    #: The numerator behind plate_yield. A rate of 0.002 renders as 0.00 at two
    #: decimal places, which reads as "never read a plate" for a camera that
    #: has read one. The count keeps nought distinguishable from nearly-nought.
    Column("plate_reads", Integer),
    Column("anpr_grade", String(12), default="UNKNOWN"),
    Column("vehicle_reid_grade", String(12), default="UNKNOWN"),
    #: Can this camera reliably tell us a vehicle was here at all? Kept separate
    #: from the two above because it is the capability most cameras on a mixed
    #: government estate actually have, and the one an investigator can still
    #: use when the other two are UNSUITABLE.
    Column("presence_grade", String(12), default="UNKNOWN"),
    Column("evidence", Text),                            # JSON: why this grade
    Column("first_sample_us", Integer), Column("last_sample_us", Integer),
    Column("overall", Float),
    Column("usable_for", Text),                          # JSON array
    Column("updated_at_us", Integer),
)

# --------------------------------------------------------------------------- #
# Intelligence — observations are the atom of the whole system.
# --------------------------------------------------------------------------- #
observations = Table(
    "observations", metadata,
    Column("observation_id", String(40), primary_key=True),
    #: Idempotency. camera:segment:sequence — see CanonicalEvent.dedup_key().
    Column("dedup_key", String(160), nullable=False),
    Column("camera_id", String(64), ForeignKey("cameras.camera_id"), nullable=False),
    Column("department", String(120)),
    Column("district", String(120)),

    #: Local to (camera, segment). NOT a statewide identity — the distinction is
    #: load-bearing and is enforced by never joining on this across cameras.
    Column("track_id", String(64), index=True),
    Column("segment_id", String(40)),

    Column("pts_s", Float, nullable=False),
    Column("t_norm_us", Integer, nullable=False),        # normalised timeline
    Column("t_ingest_us", Integer, nullable=False),      # arrival; diagnostics only

    Column("lat", Float), Column("lon", Float),

    Column("object_type", String(24), default="unknown"),
    Column("bbox_x1", Float), Column("bbox_y1", Float),
    Column("bbox_x2", Float), Column("bbox_y2", Float),
    Column("detection_confidence", Float),

    Column("plate", String(24)),                          # canonical, e.g. GJ05AB1234
    Column("plate_raw", String(48)),                      # exactly what OCR returned
    Column("plate_confidence", Float),
    Column("plate_votes", Integer, default=0),

    Column("colour", String(24)), Column("colour_confidence", Float),
    Column("make", String(60)), Column("model_name", String(60)),
    Column("direction_deg", Float),

    #: float16 bytes. Exact scan at PoC scale; ANN index at pilot scale.
    Column("embedding", BLOB),
    Column("embedding_dim", Integer),
    Column("embedding_model", String(80)),

    #: Per-observation quality. A grade-C camera still produces occasional
    #: excellent crops; scoring them identically discards information.
    Column("observation_quality", Float),
    Column("plate_pixel_width", Float),
    Column("sharpness", Float), Column("luminance", Float),
    Column("mean_luma", Float),          # brightness, not exposure quality
    Column("mean_chroma", Float),        # ~0 means a monochrome / IR frame
    Column("source_quality", Float),
    Column("source_grade", String(12)),

    Column("model_versions", Text),                       # JSON
    Column("evidence_ref", String(40)),
    Column("created_at_us", Integer),
    UniqueConstraint("dedup_key", name="uq_observations_dedup"),
)

# The three access patterns that must be fast, in order of use:
#   1. "where has this plate been"      -> plate + time
#   2. "what did this camera see then"  -> camera + time
#   3. "what happened in this window"   -> time
Index("ix_obs_plate_time", observations.c.plate, observations.c.t_norm_us)
Index("ix_obs_camera_time", observations.c.camera_id, observations.c.t_norm_us)
Index("ix_obs_time", observations.c.t_norm_us)
Index("ix_obs_ingest_time", observations.c.t_ingest_us)
Index("ix_obs_object_type", observations.c.object_type)
Index("ix_obs_district_time", observations.c.district, observations.c.t_norm_us)
Index("ix_obs_track", observations.c.camera_id, observations.c.track_id)

#: Every raw OCR attempt, kept even when rejected. Voting decides what is
#: published; forensics needs to see what was discarded and why.
plate_reads = Table(
    "plate_reads", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("camera_id", String(64), nullable=False),
    Column("track_id", String(64)),
    Column("segment_id", String(40)),
    Column("pts_s", Float, nullable=False),
    Column("t_norm_us", Integer, nullable=False),
    Column("raw_text", String(48)),
    Column("canonical", String(24)),
    Column("valid", Boolean, default=False),
    Column("reject_reason", String(120)),
    Column("ocr_confidence", Float),
    Column("det_confidence", Float),
    Column("plate_pixel_width", Float),
    Column("created_at_us", Integer),
)
Index("ix_reads_track", plate_reads.c.camera_id, plate_reads.c.track_id)
Index("ix_reads_canon_time", plate_reads.c.canonical, plate_reads.c.t_norm_us)

# --------------------------------------------------------------------------- #
# Camera Link Model — learned transitions. Prior art (AI City Challenge), and
# labelled as such; the value here is that it bootstraps with no survey.
# --------------------------------------------------------------------------- #
camera_transitions = Table(
    "camera_transitions", metadata,
    Column("from_camera", String(64), primary_key=True),
    Column("to_camera", String(64), primary_key=True),
    Column("support_count", Integer, default=0),
    Column("travel_p05_s", Float), Column("travel_p50_s", Float),
    Column("travel_p95_s", Float),
    Column("travel_mean_s", Float), Column("travel_std_s", Float),
    Column("gis_distance_m", Float),
    Column("confidence", Float, default=0.0),
    Column("source", String(24), default="observed"),     # observed | gis_seed
    Column("updated_at_us", Integer),
)
Index("ix_trans_from", camera_transitions.c.from_camera,
      camera_transitions.c.support_count)

#: Raw transition samples, so distributions can be recomputed rather than only
#: incrementally updated (incremental-only statistics cannot be audited).
transition_samples = Table(
    "transition_samples", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("from_camera", String(64), nullable=False),
    Column("to_camera", String(64), nullable=False),
    Column("plate", String(24)),
    Column("dt_s", Float, nullable=False),
    Column("t_norm_us", Integer),
    Column("created_at_us", Integer),
)
Index("ix_tsamples_pair", transition_samples.c.from_camera,
      transition_samples.c.to_camera)

# --------------------------------------------------------------------------- #
# Watchlist — representative data only. Live government sources are adapters.
# --------------------------------------------------------------------------- #
watchlist = Table(
    "watchlist", metadata,
    Column("watchlist_id", String(40), primary_key=True),
    Column("entity_type", String(24), default="vehicle"),
    Column("plate", String(24), index=True),
    Column("attributes", Text),                           # JSON
    Column("category", String(40), nullable=False),
    Column("authority", String(200), nullable=False),     # who authorised it
    Column("reason", Text, nullable=False),               # why it exists
    Column("priority", String(16), default="MEDIUM"),
    Column("jurisdiction", String(120)),
    Column("valid_from_us", Integer), Column("valid_until_us", Integer),
    Column("version", Integer, default=1),
    Column("status", String(16), default="ACTIVE"),       # ACTIVE | REVOKED | EXPIRED
    Column("source_system", String(60), default="REPRESENTATIVE"),
    Column("created_by", String(120)), Column("approved_by", String(120)),
    Column("revoked_by", String(120)), Column("revoked_reason", Text),
    Column("created_at_us", Integer), Column("updated_at_us", Integer),
)

alerts = Table(
    "alerts", metadata,
    Column("alert_id", String(40), primary_key=True),
    Column("watchlist_id", String(40)),
    Column("observation_id", String(40)),
    Column("camera_id", String(64)),
    Column("plate", String(24), index=True),
    Column("category", String(40)), Column("priority", String(16)),
    Column("confidence", Float),
    Column("source_quality", Float),
    Column("match_reason", Text),                         # JSON decomposition
    Column("recommended_action", Text),
    Column("status", String(24), default="OPEN"),         # OPEN|ACK|CLEARED|FALSE_POSITIVE
    Column("acknowledged_by", String(120)), Column("acknowledged_at_us", Integer),
    Column("cleared_reason", Text),
    Column("t_norm_us", Integer, index=True),
    Column("created_at_us", Integer),
    # The lifecycle beyond "acknowledged". Officers could acknowledge an alert
    # and nothing else: the Resolved tab could never fill, and nothing recorded
    # whether a closed hit was a real vehicle, a misread or a lawful owner.
    # All nullable, so an existing store gains them in place at startup.
    Column("disposition", String(24)),       # confirmed | false_positive | cleared
    Column("case_id", String(80)),           # attached when marked investigating
    Column("lifecycle", Text),               # JSON list: who did what, when, why
    Column("updated_at_us", Integer),
)

# --------------------------------------------------------------------------- #
# Evidence — hash-chained. Tamper-evidence, not blockchain.
# --------------------------------------------------------------------------- #
evidence = Table(
    "evidence", metadata,
    Column("evidence_id", String(40), primary_key=True),
    Column("observation_id", String(40), index=True),
    Column("camera_id", String(64)),
    Column("pts_s", Float), Column("t_norm_us", Integer),
    Column("frame_path", Text), Column("frame_sha256", String(64)),
    Column("clip_path", Text), Column("clip_sha256", String(64)),
    Column("pipeline_version", String(80)),
    Column("model_versions", Text),                       # JSON
    Column("capture_method", Text),
    Column("device", String(120)),
    Column("source_quality", Float),
    Column("prev_hash", String(64)), Column("entry_hash", String(64)),
    Column("bsa_s63_status", String(32), default="DRAFT_PENDING_SIGNATURE"),
    Column("created_at_us", Integer),
)

#: A department's rule for a camera: a zone drawn on its frame, the hours it
#: applies and the classes it concerns. "Intrusion" is a judgement about
#: permission this platform cannot make on its own; a rule is the department
#: making it, and the platform reports entries against the rule it was given.
zone_rules = Table(
    "zone_rules", metadata,
    Column("rule_id", String(40), primary_key=True),
    Column("camera_id", String(64), ForeignKey("cameras.camera_id"), index=True),
    Column("name", String(120)),
    Column("polygon", Text),                               # JSON [[x, y], ...] in frame pixels
    Column("active_from", String(5)), Column("active_to", String(5)),   # IST HH:MM, or null = always
    Column("classes", Text),                               # JSON ["person"] / ["vehicle"]
    Column("reason", Text), Column("authority", Text),
    Column("status", String(16), default="ACTIVE"),
    Column("created_by", String(120)), Column("created_at_us", Integer),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor", String(120), nullable=False),
    Column("role", String(60)),
    Column("action", String(60), nullable=False),
    Column("case_id", String(60)),
    Column("purpose", Text),                              # purpose-bound search
    Column("target", Text),
    Column("result_count", Integer),
    Column("jurisdiction", String(120)),
    Column("prev_hash", String(64)), Column("entry_hash", String(64)),
    Column("t_us", Integer, nullable=False),
)
Index("ix_audit_actor_time", audit_log.c.actor, audit_log.c.t_us)
# Added after `make queryplan` showed the case-file export falling back to a
# full scan of the audit log. Every other index in this file has a plan behind
# it in var/reports/query_plans.json; this one has a before and an after.
Index("ix_audit_case", audit_log.c.case_id, audit_log.c.id)

# Geospatial lookup for the map. A bounding-box query is `lat BETWEEN ? AND ?
# AND lon BETWEEN ? AND ?`; with lat leading, the planner range-scans on
# latitude and filters longitude, which on a state-shaped estate is the more
# selective of the two. Justified by the query plans in docs/PERFORMANCE.md,
# not added on principle.
Index("ix_cameras_geo", cameras.c.lat, cameras.c.lon)
Index("ix_cameras_district_tier", cameras.c.district, cameras.c.tier)
Index("ix_alerts_status_time", alerts.c.status, alerts.c.t_norm_us)


# --------------------------------------------------------------------------- #
# Access control.
#
# Purpose limitation is the design point, not authentication. A police officer
# with a valid login is *still* not entitled to run an arbitrary vehicle search:
# the search must be attached to a case and a stated purpose, and that binding
# has to survive into the audit record. Enforcing it at the schema level means a
# purposeless search cannot be recorded, so it cannot be performed.
#
# No password, token or key is stored in plaintext. `token_sha256` is the hash
# of a bearer token that is displayed exactly once when it is minted.
# --------------------------------------------------------------------------- #
users = Table(
    "users", metadata,
    Column("user_id", String(64), primary_key=True),
    Column("display_name", String(160)),
    Column("role", String(32), nullable=False),
    Column("department", String(120)),
    #: JSON array. Empty means statewide, which only STATE-scope roles may hold.
    Column("districts", Text),
    Column("badge_no", String(60)),
    Column("enabled", Boolean, default=True),
    Column("created_at_us", Integer), Column("updated_at_us", Integer),
)

api_tokens = Table(
    "api_tokens", metadata,
    Column("token_id", String(40), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.user_id"), nullable=False),
    Column("token_sha256", String(64), nullable=False, unique=True),
    Column("label", String(120)),
    Column("issued_at_us", Integer), Column("expires_at_us", Integer),
    Column("revoked", Boolean, default=False),
    Column("last_used_at_us", Integer),
)
Index("ix_tokens_user", api_tokens.c.user_id)

# --------------------------------------------------------------------------- #
# Investigation cases. Deliberately minimal: a case is a container that binds
# searches to a purpose and collects what was found. This is not a
# case-management product and does not try to be one.
# --------------------------------------------------------------------------- #
cases = Table(
    "cases", metadata,
    Column("case_id", String(60), primary_key=True),
    Column("title", String(200), nullable=False),
    Column("fir_number", String(80)),
    Column("district", String(120), index=True),
    Column("classification", String(60)),
    Column("status", String(24), default="OPEN"),          # OPEN | CLOSED
    Column("opened_by", String(64), nullable=False),
    Column("purpose", Text, nullable=False),
    Column("closed_by", String(64)), Column("closed_reason", Text),
    Column("created_at_us", Integer), Column("updated_at_us", Integer),
)

case_items = Table(
    "case_items", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(60), ForeignKey("cases.case_id"), nullable=False),
    #: target | observation | trajectory | alert | evidence | camera
    Column("item_type", String(24), nullable=False),
    Column("item_ref", String(80), nullable=False),
    Column("payload", Text),                               # JSON snapshot
    Column("added_by", String(64)), Column("note", Text),
    Column("created_at_us", Integer),
    UniqueConstraint("case_id", "item_type", "item_ref", name="uq_case_item"),
)
Index("ix_case_items", case_items.c.case_id, case_items.c.item_type)

case_notes = Table(
    "case_notes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String(60), ForeignKey("cases.case_id"), nullable=False),
    Column("author", String(64), nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at_us", Integer),
)
Index("ix_case_notes", case_notes.c.case_id, case_notes.c.created_at_us)

# --------------------------------------------------------------------------- #
# Edge durable queue.
#
# An edge node that loses its uplink must keep working, and must lose nothing.
# `dedup_key` carries the same value as the observation it describes, so a
# replayed batch collapses onto the same row centrally — at-least-once delivery
# with idempotent application, rather than exactly-once delivery, which does not
# exist over an unreliable link.
# --------------------------------------------------------------------------- #
edge_queue = Table(
    "edge_queue", metadata,
    Column("event_id", String(40), primary_key=True),
    Column("node_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("camera_id", String(64)),
    Column("pts_s", Float),
    Column("dedup_key", String(160), nullable=False),
    Column("payload", Text, nullable=False),               # JSON
    Column("created_at_us", Integer, nullable=False),
    #: PENDING | ACKED | FAILED. Never deleted on send — acknowledged, so a lost
    #: acknowledgement replays rather than silently dropping the event.
    Column("state", String(16), default="PENDING"),
    Column("attempts", Integer, default=0),
    Column("last_error", Text),
    Column("acked_at_us", Integer),
    UniqueConstraint("node_id", "sequence", name="uq_edge_seq"),
)
Index("ix_edge_state", edge_queue.c.state, edge_queue.c.sequence)

edge_nodes = Table(
    "edge_nodes", metadata,
    Column("node_id", String(64), primary_key=True),
    Column("site", String(160)),
    Column("district", String(120)),
    Column("last_sync_us", Integer),
    Column("last_ack_sequence", Integer, default=0),
    Column("watchlist_version", String(40)),
    Column("state", String(24), default="UNKNOWN"),
    Column("updated_at_us", Integer),
)


ALL_TABLES = [
    cameras, camera_health, camera_capability, observations, plate_reads,
    camera_transitions, transition_samples, watchlist, alerts, evidence, audit_log,
    users, api_tokens, cases, case_items, case_notes, edge_queue, edge_nodes,
    camera_timebase, time_clusters,
]
