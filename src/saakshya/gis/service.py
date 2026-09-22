"""The map as an investigation surface.

Two ideas run through this module.

**The map answers operational questions, not decorative ones.** Every layer
exists because an investigator or a control-room operator asks something of it:
where can I see, where can I *not* see, which cameras can actually read a plate
at this hour, where did this vehicle go, and where is the evidence for that.
There is no layer here whose only purpose is to look busy.

**Absence of coverage is stated, never inferred into presence.** A gap on this
map means "the system cannot observe here". It never means "the vehicle was not
here", and the wording of every gap explanation is chosen so that an officer
reading it under time pressure cannot come away with the stronger claim.

Server-side aggregation is not premature optimisation: the target estate is
~80,000 cameras. Shipping raw features to a browser works at 50 and fails at
5,000, and the failure mode is a frozen tab during an incident. Clustering,
viewport filtering and field projection all happen here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, not_, or_, select

from saakshya.command.domain import annotate_camera
from saakshya.intelligence.graph import CameraGraph, haversine_m
from saakshya.store import Store

#: Web Mercator. Only used for clustering geometry — the wire format stays
#: WGS-84 lat/lon so nothing downstream has to know about projections.
_TILE = 256.0


def mercator_xy(lat: float, lon: float, zoom: float) -> tuple[float, float]:
    scale = _TILE * (2.0 ** zoom)
    x = (lon + 180.0) / 360.0 * scale
    lat = max(-85.05112878, min(85.05112878, lat))
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    return x, y


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    #: Whole world. Used when a caller supplies no viewport, so the code path is
    #: identical rather than branching on "no bbox".
    @classmethod
    def world(cls) -> BBox:
        return cls(-85.0, -180.0, 85.0, 180.0)

    @classmethod
    def parse(cls, text: str | None) -> BBox:
        """`west,south,east,north` — the order used by every mapping client we
        might sit behind. Rejected loudly rather than silently reordered."""
        if not text:
            return cls.world()
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 4:
            raise ValueError("bbox must be 'west,south,east,north'")
        try:
            w, s, e, n = (float(p) for p in parts)
        except ValueError as exc:
            raise ValueError(f"bbox is not numeric: {text!r}") from exc
        if not (-90 <= s <= 90 and -90 <= n <= 90):
            raise ValueError("bbox latitude out of range")
        if not (-180 <= w <= 180 and -180 <= e <= 180):
            raise ValueError("bbox longitude out of range")
        if s > n:
            raise ValueError("bbox south is north of north")
        return cls(s, w, n, e)

    def expand(self, frac: float = 0.15) -> BBox:
        """Pad the viewport so a small pan does not immediately refetch."""
        dlat = (self.north - self.south) * frac
        dlon = (self.east - self.west) * frac
        return BBox(max(-90.0, self.south - dlat), max(-180.0, self.west - dlon),
                    min(90.0, self.north + dlat), min(180.0, self.east + dlon))

    def contains(self, lat: float | None, lon: float | None) -> bool:
        if lat is None or lon is None:
            return False
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    def to_dict(self) -> dict[str, float]:
        return {"south": self.south, "west": self.west,
                "north": self.north, "east": self.east}


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
#: Cluster cell in screen pixels. 64 keeps markers legible at any zoom without
#: collapsing a junction's four cameras into one blob at street level.
CLUSTER_PX = 64.0


def cluster_points(points: list[dict[str, Any]], zoom: float,
                   *, cell_px: float = CLUSTER_PX) -> list[dict[str, Any]]:
    """Grid-cluster in projected space.

    Grid rather than hierarchical clustering: it is deterministic, it is O(n),
    and — the property that actually matters operationally — the same viewport
    always produces the same clusters, so a marker does not jump between pans.
    A prettier centroid algorithm that reshuffles under a 10-pixel pan would be
    worse for the person using it.
    """
    cells: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for p in points:
        if p.get("lat") is None or p.get("lon") is None:
            continue
        x, y = mercator_xy(p["lat"], p["lon"], zoom)
        key = (int(x // cell_px), int(y // cell_px))
        cells.setdefault(key, []).append(p)

    out: list[dict[str, Any]] = []
    for key, members in sorted(cells.items()):
        if len(members) == 1:
            out.append({**members[0], "cluster": False})
            continue
        lat = sum(m["lat"] for m in members) / len(members)
        lon = sum(m["lon"] for m in members) / len(members)
        # A cluster reports the *worst* state it contains. Averaging health
        # would hide the one dead camera inside twenty live ones, which is
        # precisely the thing the operator is scanning the map for.
        states = [m.get("state") for m in members]
        worst = _worst_state(states)
        out.append({
            "cluster": True,
            "cluster_id": f"{key[0]}:{key[1]}:{int(zoom)}",
            "lat": lat, "lon": lon, "count": len(members),
            "state": worst,
            "states": {s: states.count(s)
                       for s in sorted(x for x in set(states) if x)},
            "camera_ids": sorted(m["camera_id"] for m in members
                                 if m.get("camera_id"))[:50],
            "truncated_ids": max(0, len(members) - 50),
        })
    return out


_STATE_ORDER = ["DOWN", "OPEN_FAILED", "DEGRADED", "RECONNECTING", "UNKNOWN",
                "OBSERVED", "STREAMING", "OK"]


def _worst_state(states: list[str | None]) -> str:
    present = [s for s in states if s]
    if not present:
        return "UNKNOWN"
    return min(present, key=lambda s: _STATE_ORDER.index(s)
               if s in _STATE_ORDER else len(_STATE_ORDER))


def _stream_state(camera_id: str, health: dict[str, Any],
                  observed: set[str]) -> str:
    """Health row if present; otherwise observed-from-store, never a silent unknown.

    A missing `camera_health` row used to become UNKNOWN and then "never
    ingested" on the live wall. Unbounded ingest writes health on a timer and
    at close; cameras with observations are not unseen.
    """
    st = health.get("state")
    if st:
        return st
    return "OBSERVED" if camera_id in observed else "UNKNOWN"


def _publication(pub: dict[str, dict[str, int]], camera_id: str) -> dict[str, int]:
    row = pub.get(camera_id) or {}
    return {
        "published_marks": int(row.get("distinct_marks") or 0),
        "published_confirmed": int(row.get("confirmed") or 0),
        "published_leads": int(row.get("leads") or 0),
    }


def _ai_status(cap: dict[str, Any], marks: dict[str, int]) -> str:
    """Operator label from measured grades, not a live detector heartbeat."""
    anpr = (cap.get("anpr_grade") or "UNKNOWN").upper()
    vehicle = (cap.get("vehicle_reid_grade") or "UNKNOWN").upper()
    if marks.get("published_marks"):
        return "OBSERVING"
    if anpr in {"GOOD", "DEGRADED"} or vehicle in {"GOOD", "DEGRADED"}:
        return "GRADED"
    return "IDLE"


# --------------------------------------------------------------------------- #
# Map service
# --------------------------------------------------------------------------- #
#: Two cameras farther apart than this, with nothing between them, is a hole a
#: vehicle can pass through unobserved. 1.5 km is roughly 90 seconds at urban
#: speed — long enough to change direction, park, or swap occupants.
GAP_THRESHOLD_M = 1500.0

#: Above this many features, aggregate instead of enumerating. Chosen so a
#: single response stays well under a megabyte on a district-wide viewport.
MAX_FEATURES = 1500


class MapService:
    """Assembles map layers. Reads; never writes."""

    def __init__(self, store: Store, graph: CameraGraph | None = None) -> None:
        self.store = store
        self.graph = graph

    # -- cameras ----------------------------------------------------------- #
    def cameras(self, *, bbox: BBox | None = None, zoom: float = 11.0,
                districts: tuple[str, ...] | None = None,
                departments: tuple[str, ...] | None = None,
                tiers: tuple[str, ...] | None = None,
                states: tuple[str, ...] | None = None,
                capability: str | None = None,
                capability_grades: tuple[str, ...] | None = None,
                codecs: tuple[str, ...] | None = None,
                regions: tuple[str, ...] | None = None,
                camera_types: tuple[str, ...] | None = None,
                ai_statuses: tuple[str, ...] | None = None,
                source_domains: tuple[str, ...] | None = None,
                q: str | None = None,
                max_features: int = MAX_FEATURES) -> dict[str, Any]:
        """Camera layer, filtered server-side and clustered when dense.

        `capability` selects which measured grade the `capability_grades` filter
        applies to (`anpr` or `vehicle`); asking for ANPR-capable cameras is a
        different question from asking for cameras that see vehicles at all, and
        conflating them is how an operator ends up trusting a camera that can
        only tell them something moved.
        """
        bb = bbox or BBox.world()
        rows = self.store.cameras_in_bbox(
            south=bb.south, west=bb.west, north=bb.north, east=bb.east,
            districts=list(districts) if districts else None,
            departments=list(departments) if departments else None,
            tiers=list(tiers) if tiers else None,
            enabled_only=True)
        ids = [r["camera_id"] for r in rows]
        health = self.store.list_health(ids)
        caps = self._capability_by_camera(ids)
        observed = self.store.observed_camera_ids()
        pub = self.store.plate_publication_by_camera()

        feats: list[dict[str, Any]] = []
        for r in rows:
            feat = self._row_feature(r, health, caps, observed, pub)
            state = feat["state"]
            if states and state not in states:
                continue
            if capability_grades:
                key = "anpr" if (capability or "anpr") == "anpr" else "vehicle"
                if (feat.get(key) or "UNKNOWN") not in capability_grades:
                    continue
            if codecs and (feat.get("codec") or "").lower() not in {
                    c.lower() for c in codecs}:
                continue
            if regions:
                region = (feat.get("region") or feat.get("district") or "")
                if region not in regions:
                    continue
            if camera_types and (feat.get("camera_type") or "") not in camera_types:
                continue
            if ai_statuses and (feat.get("ai_status") or "") not in ai_statuses:
                continue
            if source_domains and (feat.get("source_domain") or "") not in source_domains:
                continue
            if q:
                needle = q.lower()
                hay = " ".join(str(feat.get(k) or "") for k in (
                    "camera_id", "name", "site", "road", "district",
                    "department", "vendor")).lower()
                if needle not in hay:
                    continue
            feats.append(feat)

        unlocated_rows = [
            r for r in self.store.cameras_unlocated(
                list(districts) if districts else None)
            if r.get("enabled", True)]
        un_ids = [r["camera_id"] for r in unlocated_rows]
        un_health = self.store.list_health(un_ids)
        un_caps = self._capability_by_camera(un_ids)
        unlocated = [self._row_feature(r, un_health, un_caps, observed, pub)
                     for r in unlocated_rows]

        clustered = len(feats) > max_features
        payload = cluster_points(feats, zoom) if clustered else [
            {**f, "cluster": False} for f in feats]
        return {
            "bbox": bb.to_dict(), "zoom": zoom,
            "clustered": clustered,
            "returned": len(payload), "matched": len(feats),
            "features": payload,
            "unlocated": unlocated,
            "registry_total": len(feats) + len(unlocated),
            # Stated, not hidden. A map that quietly omits the cameras it has no
            # coordinates for looks like complete coverage of an estate it has
            # not actually drawn.
            "cameras_without_location": len(unlocated),
        }

    def _row_feature(self, r: dict[str, Any], health: dict[str, dict[str, Any]],
                     caps: dict[str, dict[str, Any]],
                     observed: set[str] | None = None,
                     pub: dict[str, dict[str, int]] | None = None
                     ) -> dict[str, Any]:
        h = health.get(r["camera_id"], {})
        cap = caps.get(r["camera_id"], {})
        seen = observed if observed is not None else set()
        marks = _publication(pub or {}, r["camera_id"])
        feat = {
            "camera_id": r["camera_id"], "name": r["name"],
            "lat": r["lat"], "lon": r["lon"],
            "located": r.get("lat") is not None and r.get("lon") is not None,
            "location_basis": r.get("location_basis") or "UNKNOWN",
            "location_precision": r.get("location_precision") or "UNKNOWN",
            "site": r.get("site"),
            "road": r.get("road"),
            "owner": r.get("owner"),
            "region": r.get("region") or r.get("district"),
            "district": r["district"], "department": r["department"],
            "vendor": r.get("vendor"), "camera_type": r.get("camera_type"),
            "vms": r.get("vms"),
            "integration_model": r.get("integration_model"),
            "source_domain": r.get("source_domain") or None,
            "maintenance_status": r.get("maintenance_status"),
            "access_state": r.get("access_state"),
            "tier": r["tier"], "enabled": bool(r["enabled"]),
            "codec": r["codec"], "width": r["width"], "height": r["height"],
            "rtsp_capable": bool(r.get("rtsp_url")),
            "whep_capable": bool(r.get("whep_url")),
            "hls_capable": bool(r.get("hls_url")),
            "state": _stream_state(r["camera_id"], h, seen),
            "reachable": h.get("reachable"),
            "measured_fps": _round(h.get("measured_fps"), 2),
            "reconnects": h.get("reconnects"),
            "last_heartbeat": h.get("last_seen_us") or h.get("updated_at_us"),
            "anpr": cap.get("anpr_grade") or "UNKNOWN",
            "vehicle": cap.get("vehicle_reid_grade") or "UNKNOWN",
            "presence": cap.get("presence_grade") or "UNKNOWN",
            "ai_status": _ai_status(cap, marks),
            "capability_samples": cap.get("samples") or 0,
            "plate_yield": cap.get("plate_yield"),
            "plate_reads": cap.get("plate_reads"),
            **marks,
        }
        return annotate_camera(feat)

    def _capability_by_camera(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Collapse per-time-band capability to one row per camera.

        The collapse takes the *most sampled* band rather than the best grade:
        reporting a camera as ANPR-capable because it manages it at noon, when
        the question is usually asked at night, would be a comfortable lie.
        """
        out: dict[str, dict[str, Any]] = {}
        for row in self.store.list_capability(ids):
            cur = out.get(row["camera_id"])
            if cur is None or (row.get("samples") or 0) > (cur.get("samples") or 0):
                out[row["camera_id"]] = row
        return out

    # -- health ------------------------------------------------------------ #
    def health(self, *, bbox: BBox | None = None,
               districts: tuple[str, ...] | None = None) -> dict[str, Any]:
        bb = bbox or BBox.world()
        rows = self.store.cameras_in_bbox(
            south=bb.south, west=bb.west, north=bb.north, east=bb.east,
            districts=list(districts) if districts else None)
        unlocated = self.store.cameras_unlocated(
            list(districts) if districts else None)
        rows = rows + unlocated
        health = self.store.list_health([r["camera_id"] for r in rows])
        observed = self.store.observed_camera_ids()
        pub = self.store.plate_publication_by_camera()
        by_state: dict[str, int] = {}
        feats = []
        for r in rows:
            h = health.get(r["camera_id"], {})
            state = _stream_state(r["camera_id"], h, observed)
            by_state[state] = by_state.get(state, 0) + 1
            feats.append({
                "camera_id": r["camera_id"], "lat": r["lat"], "lon": r["lon"],
                "located": r.get("lat") is not None and r.get("lon") is not None,
                "district": r["district"], "state": state,
                "reachable": h.get("reachable"),
                "frames": h.get("frames"), "reconnects": h.get("reconnects"),
                "decoder_errors": h.get("decoder_errors"),
                "pts_regressions": h.get("pts_regressions"),
                "segment_breaks": h.get("segment_breaks"),
                "measured_fps": _round(h.get("measured_fps"), 2),
                "declared_fps": r.get("declared_fps"),
                "clock_drift_s": _round(h.get("clock_drift_s"), 3),
                "last_error": h.get("last_error"),
                **_publication(pub, r["camera_id"]),
            })
        never = sum(1 for f in feats if f["state"] == "UNKNOWN")
        unlocated_n = sum(1 for f in feats if not f.get("located"))
        return {
            "bbox": bb.to_dict(), "summary": by_state, "total": len(feats),
            "never_observed": never,
            "unlocated": unlocated_n,
            "features": feats,
        }

    # -- capability -------------------------------------------------------- #
    #: The five departments the hackathon dataset is drawn from. A department
    #: with no camera is a coverage gap worth naming, so the expected set is
    #: declared rather than inferred from whatever happens to be onboarded.
    EXPECTED_DEPARTMENTS = (
        "Health", "Home (Police)", "GSRTC", "Panchayat",
        "Municipal Corporation",
    )

    def registry_gaps(self) -> dict[str, Any]:
        """What the registry does not know about its own estate.

        Model 1 asks for gap analysis, and a registry that reports only what it
        holds is the least useful kind: the fields nobody filled in are exactly
        the ones that block onboarding a department.

        Counted in SQL rather than by loading the estate. The first version of
        this walked `cameras_in_bbox`, which caps at 20,000 rows because it
        exists to fill a map viewport — on an 80,000-camera estate it reported
        gaps for a quarter of the cameras and said nothing about the rest. A
        report that silently drops 60,000 rows is worse than no report.
        """
        from saakshya.store import schema as S

        cams = S.cameras
        real = not_(cams.c.camera_id.like("CTL-%"))
        fields = ("department", "vms", "storage_location", "retention_days",
                  "vendor", "camera_type")

        with self.store.engine.connect() as c:
            total = c.execute(select(func.count()).select_from(cams)
                              .where(real)).scalar_one()
            slots = c.execute(select(func.count()).select_from(cams)
                              .where(cams.c.camera_id.like("CTL-%"))).scalar_one()

            counts: dict[str, int] = {}
            samples: dict[str, list[str]] = {}
            for f in fields:
                col = cams.c[f]
                missing = col.is_(None)
                if f != "retention_days":
                    missing = or_(col.is_(None), func.trim(col) == "")
                counts[f] = c.execute(select(func.count()).select_from(cams)
                                      .where(and_(real, missing))).scalar_one()
                samples[f] = [r[0] for r in c.execute(
                    select(cams.c.camera_id).where(and_(real, missing))
                    .order_by(cams.c.camera_id).limit(40))]

            no_coords = and_(real, or_(cams.c.lat.is_(None), cams.c.lon.is_(None)))
            counts["coordinates"] = c.execute(
                select(func.count()).select_from(cams).where(no_coords)).scalar_one()
            samples["coordinates"] = [r[0] for r in c.execute(
                select(cams.c.camera_id).where(no_coords)
                .order_by(cams.c.camera_id).limit(40))]

            present = {(d or "(unrecorded)"): int(n) for d, n in c.execute(
                select(cams.c.department, func.count()).where(real)
                .group_by(cams.c.department).order_by(func.count().desc()))}

            graded = select(S.camera_capability.c.camera_id).distinct().scalar_subquery()
            ungraded_n = c.execute(
                select(func.count()).select_from(cams)
                .where(and_(real, cams.c.camera_id.notin_(graded)))).scalar_one()
            ungraded = [r[0] for r in c.execute(
                select(cams.c.camera_id)
                .where(and_(real, cams.c.camera_id.notin_(graded)))
                .order_by(cams.c.camera_id).limit(40))]

        absent = [d for d in self.EXPECTED_DEPARTMENTS if d not in present]
        gaps = [
            {"field": f, "missing": counts[f], "of": total,
             "pct": (round(100.0 * counts[f] / total, 1) if total else 0.0),
             "cameras": samples[f],
             "truncated": max(0, counts[f] - len(samples[f]))}
            for f in sorted(counts, key=lambda k: -counts[k])
        ]
        return {
            "cameras": total,
            "capacity_slots": slots,
            "departments_present": present,
            "departments_expected": list(self.EXPECTED_DEPARTMENTS),
            "departments_absent": absent,
            "ungraded": {"count": ungraded_n, "cameras": ungraded},
            "field_gaps": gaps,
            "note": ("Counted across the whole registry in SQL. A field listed "
                     "here is one no department has supplied yet, not one the "
                     "platform cannot hold — the column exists in the schema."),
        }

    def capability(self, *, bbox: BBox | None = None,
                   districts: tuple[str, ...] | None = None,
                   time_band: str | None = None,
                   include_unlocated: bool = True) -> dict[str, Any]:
        """Measured capability per camera.

        This is an inventory, not a map layer, so cameras without coordinates
        are included by default. Excluding them made the entire live grid
        invisible in its own capability view — thirty registered, working
        cameras, none of which the catalogue had told us where to put.
        """
        bb = bbox or BBox.world()
        rows = self.store.cameras_in_bbox(
            south=bb.south, west=bb.west, north=bb.north, east=bb.east,
            districts=list(districts) if districts else None)
        unlocated = (self.store.cameras_unlocated(
            list(districts) if districts else None) if include_unlocated else [])
        rows = rows + unlocated
        ids = [r["camera_id"] for r in rows]
        by_cam: dict[str, list[dict[str, Any]]] = {}
        for c in self.store.list_capability(ids, time_band=time_band):
            by_cam.setdefault(c["camera_id"], []).append(c)
        pub = self.store.plate_publication_by_camera()

        feats: list[dict[str, Any]] = []
        tally: dict[str, dict[str, int]] = {"anpr": {}, "vehicle": {},
                                            "presence": {}}
        slots = 0
        for r in rows:
            bands = by_cam.get(r["camera_id"], [])
            best = max(bands, key=lambda b: b.get("samples") or 0, default=None)
            grades = {
                "anpr": (best or {}).get("anpr_grade") or "UNKNOWN",
                "vehicle": (best or {}).get("vehicle_reid_grade") or "UNKNOWN",
                "presence": (best or {}).get("presence_grade") or "UNKNOWN",
            }
            # A capacity slot has no stream, so it has nothing to grade. Counting
            # it as UNKNOWN put eighteen reserved slots into the estate's
            # capability figures and reported "21 not graded" for an estate with
            # three ungraded cameras - measuring the padding, not the estate.
            is_slot = str(r["camera_id"]).startswith("CTL-")
            if is_slot:
                slots += 1
            else:
                for k, v in grades.items():
                    tally[k][v] = tally[k].get(v, 0) + 1
            feats.append({
                "synthetic_slot": is_slot,
                "source_domain": "SYNTHETIC_CONTROL" if is_slot else "GOVERNMENT",
                "camera_id": r["camera_id"], "name": r.get("name"),
                "lat": r["lat"], "lon": r["lon"],
                "located": r["lat"] is not None and r["lon"] is not None,
                "district": r["district"], "tier": r["tier"],
                # The registry metadata an integrator actually acts on. These
                # are the same fields /gis/gaps reports as unsupplied, and
                # leaving them out of the inventory meant the estate view
                # could not be filtered by the thing a department cares about
                # — which VMS a feed must be integrated through, and how long
                # its footage survives.
                "department": r.get("department"),
                "vms": r.get("vms"),
                "vendor": r.get("vendor"),
                "camera_type": r.get("camera_type"),
                "storage_location": r.get("storage_location"),
                "retention_days": r.get("retention_days"),
                "codec": r.get("codec"),
                "resolution": (f"{r['width']}x{r['height']}"
                               if r.get("width") else None),
                **grades,
                "samples": (best or {}).get("samples") or 0,
                "sharpness": _round((best or {}).get("sharpness"), 1),
                "luminance": _round((best or {}).get("luminance"), 1),
                "plate_yield": _round((best or {}).get("plate_yield"), 3),
                "plate_reads": (best or {}).get("plate_reads"),
                "vehicle_yield": _round((best or {}).get("vehicle_yield"), 3),
                "bands": [{"time_band": b["time_band"],
                           "anpr": b["anpr_grade"],
                           "vehicle": b["vehicle_reid_grade"],
                           "presence": b.get("presence_grade") or "UNKNOWN",
                           "samples": b["samples"]} for b in bands],
                **_publication(pub, r["camera_id"]),
            })
        return {"bbox": bb.to_dict(), "total": len(feats),
                "cameras": len(feats) - slots, "capacity_slots": slots,
                "unlocated": len(unlocated),
                "grade_summary": tally, "features": feats,
                "note": (f"{len(unlocated)} camera(s) have no coordinates and "
                         "cannot be placed on the map. They are listed here "
                         "because capability is a property of the camera, not "
                         "of its position." if unlocated else None)}

    # -- coverage ---------------------------------------------------------- #
    def coverage(self, *, bbox: BBox | None = None,
                 districts: tuple[str, ...] | None = None,
                 threshold_m: float = GAP_THRESHOLD_M) -> dict[str, Any]:
        """Where the estate cannot see, and why.

        Three distinct kinds, kept distinct because the remedy differs:

        * ``DISTANCE`` — the nearest neighbouring camera is far enough away that
          a vehicle can leave the network between them. Remedy: a new camera.
        * ``CAPABILITY`` — a camera is there and working, but measurement says it
          cannot do the job asked of it. Remedy: a lens, a re-aim, or a
          re-tiering. This is the class that a conventional map cannot show at
          all, because it looks identical to a healthy camera.
        * ``AVAILABILITY`` — a camera that should cover this is currently down.
          Remedy: maintenance.

        None of these is a statement about where any vehicle went.
        """
        bb = bbox or BBox.world()
        rows = [r for r in self.store.cameras_in_bbox(
            south=bb.south, west=bb.west, north=bb.north, east=bb.east,
            districts=list(districts) if districts else None)]
        by_id = {r["camera_id"]: r for r in rows}
        health = self.store.list_health(list(by_id))
        caps = self._capability_by_camera(list(by_id))

        gaps: list[dict[str, Any]] = []

        # DISTANCE — nearest-neighbour distance per camera. O(n^2) over the
        # viewport, which is bounded by the bbox query above; a k-d tree is the
        # obvious change if a viewport ever returns tens of thousands.
        located = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
        for a in located:
            nearest, best = None, float("inf")
            for b in located:
                if a["camera_id"] == b["camera_id"]:
                    continue
                d = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
                if d < best:
                    best, nearest = d, b
            if nearest is None:
                gaps.append({
                    "kind": "DISTANCE", "severity": "HIGH",
                    "camera_id": a["camera_id"], "lat": a["lat"], "lon": a["lon"],
                    "distance_m": None,
                    "explanation": (f"{a['camera_id']} has no neighbouring camera in "
                                    "this view. A vehicle leaving it is unobserved."),
                })
            elif best > threshold_m:
                gaps.append({
                    "kind": "DISTANCE",
                    "severity": "HIGH" if best > threshold_m * 2 else "MEDIUM",
                    "camera_id": a["camera_id"], "lat": a["lat"], "lon": a["lon"],
                    "to_camera": nearest["camera_id"],
                    "to_lat": nearest["lat"], "to_lon": nearest["lon"],
                    "distance_m": round(best),
                    "explanation": (
                        f"Nearest camera to {a['camera_id']} is {nearest['camera_id']} "
                        f"at {best / 1000:.1f} km. A vehicle can pass between them "
                        "unobserved. This does not indicate that any vehicle did."),
                })

        # CAPABILITY — measured, and only where we have enough samples to say so.
        for cid, cap in caps.items():
            r = by_id.get(cid)
            if not r:
                continue
            if (cap.get("samples") or 0) < 1:
                continue
            if cap.get("anpr_grade") == "UNSUITABLE":
                gaps.append({
                    "kind": "CAPABILITY", "severity": "MEDIUM",
                    "camera_id": cid, "lat": r["lat"], "lon": r["lon"],
                    "explanation": (
                        f"{cid} is online but measured UNSUITABLE for plate reading "
                        f"over {cap['samples']} samples. Vehicles pass and are "
                        "counted; registration numbers are not recoverable here."),
                })

        # AVAILABILITY — down now.
        for cid, h in health.items():
            if h.get("state") in ("DOWN", "OPEN_FAILED"):
                r = by_id.get(cid)
                if not r:
                    continue
                gaps.append({
                    "kind": "AVAILABILITY", "severity": "HIGH",
                    "camera_id": cid, "lat": r["lat"], "lon": r["lon"],
                    "explanation": (
                        f"{cid} is {h['state']}"
                        + (f": {h['last_error']}" if h.get("last_error") else "")
                        + ". Any period while it is down is unobserved, not clear."),
                })

        by_kind: dict[str, int] = {}
        for g in gaps:
            by_kind[g["kind"]] = by_kind.get(g["kind"], 0) + 1
        return {
            "bbox": bb.to_dict(), "threshold_m": threshold_m,
            "summary": by_kind, "total": len(gaps), "gaps": gaps,
            "caveat": ("A coverage gap states where the system cannot observe. "
                       "It is never evidence about where a vehicle was."),
        }

    # -- trajectory geometry ------------------------------------------------ #
    def trajectory_geometry(self, hypothesis: dict[str, Any]) -> dict[str, Any]:
        """Turn a solved hypothesis into map geometry.

        Leg kind drives the styling, so the four cases stay visually distinct on
        the map exactly as they are in the data. An OBSERVED leg and a
        COVERAGE_GAP leg drawn as the same line would erase the distinction the
        rest of the system works to preserve.
        """
        cams = {c["camera_id"]: c for c in self.store.list_cameras()}
        nodes = []
        for cid, ts in zip(hypothesis.get("camera_sequence", []),
                           hypothesis.get("timestamps", []), strict=False):
            c = cams.get(cid, {})
            nodes.append({"camera_id": cid, "name": c.get("name"),
                          "lat": c.get("lat"), "lon": c.get("lon"),
                          "district": c.get("district"), "t_norm": ts})
        legs = []
        for leg in hypothesis.get("legs", []):
            a, b = cams.get(leg["from_camera"], {}), cams.get(leg["to_camera"], {})
            legs.append({
                **leg,
                "from_lat": a.get("lat"), "from_lon": a.get("lon"),
                "to_lat": b.get("lat"), "to_lon": b.get("lon"),
                "style": _LEG_STYLE.get(leg.get("kind"), _LEG_STYLE["UNOBSERVED"]),
                "straight_line_m": (
                    round(haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]))
                    if a.get("lat") is not None and b.get("lat") is not None else None),
            })
        return {
            "trajectory_id": hypothesis.get("trajectory_id"),
            "target": hypothesis.get("target"),
            "status": hypothesis.get("status"),
            "score": hypothesis.get("score"),
            "nodes": nodes, "legs": legs,
            "bbox": _bounds([n for n in nodes if n["lat"] is not None]),
            "caveat": ("The line between two cameras is a straight-line link, not "
                       "a driven route. Road geometry is not modelled."),
        }

    # -- alerts ------------------------------------------------------------- #
    def alerts(self, rows: list[dict[str, Any]], *, bbox: BBox | None = None
               ) -> dict[str, Any]:
        bb = bbox or BBox.world()
        cams = {c["camera_id"]: c for c in self.store.list_cameras()}
        feats = []
        for a in rows:
            c = cams.get(a.get("camera_id"), {})
            if not bb.contains(c.get("lat"), c.get("lon")):
                continue
            feats.append({
                "alert_id": a["alert_id"], "plate": a.get("plate"),
                "camera_id": a.get("camera_id"), "name": c.get("name"),
                "lat": c.get("lat"), "lon": c.get("lon"),
                "district": c.get("district"),
                "priority": a.get("priority"), "category": a.get("category"),
                "status": a.get("status"), "confidence": a.get("confidence"),
                "t_norm": a.get("t_norm"),
            })
        return {"bbox": bb.to_dict(), "total": len(feats), "features": feats}


_LEG_STYLE = {
    "OBSERVED": {"stroke": "solid", "weight": 3, "tone": "confirmed"},
    "COVERAGE_GAP": {"stroke": "dotted", "weight": 2, "tone": "unknown"},
    "UNOBSERVED": {"stroke": "dashed", "weight": 2, "tone": "weak"},
    "CONTRADICTION": {"stroke": "dashed", "weight": 3, "tone": "conflict"},
}


def _bounds(nodes: list[dict[str, Any]]) -> dict[str, float] | None:
    if not nodes:
        return None
    lats = [n["lat"] for n in nodes]
    lons = [n["lon"] for n in nodes]
    return {"south": min(lats), "west": min(lons),
            "north": max(lats), "east": max(lons)}


def _round(v: Any, places: int) -> float | None:
    return None if v is None else round(float(v), places)


def as_epoch(dt: datetime | None) -> float | None:
    return None if dt is None else dt.timestamp()
