"""Repository layer.

The only place in the application that knows SQL. Everything above works with
domain objects, which is what makes SQLite→PostgreSQL a deployment decision
rather than a rewrite.

Ingestion is **idempotent by construction**: `observations.dedup_key` is UNIQUE
and inserts use an upsert that keeps the first write. An offline district that
replays its queue after a WAN outage cannot create duplicate observations, and
that property is tested rather than assumed.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import (
    Engine,
    and_,
    case,
    create_engine,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from saakshya.common.ids import new_id
from saakshya.store import schema as S

log = logging.getLogger(__name__)

EPOCH_US = 1_000_000


def to_us(dt: datetime) -> int:
    return int(dt.timestamp() * EPOCH_US)


def from_us(us: int | None) -> datetime | None:
    return datetime.fromtimestamp(us / EPOCH_US, UTC) if us else None


def from_us_required(us: int | None, field: str) -> datetime:
    """For NOT NULL timestamp columns.

    The schema guarantees these are present, so a None here means the row is
    corrupt. Failing with the field name beats propagating a None into a
    dataclass that declares the field non-optional and failing somewhere else.
    """
    t = from_us(us)
    if t is None:
        raise ValueError(f"{field} is NULL on a NOT NULL column; the row is corrupt")
    return t


def now_us() -> int:
    return int(time.time() * EPOCH_US)


def pack_vec(v: np.ndarray | None) -> bytes | None:
    """float16 on the wire and on disk: half the bytes, no measurable recall loss
    at these dimensions, and it matches the 1 KB/embedding scale assumption."""
    if v is None:
        return None
    return np.asarray(v, dtype=np.float16).tobytes()


def unpack_vec(b: bytes | None, dim: int | None) -> np.ndarray | None:
    if not b:
        return None
    v = np.frombuffer(b, dtype=np.float16).astype(np.float32)
    return v if dim is None or v.size == dim else v[:dim]


# --------------------------------------------------------------------------- #
# Domain objects
# --------------------------------------------------------------------------- #
@dataclass
class VehicleObservation:
    """One vehicle seen once, by one camera, at one time.

    The atom of the intelligence layer. Everything — search, trajectory,
    watchlist, evidence — is a function over these.
    """

    camera_id: str
    pts_s: float
    t_norm: datetime
    t_ingest: datetime
    dedup_key: str

    observation_id: str = field(default_factory=lambda: new_id("OB"))
    department: str | None = None
    district: str | None = None
    track_id: str | None = None
    segment_id: str | None = None

    lat: float | None = None
    lon: float | None = None

    object_type: str = "unknown"
    bbox: tuple[float, float, float, float] | None = None
    detection_confidence: float | None = None

    plate: str | None = None
    plate_raw: str | None = None
    plate_confidence: float | None = None
    plate_votes: int = 0

    colour: str | None = None
    colour_confidence: float | None = None
    make: str | None = None
    model_name: str | None = None
    direction_deg: float | None = None

    embedding: np.ndarray | None = None
    embedding_model: str | None = None

    observation_quality: float | None = None
    plate_pixel_width: float | None = None
    sharpness: float | None = None
    luminance: float | None = None
    mean_luma: float | None = None
    mean_chroma: float | None = None
    source_quality: float | None = None
    source_grade: str | None = None

    model_versions: dict[str, Any] = field(default_factory=dict)
    evidence_ref: str | None = None

    def row(self) -> dict[str, Any]:
        b = self.bbox or (None, None, None, None)
        return {
            "observation_id": self.observation_id, "dedup_key": self.dedup_key,
            "camera_id": self.camera_id, "department": self.department,
            "district": self.district, "track_id": self.track_id,
            "segment_id": self.segment_id, "pts_s": self.pts_s,
            "t_norm_us": to_us(self.t_norm), "t_ingest_us": to_us(self.t_ingest),
            "lat": self.lat, "lon": self.lon,
            "object_type": self.object_type,
            "bbox_x1": b[0], "bbox_y1": b[1], "bbox_x2": b[2], "bbox_y2": b[3],
            "detection_confidence": self.detection_confidence,
            "plate": self.plate, "plate_raw": self.plate_raw,
            "plate_confidence": self.plate_confidence, "plate_votes": self.plate_votes,
            "colour": self.colour, "colour_confidence": self.colour_confidence,
            "make": self.make, "model_name": self.model_name,
            "direction_deg": self.direction_deg,
            "embedding": pack_vec(self.embedding),
            "embedding_dim": int(self.embedding.size) if self.embedding is not None else None,
            "embedding_model": self.embedding_model,
            "observation_quality": self.observation_quality,
            "plate_pixel_width": self.plate_pixel_width,
            "sharpness": self.sharpness, "luminance": self.luminance,
            "mean_luma": self.mean_luma,
            "mean_chroma": self.mean_chroma,
            "source_quality": self.source_quality, "source_grade": self.source_grade,
            "model_versions": json.dumps(self.model_versions) if self.model_versions else None,
            "evidence_ref": self.evidence_ref,
            "created_at_us": now_us(),
        }

    @staticmethod
    def from_row(r: Any) -> VehicleObservation:
        m = r._mapping if hasattr(r, "_mapping") else r
        bbox = None
        if m["bbox_x1"] is not None:
            bbox = (m["bbox_x1"], m["bbox_y1"], m["bbox_x2"], m["bbox_y2"])
        return VehicleObservation(
            observation_id=m["observation_id"], dedup_key=m["dedup_key"],
            camera_id=m["camera_id"], department=m["department"], district=m["district"],
            track_id=m["track_id"], segment_id=m["segment_id"], pts_s=m["pts_s"],
            t_norm=from_us_required(m["t_norm_us"], "t_norm_us"),
            t_ingest=from_us_required(m["t_ingest_us"], "t_ingest_us"),
            lat=m["lat"], lon=m["lon"], object_type=m["object_type"], bbox=bbox,
            detection_confidence=m["detection_confidence"],
            plate=m["plate"], plate_raw=m["plate_raw"],
            plate_confidence=m["plate_confidence"], plate_votes=m["plate_votes"] or 0,
            colour=m["colour"], colour_confidence=m["colour_confidence"],
            make=m["make"], model_name=m["model_name"], direction_deg=m["direction_deg"],
            embedding=unpack_vec(m["embedding"], m["embedding_dim"]),
            embedding_model=m["embedding_model"],
            observation_quality=m["observation_quality"],
            plate_pixel_width=m["plate_pixel_width"],
            sharpness=m["sharpness"], luminance=m["luminance"],
            mean_luma=m["mean_luma"], mean_chroma=m["mean_chroma"],
            source_quality=m["source_quality"], source_grade=m["source_grade"],
            model_versions=json.loads(m["model_versions"]) if m["model_versions"] else {},
            evidence_ref=m["evidence_ref"],
        )

    def to_public(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("embedding", None)
        d["t_norm"] = self.t_norm.isoformat() if self.t_norm else None
        d["t_ingest"] = self.t_ingest.isoformat() if self.t_ingest else None
        return d


@dataclass
class SearchFilter:
    """Structured prune — stage 1 of the hybrid search.

    Runs before any embedding is touched, because structure does not suffer
    domain shift and embeddings do.
    """

    plate: str | None = None
    plate_prefix: str | None = None
    cameras: Sequence[str] | None = None
    districts: Sequence[str] | None = None
    departments: Sequence[str] | None = None
    object_types: Sequence[str] | None = None
    colours: Sequence[str] | None = None
    t_from: datetime | None = None
    t_to: datetime | None = None
    min_plate_confidence: float | None = None
    min_observation_quality: float | None = None
    has_embedding: bool | None = None
    limit: int = 500


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class Store:
    """SQLAlchemy-Core repository. Works on SQLite and PostgreSQL."""

    def __init__(self, url: str = "sqlite:///var/saakshya.db", echo: bool = False) -> None:
        if url.startswith("sqlite"):
            path = url.replace("sqlite:///", "")
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.url = url
        engine_kw: dict[str, Any] = {"echo": echo, "future": True}
        if url.startswith("sqlite"):
            # Per-connection wait. The one-shot PRAGMA below only touches the
            # first connection; ingest and the API open many. 5 s was losing
            # readers while 30 workers wrote.
            engine_kw["connect_args"] = {"timeout": 4.0, "check_same_thread": False}
        self.engine: Engine = create_engine(url, **engine_kw)
        self.is_sqlite = url.startswith("sqlite")
        #: camera_id -> (district, department, lat, lon). Observations are
        #: denormalised against this at write time so district-scoped queries
        #: hit an index instead of a join — district scoping is an access-control
        #: path, not an analytics convenience.
        self._cam_cache: dict[str, tuple] = {}
        #: Whether the bulk warm has run. Emptiness is not the same question:
        #: the cache stays non-empty while holding stale misses, and testing
        #: `if self._cam_cache` for "already warmed" is what let a camera
        #: onboarded after the warm stay invisible for the process's lifetime.
        self._cam_cache_warmed = False
        #: Camera ids confirmed absent from the registry. Observations arrive
        #: from unregistered cameras routinely, and without this a miss would
        #: issue a SELECT on every batch, for every such camera, forever.
        self._cam_cache_absent: set[str] = set()
        #: Overview used to take ~10 s because it issued a dozen COUNT scans
        #: against a growing live store. A few seconds of staleness is honest
        #: on a wall that already says the store is growing; a 10 s home
        #: screen is not.
        #:
        #: The TTL was 3 s while the computation itself took ~3.9 s against
        #: 798k observations, so the entry had always expired by the time the
        #: next caller asked for it: the cache never once returned a hit and
        #: every page load paid the full eighteen-query bill. A TTL has to be
        #: longer than the work it is caching. These are estate-wide totals
        #: that move slowly; half a minute of staleness on "798,129
        #: observations" costs an operator nothing, and it is the difference
        #: between a home screen that appears and one that arrives.
        self._stats_cache: tuple[float, dict[str, Any]] | None = None
        self._stats_ttl_s = 30.0
        self._chroma_cache: tuple[float, dict[str, float]] | None = None
        self._pub_cache: tuple[float, dict[str, dict[str, int]]] | None = None
        if self.is_sqlite:
            with self.engine.begin() as c:
                # WAL lets the analytics writer and the API reader run
                # concurrently, which the demo needs.
                c.exec_driver_sql("PRAGMA journal_mode=WAL")
                c.exec_driver_sql("PRAGMA synchronous=NORMAL")
                # 4s, not 60s: command APIs must not wait out a media writer.
                c.exec_driver_sql("PRAGMA busy_timeout=4000")

    def create_all(self) -> None:
        """Create missing tables, then add missing nullable columns.

        `metadata.create_all` creates tables and never touches an existing one,
        so every column added to the schema silently breaks every query against
        a database created before it. Found by the release gate: two advisory
        checks failed with `no such column: observations.mean_chroma` against a
        store built the day before. In development the answer was to delete the
        database. In a deployment that answer does not exist.

        Deliberately narrow. This adds **nullable columns only** — the one kind
        of change this schema actually makes, and the one kind SQLite can apply
        in place without rewriting a table. A rename, a type change or a new
        constraint is not handled here and must not be: those need a real
        migration tool with a downgrade path, and pretending otherwise would be
        worse than the gap. `pending_migrations()` reports anything it cannot
        apply rather than proceeding.
        """
        S.metadata.create_all(self.engine)
        added = self._add_missing_columns()
        if added:
            log.info("schema: added %d missing column(s): %s",
                     len(added), ", ".join(added))

    def _existing_columns(self, table: str) -> set[str]:
        with self.engine.connect() as c:
            if self.is_sqlite:
                rows = c.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
                return {r[1] for r in rows}
            rows = c.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s", (table,)).fetchall()
            return {r[0] for r in rows}

    def _add_missing_columns(self) -> list[str]:
        added: list[str] = []
        for table in S.ALL_TABLES:
            try:
                existing = self._existing_columns(table.name)
            except Exception:            # table absent; create_all handles it
                continue
            if not existing:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                if not col.nullable or col.primary_key:
                    # Not applicable in place, and not silently skipped either —
                    # pending_migrations() surfaces it.
                    continue
                ddl = col.type.compile(self.engine.dialect)
                with self.engine.begin() as c:
                    c.exec_driver_sql(
                        f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}")
                added.append(f"{table.name}.{col.name}")
        return added

    def pending_migrations(self) -> list[str]:
        """Schema differences this store cannot apply in place.

        Anything here needs a real migration with a downgrade path. Reported so
        a deployment fails loudly at startup rather than at the first query."""
        pending: list[str] = []
        for table in S.ALL_TABLES:
            try:
                existing = self._existing_columns(table.name)
            except Exception:
                continue
            if not existing:
                continue
            for col in table.columns:
                if col.name not in existing and (not col.nullable
                                                 or col.primary_key):
                    pending.append(
                        f"{table.name}.{col.name} is NOT NULL or a primary key "
                        "and cannot be added in place")
        return pending

    def drop_all(self) -> None:
        S.metadata.drop_all(self.engine)

    # -- cameras ----------------------------------------------------------- #
    #: Facts an operator establishes and a discovery pass cannot know: what a
    #: camera is called, where it is, and who owns it. Stream properties
    #: (codec, resolution, urls, tier) are the opposite — measured every run,
    #: and a fresh measurement should replace a stale one.
    CURATED_COLUMNS = frozenset({
        "name", "site", "district", "department", "lat", "lon",
        "location_precision", "location_basis", "location_note",
        "owner", "region", "road", "integration_model",
        "maintenance_status", "access_state", "source_domain",
    })

    def upsert_camera(self, cam: dict[str, Any], *,
                      clear: frozenset[str] | set[str] = frozenset()) -> None:
        """Insert or update a camera, without letting discovery erase curation.

        A probe pass knows camera ids and stream properties; it does not know
        that cam01 is Chimanbhai Bridge at 23.0296, 72.5219. It passes None for
        what it cannot see, and before this rule existed those Nones overwrote
        surveyed positions — one ingest run silently emptied the map.

        So for the curated columns, None means "I don't know", never "delete".
        A caller that genuinely means to clear a field names it in `clear`,
        which is deliberate, greppable, and cannot happen by accident.
        """
        cam = dict(cam)
        protected = self.CURATED_COLUMNS - set(clear)
        cam.setdefault("created_at_us", now_us())
        cam["updated_at_us"] = now_us()
        with self.engine.begin() as c:
            prior = c.execute(select(S.cameras).where(
                S.cameras.c.camera_id == cam["camera_id"])).first()
            if prior is not None:
                held = prior._mapping
                for col in protected:
                    if cam.get(col) is None and held.get(col) is not None:
                        cam.pop(col, None)
            else:
                # A brand-new camera still needs something to be called. Its id
                # is the only honest answer until someone names it.
                cam.setdefault("name", cam["camera_id"])

            if self.is_sqlite:
                stmt = sqlite_insert(S.cameras).values(**cam)
                upd = {k: v for k, v in cam.items() if k != "created_at_us"}
                c.execute(stmt.on_conflict_do_update(index_elements=["camera_id"], set_=upd))
            elif prior is not None:
                c.execute(update(S.cameras).where(
                    S.cameras.c.camera_id == cam["camera_id"]).values(**cam))
            else:
                c.execute(insert(S.cameras).values(**cam))
        self._cam_cache.pop(cam["camera_id"], None)   # reread; cam may be merged
        self._cam_cache_absent.discard(cam["camera_id"])

    _CAM_CTX_COLS = ("district", "department", "lat", "lon")

    def _ensure_cam_cache(self) -> None:
        if self._cam_cache_warmed:
            return
        with self.engine.connect() as c:
            for r in c.execute(select(S.cameras.c.camera_id, S.cameras.c.district,
                                      S.cameras.c.department, S.cameras.c.lat,
                                      S.cameras.c.lon)):
                self._cam_cache[r[0]] = (r[1], r[2], r[3], r[4])
        self._cam_cache_warmed = True

    def _cam_ctx(self, camera_id: str) -> tuple | None:
        """Registry context for one camera, correct after a late onboarding.

        The warm pass runs once. A camera onboarded afterwards — which is
        exactly what the evaluation asks for, and what the own-feed recording
        does on camera — would otherwise never enter the cache, and its
        observations would be stored with no district, department or position.
        That is not merely cosmetic: district is an access-control dimension,
        so those rows fall outside a scoped investigator's reach entirely.

        Reloading the whole table on every upsert would make a bulk import of
        an 80,000-camera estate quadratic, so a miss costs one indexed row read
        and is then remembered either way.
        """
        self._ensure_cam_cache()
        ctx = self._cam_cache.get(camera_id)
        if ctx is not None or camera_id in self._cam_cache_absent:
            return ctx
        with self.engine.connect() as c:
            row = c.execute(select(
                S.cameras.c.district, S.cameras.c.department,
                S.cameras.c.lat, S.cameras.c.lon,
            ).where(S.cameras.c.camera_id == camera_id)).first()
        if row is None:
            self._cam_cache_absent.add(camera_id)
            return None
        ctx = (row[0], row[1], row[2], row[3])
        self._cam_cache[camera_id] = ctx
        return ctx

    def delete_camera(self, camera_id: str) -> bool:
        """Remove a registry row. Health goes with it. Observations stay."""
        with self.engine.begin() as c:
            c.execute(delete(S.camera_health).where(
                S.camera_health.c.camera_id == camera_id))
            c.execute(delete(S.camera_capability).where(
                S.camera_capability.c.camera_id == camera_id))
            result = c.execute(delete(S.cameras).where(
                S.cameras.c.camera_id == camera_id))
        self._cam_cache.pop(camera_id, None)
        self._cam_cache_absent.discard(camera_id)
        self._stats_cache = None
        return bool(getattr(result, "rowcount", 0))

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as c:
            r = c.execute(select(S.cameras).where(
                S.cameras.c.camera_id == camera_id)).first()
            return dict(r._mapping) if r else None

    def list_cameras(self, district: str | None = None,
                     department: str | None = None) -> list[dict[str, Any]]:
        q = select(S.cameras)
        if district:
            q = q.where(S.cameras.c.district == district)
        if department:
            q = q.where(S.cameras.c.department == department)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q.order_by(S.cameras.c.camera_id))]

    def upsert_health(self, camera_id: str, health: dict[str, Any]) -> None:
        row = {k: v for k, v in health.items()
               if k in S.camera_health.c and k != "camera_id"}
        row["camera_id"] = camera_id
        row["updated_at_us"] = now_us()
        with self.engine.begin() as c:
            if self.is_sqlite:
                stmt = sqlite_insert(S.camera_health).values(**row)
                c.execute(stmt.on_conflict_do_update(
                    index_elements=["camera_id"],
                    set_={k: v for k, v in row.items() if k != "camera_id"}))
            else:
                c.execute(delete(S.camera_health).where(
                    S.camera_health.c.camera_id == camera_id))
                c.execute(insert(S.camera_health).values(**row))

    def list_health(self, camera_ids: Sequence[str] | None = None
                    ) -> dict[str, dict[str, Any]]:
        q = select(S.camera_health)
        if camera_ids is not None:
            if not camera_ids:
                return {}
            q = q.where(S.camera_health.c.camera_id.in_(list(camera_ids)))
        with self.engine.connect() as c:
            return {r._mapping["camera_id"]: dict(r._mapping) for r in c.execute(q)}

    def observed_camera_ids(self) -> set[str]:
        """Cameras that have at least one observation in this store.

        Distinct from `camera_health`. Health is persisted by ingest, and an
        unbounded run writes it on a timer and at close — a camera can have
        thousands of observations and still no health row if that process
        predates the write. Treating a missing health row as "never ingested"
        is then a lie.
        """
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(
                select(S.observations.c.camera_id).distinct())}

    def plate_publication_by_camera(self) -> dict[str, dict[str, int]]:
        """Live-store plate identity per camera, not the capability sample.

        ANPR grade is yield at this geometry. A camera graded UNSUITABLE can
        still have published a mark; Cameras and the live wall must say so
        rather than looking like the store is empty of plates.
        """
        now = time.monotonic()
        hit = self._pub_cache
        if hit is not None and now - hit[0] < self._stats_ttl_s:
            return hit[1]
        plated = and_(S.observations.c.plate.isnot(None),
                      S.observations.c.plate != "")
        with self.engine.connect() as c:
            rows = c.execute(
                select(
                    S.observations.c.camera_id,
                    func.count(func.distinct(S.observations.c.plate))
                    .label("distinct_marks"),
                    func.coalesce(func.sum(case(
                        (S.observations.c.plate_votes >= 2, 1), else_=0)), 0)
                    .label("confirmed"),
                    func.coalesce(func.sum(case(
                        (S.observations.c.plate_votes == 1, 1), else_=0)), 0)
                    .label("leads"),
                ).where(plated).group_by(S.observations.c.camera_id))
            out = {
                r.camera_id: {
                    "distinct_marks": int(r.distinct_marks or 0),
                    "confirmed": int(r.confirmed or 0),
                    "leads": int(r.leads or 0),
                }
                for r in rows
            }
        self._pub_cache = (now, out)
        return out

    def cameras_in_bbox(self, *, south: float, west: float, north: float, east: float,
                        districts: Sequence[str] | None = None,
                        departments: Sequence[str] | None = None,
                        tiers: Sequence[str] | None = None,
                        enabled_only: bool = False,
                        limit: int = 20_000) -> list[dict[str, Any]]:
        """Cameras inside a viewport. Pushed into SQL, not filtered in Python.

        The map must not degrade into "send 80,000 rows and let the browser sort
        it out", so the viewport is part of the query rather than part of the
        rendering. Cameras with no coordinates are excluded here and reported
        separately by `cameras_without_location`, because silently dropping them
        would make an incomplete map look complete.
        """
        q = select(S.cameras).where(
            S.cameras.c.lat.is_not(None), S.cameras.c.lon.is_not(None),
            S.cameras.c.lat >= south, S.cameras.c.lat <= north,
            S.cameras.c.lon >= west, S.cameras.c.lon <= east)
        if districts:
            q = q.where(S.cameras.c.district.in_(list(districts)))
        if departments:
            q = q.where(S.cameras.c.department.in_(list(departments)))
        if tiers:
            q = q.where(S.cameras.c.tier.in_(list(tiers)))
        if enabled_only:
            q = q.where(S.cameras.c.enabled.is_(True))
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q.limit(limit))]

    def cameras_unlocated(self, districts: Sequence[str] | None = None,
                          limit: int = 20_000) -> list[dict[str, Any]]:
        """Cameras with no coordinates. Real, registered, and unmappable.

        They are excluded from every viewport query by construction, so anything
        that is a *list* rather than a map has to fetch them separately or the
        estate disappears from its own inventory.
        """
        q = select(S.cameras).where(
            (S.cameras.c.lat.is_(None)) | (S.cameras.c.lon.is_(None)))
        if districts:
            q = q.where(S.cameras.c.district.in_(list(districts)))
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q.limit(limit))]

    def cameras_without_location(self, districts: Sequence[str] | None = None) -> int:
        q = select(func.count()).select_from(S.cameras).where(
            (S.cameras.c.lat.is_(None)) | (S.cameras.c.lon.is_(None)))
        if districts:
            q = q.where(S.cameras.c.district.in_(list(districts)))
        with self.engine.connect() as c:
            return int(c.execute(q).scalar() or 0)

    def camera_extent(self, districts: Sequence[str] | None = None
                      ) -> dict[str, float] | None:
        """Bounding box of the located estate, for the map's initial view."""
        q = select(func.min(S.cameras.c.lat), func.min(S.cameras.c.lon),
                   func.max(S.cameras.c.lat), func.max(S.cameras.c.lon)).where(
            S.cameras.c.lat.is_not(None), S.cameras.c.lon.is_not(None))
        if districts:
            q = q.where(S.cameras.c.district.in_(list(districts)))
        with self.engine.connect() as c:
            r = c.execute(q).first()
        if not r or r[0] is None:
            return None
        return {"south": r[0], "west": r[1], "north": r[2], "east": r[3]}

    # -- capability (measured, never declared) ------------------------------ #
    def upsert_capability(self, camera_id: str, time_band: str,
                          row: dict[str, Any]) -> None:
        vals = {k: v for k, v in row.items()
                if k in S.camera_capability.c and k not in ("camera_id", "time_band")}
        vals.update({"camera_id": camera_id, "time_band": time_band,
                     "updated_at_us": now_us()})
        with self.engine.begin() as c:
            if self.is_sqlite:
                stmt = sqlite_insert(S.camera_capability).values(**vals)
                c.execute(stmt.on_conflict_do_update(
                    index_elements=["camera_id", "time_band"],
                    set_={k: v for k, v in vals.items()
                          if k not in ("camera_id", "time_band")}))
            else:
                c.execute(delete(S.camera_capability).where(
                    S.camera_capability.c.camera_id == camera_id,
                    S.camera_capability.c.time_band == time_band))
                c.execute(insert(S.camera_capability).values(**vals))

    def list_capability(self, camera_ids: Sequence[str] | None = None,
                        time_band: str | None = None) -> list[dict[str, Any]]:
        q = select(S.camera_capability)
        if camera_ids is not None:
            if not camera_ids:
                return []
            q = q.where(S.camera_capability.c.camera_id.in_(list(camera_ids)))
        if time_band:
            q = q.where(S.camera_capability.c.time_band == time_band)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(q)]

    def observation_counts_by_camera(self, t_from: datetime | None = None,
                                     t_to: datetime | None = None
                                     ) -> dict[str, dict[str, int]]:
        """Per-camera totals in one query. Written specifically to avoid the
        N+1 that the obvious per-camera loop produces on the map endpoints."""
        q = select(S.observations.c.camera_id,
                   func.count().label("n"),
                   func.sum(case((S.observations.c.plate.is_not(None), 1), else_=0)
                            ).label("plated")).group_by(S.observations.c.camera_id)
        if t_from:
            q = q.where(S.observations.c.t_norm_us >= to_us(t_from))
        if t_to:
            q = q.where(S.observations.c.t_norm_us <= to_us(t_to))
        with self.engine.connect() as c:
            return {r[0]: {"observations": int(r[1]), "with_plate": int(r[2] or 0)}
                    for r in c.execute(q)}

    def mean_chroma_by_camera(self) -> dict[str, float]:
        """Latest measured channel spread per camera.

        An all-time average mixes a daytime colour window with a night IR
        window and under-counts cameras that are infrared *now*. The copilot
        asks this to list the current infrared estate.
        """
        now = time.monotonic()
        hit = self._chroma_cache
        if hit is not None and now - hit[0] < 10.0:
            return hit[1]
        ranked = (
            select(
                S.observations.c.camera_id,
                S.observations.c.mean_chroma,
                func.row_number().over(
                    partition_by=S.observations.c.camera_id,
                    order_by=S.observations.c.t_norm_us.desc(),
                ).label("rn"),
            ).where(S.observations.c.mean_chroma.is_not(None))
            .subquery()
        )
        q = select(ranked.c.camera_id, ranked.c.mean_chroma).where(ranked.c.rn == 1)
        with self.engine.connect() as c:
            out = {r[0]: float(r[1]) for r in c.execute(q) if r[1] is not None}
        self._chroma_cache = (now, out)
        return out

    # -- observations ------------------------------------------------------- #
    def add_observations(self, obs: Sequence[VehicleObservation]) -> int:
        """Idempotent bulk insert. Returns the number actually written.

        Duplicates are dropped silently by `dedup_key`, which is what makes
        offline replay safe.
        """
        if not obs:
            return 0
        rows = []
        for o in obs:
            r = o.row()
            ctx = self._cam_ctx(o.camera_id)
            if ctx:
                # Denormalise from the registry rather than trusting the caller.
                r["district"] = r["district"] or ctx[0]
                r["department"] = r["department"] or ctx[1]
                if r["lat"] is None:
                    r["lat"], r["lon"] = ctx[2], ctx[3]
            rows.append(r)
        written = 0
        with self.engine.begin() as c:
            if self.is_sqlite:
                stmt = sqlite_insert(S.observations).on_conflict_do_nothing(
                    index_elements=["dedup_key"])
                res = c.execute(stmt, rows)
                written = res.rowcount if res.rowcount is not None else len(rows)
            else:
                for r in rows:
                    try:
                        c.execute(insert(S.observations).values(**r))
                        written += 1
                    except Exception:
                        pass
        self._stats_cache = None
        self._chroma_cache = None
        self._pub_cache = None
        return max(0, written)

    def add_plate_reads(self, reads: Sequence[dict[str, Any]]) -> int:
        if not reads:
            return 0
        rows = [{**r, "created_at_us": now_us()} for r in reads]
        with self.engine.begin() as c:
            c.execute(insert(S.plate_reads), rows)
        self._stats_cache = None
        self._pub_cache = None
        return len(rows)

    def _apply_filter(self, q, f: SearchFilter):
        if f.plate:
            q = q.where(S.observations.c.plate == f.plate)
        if f.plate_prefix:
            q = q.where(S.observations.c.plate.like(f"{f.plate_prefix}%"))
        if f.cameras:
            q = q.where(S.observations.c.camera_id.in_(list(f.cameras)))
        if f.districts:
            q = q.where(S.observations.c.district.in_(list(f.districts)))
        if f.departments:
            q = q.where(S.observations.c.department.in_(list(f.departments)))
        if f.object_types:
            q = q.where(S.observations.c.object_type.in_(list(f.object_types)))
        if f.colours:
            q = q.where(S.observations.c.colour.in_(list(f.colours)))
        if f.t_from:
            q = q.where(S.observations.c.t_norm_us >= to_us(f.t_from))
        if f.t_to:
            q = q.where(S.observations.c.t_norm_us <= to_us(f.t_to))
        if f.min_plate_confidence is not None:
            q = q.where(S.observations.c.plate_confidence >= f.min_plate_confidence)
        if f.min_observation_quality is not None:
            q = q.where(or_(S.observations.c.observation_quality.is_(None),
                            S.observations.c.observation_quality >= f.min_observation_quality))
        if f.has_embedding:
            q = q.where(S.observations.c.embedding.isnot(None))
        return q

    def search(self, f: SearchFilter) -> list[VehicleObservation]:
        q = self._apply_filter(select(S.observations), f)
        q = q.order_by(S.observations.c.t_norm_us).limit(f.limit)
        with self.engine.connect() as c:
            return [VehicleObservation.from_row(r) for r in c.execute(q)]

    def search_plate(self, plate: str, t_from: datetime | None = None,
                     t_to: datetime | None = None, limit: int = 500
                     ) -> list[VehicleObservation]:
        """The mandatory query: where has this registration mark been?"""
        return self.search(SearchFilter(plate=plate, t_from=t_from, t_to=t_to,
                                        limit=limit))

    def observations_for_track(self, camera_id: str, track_id: str
                               ) -> list[VehicleObservation]:
        q = select(S.observations).where(and_(
            S.observations.c.camera_id == camera_id,
            S.observations.c.track_id == track_id,
        )).order_by(S.observations.c.t_norm_us)
        with self.engine.connect() as c:
            return [VehicleObservation.from_row(r) for r in c.execute(q)]

    def distinct_plates(self, camera_id: str | None = None) -> list[str]:
        q = select(S.observations.c.plate).where(
            S.observations.c.plate.isnot(None)).distinct()
        if camera_id:
            q = q.where(S.observations.c.camera_id == camera_id)
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(q) if r[0]]

    def plate_marks(self, *, like: str | None = None, prefix: str | None = None,
                    t_from: datetime | None = None, t_to: datetime | None = None,
                    limit: int = 5000) -> list[dict[str, Any]]:
        """Distinct registration marks matching a LIKE pattern, per camera.

        One row per (mark, camera) with its read count and first/last time, so
        a partial-plate query answers "which vehicles" rather than returning a
        thousand observations of three of them. ``prefix`` becomes an index
        range (``plate >= p AND plate < p'``), which is what keeps a witness
        fragment like GJ18X67 a seek on ``ix_obs_plate_time`` instead of a scan
        of every row; without one, ``plate > ''`` still skips the unplated
        majority of the table.
        """
        col = S.observations.c.plate
        q = select(col, S.observations.c.camera_id,
                   func.count().label("reads"),
                   func.min(S.observations.c.t_norm_us).label("first_us"),
                   func.max(S.observations.c.t_norm_us).label("last_us"))
        if prefix:
            q = q.where(col >= prefix, col < prefix[:-1] + chr(ord(prefix[-1]) + 1))
        else:
            q = q.where(col > "")
        if like:
            q = q.where(col.like(like))
        if t_from:
            q = q.where(S.observations.c.t_norm_us >= to_us(t_from))
        if t_to:
            q = q.where(S.observations.c.t_norm_us <= to_us(t_to))
        q = q.group_by(col, S.observations.c.camera_id).limit(limit)
        with self.engine.connect() as c:
            return [{"plate": r[0], "camera_id": r[1], "reads": int(r[2]),
                     "first_seen": from_us(r[3]), "last_seen": from_us(r[4])}
                    for r in c.execute(q) if r[0]]

    def recent_marks(self, limit: int = 48) -> list[dict[str, Any]]:
        """Latest distinct registration marks, with the camera that published them.

        Deduped by plate, newest first. Location is the camera's, not a
        reconstructed route — one row is one mark as last seen.
        """
        q = (select(
                S.observations.c.plate,
                S.observations.c.camera_id,
                S.observations.c.t_norm_us,
                S.observations.c.district,
                S.observations.c.object_type,
                S.observations.c.plate_votes,
            )
            .where(S.observations.c.plate.isnot(None),
                   S.observations.c.plate != "")
            .order_by(S.observations.c.t_ingest_us.desc())
            .limit(max(limit * 8, 80)))
        seen: set[str] = set()
        by_cam: dict[str, list[dict[str, Any]]] = {}
        with self.engine.connect() as c:
            rows = list(c.execute(q))
        for plate, cam_id, t_us, district, otype, votes in rows:
            if not plate or plate in seen:
                continue
            seen.add(plate)
            cam = self.get_camera(cam_id) or {}
            if cam.get("enabled") is False or cam.get("enabled") == 0:
                continue
            when = from_us(t_us)
            by_cam.setdefault(cam_id, []).append({
                "plate": plate,
                "camera_id": cam_id,
                "name": cam.get("name") or cam_id,
                "district": district or cam.get("district"),
                "t": when.isoformat() if when else None,
                "object_type": otype,
                "votes": int(votes or 0),
            })
        try:
            from saakshya.live.preview import preview_usable
        except Exception:
            def preview_usable(cid: str) -> bool:  # type: ignore[misc]
                return True
        usable: dict[str, bool] = {}
        out: list[dict[str, Any]] = []
        rest: list[dict[str, Any]] = []
        while (len(out) + len(rest)) < limit and any(by_cam.values()):
            for cam_id in list(by_cam):
                bucket = by_cam.get(cam_id) or []
                if not bucket:
                    by_cam.pop(cam_id, None)
                    continue
                row = bucket.pop(0)
                if cam_id not in usable:
                    usable[cam_id] = bool(preview_usable(cam_id))
                row["still_ok"] = usable[cam_id]
                (out if row["still_ok"] else rest).append(row)
                if not bucket:
                    by_cam.pop(cam_id, None)
                if (len(out) + len(rest)) >= limit:
                    break
        return (out + rest)[:limit]

    def marks_for_camera(self, camera_id: str, limit: int = 24
                         ) -> list[dict[str, Any]]:
        """Distinct plates last published by one camera, with the plate box.

        Focus uses this to show the crop and the number together so the
        operator picks a real read, not a drawn-on registration plate.
        """
        if not camera_id:
            return []
        cam = self.get_camera(camera_id) or {}
        if cam.get("enabled") is False or cam.get("enabled") == 0:
            return []
        q = (select(
                S.observations.c.plate,
                S.observations.c.t_norm_us,
                S.observations.c.object_type,
                S.observations.c.plate_votes,
                S.observations.c.bbox_x1,
                S.observations.c.bbox_y1,
                S.observations.c.bbox_x2,
                S.observations.c.bbox_y2,
                S.observations.c.pts_s,
                S.observations.c.observation_id,
            )
            .where(S.observations.c.camera_id == camera_id,
                   S.observations.c.plate.isnot(None),
                   S.observations.c.plate != "")
            .order_by(S.observations.c.t_ingest_us.desc())
            .limit(max(limit * 6, 24)))
        with self.engine.connect() as c:
            rows = list(c.execute(q))
        try:
            from saakshya.live.preview import preview_usable
            still_ok = bool(preview_usable(camera_id))
        except Exception:
            still_ok = True
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for plate, t_us, otype, votes, x1, y1, x2, y2, pts, oid in rows:
            if not plate or plate in seen:
                continue
            seen.add(plate)
            when = from_us(t_us)
            bbox = None
            if x1 is not None and y1 is not None and x2 is not None and y2 is not None:
                bbox = [float(x1), float(y1), float(x2), float(y2)]
            out.append({
                "plate": plate,
                "camera_id": camera_id,
                "name": cam.get("name") or camera_id,
                "district": cam.get("district"),
                "t": when.isoformat() if when else None,
                "object_type": otype,
                "votes": int(votes or 0),
                "bbox": bbox,
                "pts_s": float(pts) if pts is not None else None,
                "observation_id": oid,
                "still_ok": still_ok,
            })
            if len(out) >= limit:
                break
        return out

    def marks_in_latest_hour(self) -> dict[str, int]:
        """Distinct marks in the last hour of *store* time, not wall clock.

        Demo and paused ingest have no 'now'. Using the newest observation as
        t1 keeps the KPI honest on both stores.
        """
        with self.engine.connect() as c:
            newest = c.execute(select(func.max(S.observations.c.t_ingest_us))).scalar()
            if not newest:
                return {"distinct": 0, "confirmed": 0, "leads": 0}
            cut = int(newest) - 3_600_000_000
            distinct = c.execute(
                select(func.count(func.distinct(S.observations.c.plate)))
                .where(S.observations.c.plate.isnot(None),
                       S.observations.c.t_ingest_us >= cut)).scalar() or 0
            confirmed = c.execute(
                select(func.count(func.distinct(S.observations.c.plate)))
                .where(S.observations.c.plate.isnot(None),
                       S.observations.c.plate_votes >= 2,
                       S.observations.c.t_ingest_us >= cut)).scalar() or 0
            leads = c.execute(
                select(func.count(func.distinct(S.observations.c.plate)))
                .where(S.observations.c.plate.isnot(None),
                       S.observations.c.plate_votes == 1,
                       S.observations.c.t_ingest_us >= cut)).scalar() or 0
        return {"distinct": int(distinct), "confirmed": int(confirmed),
                "leads": int(leads)}

    def count_observations(self) -> int:
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(S.observations)).scalar_one()

    def stats(self) -> dict[str, Any]:
        now = time.monotonic()
        hit = self._stats_cache
        if hit is not None and now - hit[0] < self._stats_ttl_s:
            return hit[1]
        with self.engine.connect() as c:
            def n(t):
                return c.execute(select(func.count()).select_from(t)).scalar_one()
            with_plate = c.execute(
                select(func.count()).select_from(S.observations)
                .where(S.observations.c.plate.isnot(None))).scalar_one()
            plate_confirmed = c.execute(
                select(func.count()).select_from(S.observations)
                .where(S.observations.c.plate.isnot(None),
                       S.observations.c.plate_votes >= 2)).scalar_one()
            plate_leads = c.execute(
                select(func.count()).select_from(S.observations)
                .where(S.observations.c.plate.isnot(None),
                       S.observations.c.plate_votes == 1)).scalar_one()
            persons = c.execute(
                select(func.count()).select_from(S.observations)
                .where(S.observations.c.object_type == "person")).scalar_one()
            # JSON true extracts as 1 on SQLite. This is a duration on one
            # camera, not an identity and not an intrusion judgement.
            dwell_flag = func.json_extract(
                S.observations.c.model_versions, "$.dwell_exceeded")
            person_long_stay = c.execute(
                select(func.count()).select_from(S.observations).where(
                    S.observations.c.object_type == "person",
                    dwell_flag.in_((1, True)),
                )).scalar_one()
            cameras_person_long_stay = c.execute(
                select(func.count(func.distinct(S.observations.c.camera_id)))
                .where(S.observations.c.object_type == "person",
                       dwell_flag.in_((1, True)))).scalar_one()
            cameras_with_plate = c.execute(
                select(func.count(func.distinct(S.observations.c.camera_id)))
                .where(S.observations.c.plate.isnot(None))).scalar_one()
            distinct_plates = c.execute(
                select(func.count(func.distinct(S.observations.c.plate)))
                .where(S.observations.c.plate.isnot(None))).scalar_one()
            with_emb = c.execute(
                select(func.count()).select_from(S.observations)
                .where(S.observations.c.embedding.isnot(None))).scalar_one()
            type_rows = c.execute(
                select(S.observations.c.object_type, func.count())
                .group_by(S.observations.c.object_type)).all()
            by_object_type = {
                (row[0] or "unknown"): int(row[1]) for row in type_rows
            }
            out = {
                "cameras": n(S.cameras), "observations": n(S.observations),
                "observations_with_plate": with_plate,
                "observations_plate_confirmed": plate_confirmed,
                "observations_plate_leads": plate_leads,
                "observations_person": persons,
                "observations_person_long_stay": person_long_stay,
                "cameras_person_long_stay": cameras_person_long_stay,
                "cameras_with_plate": cameras_with_plate,
                "distinct_plates": distinct_plates,
                "observations_with_embedding": with_emb,
                "observations_by_object_type": by_object_type,
                # The raw-OCR table: every read attempt including the ones
                # rejected, kept so a reader can see what was discarded and
                # why. It is *not* "how many plates were read" — that is
                # `observations_with_plate` — and printing the two side by
                # side under similar names invites exactly that misreading.
                "raw_ocr_read_records": n(S.plate_reads),
                "transitions": n(S.camera_transitions),
                "watchlist": n(S.watchlist), "alerts": n(S.alerts),
                "evidence": n(S.evidence), "audit_entries": n(S.audit_log),
            }
        self._stats_cache = (now, out)
        return out

    # -- transitions (Camera Link Model) ------------------------------------ #
    def add_transition_samples(self, samples: Sequence[dict[str, Any]]) -> int:
        if not samples:
            return 0
        rows = [{**s, "created_at_us": now_us()} for s in samples]
        with self.engine.begin() as c:
            c.execute(insert(S.transition_samples), rows)
        return len(rows)

    def upsert_transition(self, row: dict[str, Any]) -> None:
        row = {**row, "updated_at_us": now_us()}
        with self.engine.begin() as c:
            if self.is_sqlite:
                stmt = sqlite_insert(S.camera_transitions).values(**row)
                c.execute(stmt.on_conflict_do_update(
                    index_elements=["from_camera", "to_camera"],
                    set_={k: v for k, v in row.items()
                          if k not in ("from_camera", "to_camera")}))
            else:
                c.execute(delete(S.camera_transitions).where(and_(
                    S.camera_transitions.c.from_camera == row["from_camera"],
                    S.camera_transitions.c.to_camera == row["to_camera"])))
                c.execute(insert(S.camera_transitions).values(**row))

    def get_transitions(self, from_camera: str | None = None
                        ) -> list[dict[str, Any]]:
        q = select(S.camera_transitions)
        if from_camera:
            q = q.where(S.camera_transitions.c.from_camera == from_camera)
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in
                    c.execute(q.order_by(S.camera_transitions.c.support_count.desc()))]

    def all_transition_samples(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [dict(r._mapping) for r in c.execute(select(S.transition_samples))]

    # -- audit -------------------------------------------------------------- #
    def audit(self, actor: str, action: str, *, role: str | None = None,
              case_id: str | None = None, purpose: str | None = None,
              target: str | None = None, result_count: int | None = None,
              jurisdiction: str | None = None) -> None:
        """Append to the hash-chained audit log.

        Every search is recorded. The chain means a deleted or altered entry is
        detectable, which is what makes "all searches are audited" a claim we
        can support rather than assert.
        """
        import hashlib

        with self.engine.begin() as c:
            prev = c.execute(select(S.audit_log.c.entry_hash)
                             .order_by(S.audit_log.c.id.desc()).limit(1)).scalar()
            # One timestamp, used for both the hash and the row. Calling now_us()
            # twice makes the stored value differ from the hashed value and the
            # chain fails verification on the very first entry.
            t = now_us()
            payload = json.dumps({
                "actor": actor, "role": role, "action": action, "case_id": case_id,
                "purpose": purpose, "target": target, "result_count": result_count,
                "jurisdiction": jurisdiction, "t": t, "prev": prev,
            }, sort_keys=True)
            entry = hashlib.sha256(payload.encode()).hexdigest()
            c.execute(insert(S.audit_log).values(
                actor=actor, role=role, action=action, case_id=case_id,
                purpose=purpose, target=target, result_count=result_count,
                jurisdiction=jurisdiction, prev_hash=prev, entry_hash=entry,
                t_us=t))
        # `stats()` is cached for dashboard reads; an audit write must be
        # visible immediately to the same request/test process.
        self._stats_cache = None

    def verify_audit_chain(self) -> tuple[bool, str | None]:
        import hashlib

        with self.engine.connect() as c:
            rows = list(c.execute(select(S.audit_log).order_by(S.audit_log.c.id)))
        prev = None
        for r in rows:
            m = r._mapping
            payload = json.dumps({
                "actor": m["actor"], "role": m["role"], "action": m["action"],
                "case_id": m["case_id"], "purpose": m["purpose"], "target": m["target"],
                "result_count": m["result_count"], "jurisdiction": m["jurisdiction"],
                "t": m["t_us"], "prev": prev,
            }, sort_keys=True)
            if hashlib.sha256(payload.encode()).hexdigest() != m["entry_hash"]:
                return False, f"audit chain broken at id={m['id']}"
            prev = m["entry_hash"]
        return True, None
