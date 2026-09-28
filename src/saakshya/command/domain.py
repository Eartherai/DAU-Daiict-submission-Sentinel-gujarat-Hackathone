"""Provenance of every camera on the 50-camera wall.

Source domains, never mixed in labels:

* GOVERNMENT — supplied Sentinel probe / catalogue cameras.
* OWN_FEED — participant submission feeds (golden Model 4 demo).
* SYNTHETIC_CONTROL — logical / evaluation slots. Never labelled government.
* ARCHIVAL_REPLAY — recorded files, separate from the current government stream.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from saakshya.live.snapshot import local_media_url
from saakshya.store import Store, now_us

log = logging.getLogger(__name__)

GOVERNMENT = "GOVERNMENT"
OWN_FEED = "OWN_FEED"
SYNTHETIC_CONTROL = "SYNTHETIC_CONTROL"

ARCHIVAL_REPLAY = "ARCHIVAL_REPLAY"

DOMAINS = (GOVERNMENT, OWN_FEED, SYNTHETIC_CONTROL, ARCHIVAL_REPLAY)

GOLDEN_OWN_FEEDS = (
    {
        "camera_id": "OWN-PEOPLE",
        "name": "Own Feed A — people corridor",
        "role": "FULL ANALYTICS",
        "district": "Ahmedabad",
        "department": "Own estate",
        "site": "Signal A",
        "lat": 23.0485,
        "lon": 72.5710,
        "quality_note": (
            "OWN SUBMISSION FEED · GOLDEN M4. Person detection, tracking, "
            "alerts, evidence. DEMO / CONTROLLED TEST when a fixture is used."
        ),
    },
    {
        "camera_id": "OWN-TRAFFIC",
        "name": "Own Feed B — traffic overhead",
        "role": "FULL ANALYTICS",
        "district": "Ahmedabad",
        "department": "Own estate",
        "site": "Signal B",
        "lat": 23.0410,
        "lon": 72.5855,
        "quality_note": (
            "OWN SUBMISSION FEED · GOLDEN M4. Vehicles, ANPR, tracking, "
            "watchlist, route. DEMO / CONTROLLED TEST when a fixture is used."
        ),
    },
)

GOLDEN_IDS = tuple(f["camera_id"] for f in GOLDEN_OWN_FEEDS)

_CAM_PROBE = re.compile(r"^cam\d+$", re.IGNORECASE)

ARCHITECTURE_CLAIM = (
    "Centralized analytics and command orchestration with regional media/AI "
    "pools for statewide deployment."
)

ARCHITECTURE_NOT = (
    "Not a claim that all 80,000 cameras are processed or recorded centrally."
)

#: Overlay poll vs AI-plane cadence. FAST lowers HUD latency. DEEP deepens
#: analysis on the AI plane and must not raise browser overlay frequency.
AI_CADENCE = {
    "FAST": {
        "overlay_poll_ms": 400,
        "infer_every": 1,
        "ocr_every": 8,
        "scheduler_mode": "HIGH_PRIORITY",
        "intent": "lowest overlay / admission latency",
    },
    "BALANCED": {
        "overlay_poll_ms": 1000,
        "infer_every": 4,
        "ocr_every": 8,
        "scheduler_mode": "NORMAL",
        "intent": "normal analysis",
    },
    "DEEP": {
        "overlay_poll_ms": 1000,
        "infer_every": 1,
        "ocr_every": 1,
        "scheduler_mode": "FORENSIC",
        "intent": "maximum useful analysis; overlay poll stays bounded",
    },
}


def government_grid_urls(camera_id: str) -> dict[str, str]:
    """Documented Sentinel templates. Credentials never go in the URL."""
    from saakshya.live.grid import GridConfig
    cfg = GridConfig.from_env()
    cid = str(camera_id)
    return {
        "rtsp_url": cfg.rtsp(cid),
        "hls_url": cfg.hls(cid),
        "whep_url": cfg.whep(cid),
    }


def attach_government_grid_urls(store: Store) -> dict[str, Any]:
    """Fill empty RTSP/WHEP URLs on GOVERNMENT registry rows.

    The 50-camera evaluation seed historically stored probe ids without
    endpoints, so the product WHEP proxy stayed off even when Sentinel
    credentials were in the process. This does not invent cameras.
    """
    updated = 0
    for cam in store.list_cameras():
        domain = classify_source_domain(
            cam.get("camera_id"),
            stored=cam.get("source_domain"),
            integration_model=cam.get("integration_model"))
        if domain != GOVERNMENT:
            continue
        if not _CAM_PROBE.match(str(cam.get("camera_id") or "")):
            continue
        urls = government_grid_urls(cam["camera_id"])
        patch = {}
        for key, val in urls.items():
            if not cam.get(key):
                patch[key] = val
        if not patch:
            continue
        store.upsert_camera({"camera_id": cam["camera_id"], **patch})
        updated += 1
    return {"updated": updated, "label": "GOVERNMENT endpoints from GridConfig"}


#: Gujarat Police ranks map onto the six existing product roles. These are
#: operational equivalents, not extra permission sets.
RANK_EQUIVALENCE = (
    {"ranks": "DGP, Addl. DGP, IGP, DIG, SSP",
     "role": "SUPERVISOR", "scope": "statewide",
     "may": "wall, search, watchlist write, investigate, evidence, audit",
     "must_not": "admin user/policy writes"},
    {"ranks": "SP, Addl. SP, DySP / ACP, PI",
     "role": "INVESTIGATOR", "scope": "assigned district",
     "may": "wall, search, alerts, evidence, investigation",
     "must_not": "watchlist write, statewide search, admin"},
    {"ranks": "API, PSI, ASI, HC, PC",
     "role": "OPERATOR", "scope": "assigned district",
     "may": "wall, health, acknowledge alerts",
     "must_not": "plate search, trajectory, evidence export, watchlist write"},
    {"ranks": "IT / estate administrator",
     "role": "ADMIN", "scope": "statewide",
     "may": "users, registry, policy",
     "must_not": "vehicle search"},
    {"ranks": "oversight / audit cell",
     "role": "AUDITOR", "scope": "statewide",
     "may": "audit log and camera identity",
     "must_not": "observations, evidence, search"},
)


def classify_source_domain(camera_id: str | None, *,
                           stored: str | None = None,
                           integration_model: str | None = None) -> str:
    """Resolve provenance. Explicit storage wins; otherwise the id is enough."""
    held = (stored or "").strip().upper()
    if held in DOMAINS:
        return held
    cid = (camera_id or "").strip()
    if not cid:
        return SYNTHETIC_CONTROL
    if cid.upper().startswith("GOVREC-"):
        return ARCHIVAL_REPLAY
    if cid.upper().startswith("OWN-") or cid in GOLDEN_IDS:
        return OWN_FEED
    im = (integration_model or "").strip().upper()
    if im in {"SYNTHETIC", "MOCK", "CONTROL"}:
        return SYNTHETIC_CONTROL
    upper = cid.upper()
    if (upper.startswith("SYN") or upper.startswith("CTL")
            or upper.startswith("C-")):
        return SYNTHETIC_CONTROL
    if _CAM_PROBE.match(cid) or im in {
            "REAL_PROBE_ID", "DIRECT_WHEP", "RTSP_BRIDGE", "RTSP_AI",
            "DIRECT_SENTINEL_WHEP", "RTSP_TRANSCODED_H264"}:
        return GOVERNMENT
    return SYNTHETIC_CONTROL


def tile_status(cam: dict[str, Any], *, local_replay: bool = False) -> str:
    """Operator tile badge. A still is never LIVE."""
    if cam.get("source_domain") == ARCHIVAL_REPLAY:
        return "REPLAY" if local_replay else "NO SIGNAL"
    st = str(cam.get("state") or cam.get("health_state") or "").upper()
    whep = bool(cam.get("whep_capable") or cam.get("whep_url"))
    rtsp = bool(cam.get("rtsp_capable") or cam.get("rtsp_url"))
    if st == "RECONNECTING":
        return "RECONNECTING"
    if st == "DEGRADED":
        return "DEGRADED"
    if st == "STREAMING":
        if whep or local_replay:
            return "LIVE"
        if rtsp:
            return "RTSP_ONLY_AI"
        return "PREVIEW"
    if st in {"DOWN", "FAILED", "OPEN_FAILED"}:
        return "NO SIGNAL"
    if st in {"OBSERVED", "OK"}:
        return "PREVIEW"
    if local_replay:
        return "PREVIEW"
    return "NO SIGNAL"


def annotate_camera(cam: dict[str, Any]) -> dict[str, Any]:
    """Copy a registry/GIS row with domain and tile status filled in."""
    out = dict(cam)
    domain = classify_source_domain(
        out.get("camera_id"),
        stored=out.get("source_domain"),
        integration_model=out.get("integration_model"))
    out["source_domain"] = domain
    cid = str(out.get("camera_id") or "")
    replay = False
    if cid.startswith(("OWN-", "C-", "GOVREC-")):
        replay = bool(local_media_url(cid))
    out["local_replay"] = replay
    out["tile_status"] = tile_status(out, local_replay=replay)
    out["domain_badge"] = {
        GOVERNMENT: "GOVERNMENT",
        OWN_FEED: "OWN FEED",
        SYNTHETIC_CONTROL: "CONTROL",
        ARCHIVAL_REPLAY: "ARCHIVAL REPLAY",
    }[domain]
    if domain == ARCHIVAL_REPLAY:
        from saakshya.live.recordings import recording_metadata
        out.update(recording_metadata(cid))
    if domain == OWN_FEED:
        out["demo_label"] = "DEMO / CONTROLLED TEST"
    return out


def ensure_golden_feeds(store: Store) -> list[str]:
    """Register the two own submission feeds if this store lacks them."""
    created: list[str] = []
    ts = now_us()
    for spec in GOLDEN_OWN_FEEDS:
        cid = spec["camera_id"]
        if store.get_camera(cid):
            store.upsert_camera({
                "camera_id": cid,
                "source_domain": OWN_FEED,
                "quality_note": spec["quality_note"],
            })
            continue
        replay = bool(local_media_url(cid))
        store.upsert_camera({
            "camera_id": cid,
            "name": spec["name"],
            "department": spec["department"],
            "district": spec["district"],
            "site": spec["site"],
            "lat": spec["lat"],
            "lon": spec["lon"],
            "codec": "h264",
            "enabled": True,
            "source_domain": OWN_FEED,
            "integration_model": "OWN_FEED",
            "access_state": "OWN_SUBMISSION",
            "quality_note": spec["quality_note"],
            "location_basis": "OWN_ESTATE",
            "location_precision": "LOCALITY",
            "created_at_us": ts,
            "updated_at_us": ts,
        })
        store.upsert_health(cid, {
            "state": "OBSERVED" if replay else "UNKNOWN",
            "reachable": replay,
        })
        created.append(cid)
    return created


def wall_composition(store: Store, *, target: int = 50) -> dict[str, Any]:
    """50-camera logical wall: government + 2 own + control fill."""
    rows = [annotate_camera(c) for c in store.list_cameras()]
    gov = [c for c in rows if c["source_domain"] == GOVERNMENT]
    own = [c for c in rows if c["source_domain"] == OWN_FEED]
    syn = [c for c in rows if c["source_domain"] == SYNTHETIC_CONTROL]
    golden = [c for c in own if c["camera_id"] in GOLDEN_IDS]
    remaining = max(0, target - len(gov) - 2)
    return {
        "target": target,
        "government": len(gov),
        "own_feed": len(own),
        "golden_own_feeds": [c["camera_id"] for c in golden] or list(GOLDEN_IDS),
        "synthetic_control": len(syn),
        "control_slots_needed": remaining,
        "onboarded": len(rows),
        "note": (
            f"{len(gov)} government + 2 own feeds + labelled control slots "
            f"to {target}. Not {target} government streams."
        ),
        "label": "MEASURED from this store; control slots are SYNTHETIC_CONTROL",
        "cameras": {
            GOVERNMENT: [c["camera_id"] for c in gov],
            OWN_FEED: [c["camera_id"] for c in own],
            SYNTHETIC_CONTROL: [c["camera_id"] for c in syn],
        },
    }


#: How many `camNN` government fixtures the evaluation seeder creates.
#: `enforce_evaluation_50` and `_is_evaluation_fixture` must agree on this
#: number: one builds the keep-set from it and the other decides what it is
#: entitled to delete, and a disagreement between them deletes real data.
SEEDED_GOVERNMENT_CAMERAS = 30


def _is_evaluation_fixture(camera_id: str, cam: dict[str, Any]) -> bool:
    """Was this row created by the evaluation seeder rather than onboarded?

    The seeder makes three shapes: `camNN` government fixtures, the named
    golden own-feeds, and synthetic control slots. Anything else reached the
    registry some other way — most likely a real onboarding — and is not this
    function's to remove.
    """
    if camera_id.startswith("CTL-") or camera_id == "FAR":
        return True
    if camera_id in GOLDEN_IDS:
        return True
    if camera_id.startswith("cam") and camera_id[3:].isdigit():
        # Only the range the seeder actually creates.
        #
        # Unbounded, this branch was reachable *only* in the case it must never
        # fire. `enforce_evaluation_50` puts cam01..cam30 in `wanted` and skips
        # them before asking this question, so the only `camNN` that ever got
        # here was one outside the seeded range — which is to say, one that was
        # onboarded. The evaluation grid names its cameras this way, and the
        # challenge supplies about fifty of them, so onboarding cam31..cam50
        # and restarting the API deleted exactly the cameras being evaluated,
        # silently, at startup.
        return 1 <= int(camera_id[3:]) <= SEEDED_GOVERNMENT_CAMERAS
    return (cam.get("source_domain") or "").upper() == SYNTHETIC_CONTROL


def enforce_evaluation_50(store: Store) -> dict[str, Any]:
    """Keep exactly 30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL.

    Extra fixtures such as FAR are removed from the registry so onboarded=50.
    Does not re-insert cameras that already exist (seed is insert-only).
    """
    from saakshya.command.scale import seed_50_evaluation
    existing = {c["camera_id"] for c in store.list_cameras()}
    gov_have = sum(1 for cid in existing if cid.startswith("cam") and cid[3:].isdigit())
    if gov_have < 30 or "OWN-PEOPLE" not in existing:
        seed_50_evaluation(store)
    wanted: set[str] = {f"cam{i:02d}"
                        for i in range(1, SEEDED_GOVERNMENT_CAMERAS + 1)}
    wanted.update(GOLDEN_IDS)
    syn_ids = [
        c["camera_id"] for c in store.list_cameras()
        if (c.get("source_domain") or "").upper() == SYNTHETIC_CONTROL
        and not str(c["camera_id"]).startswith("CTL-SLOT")
        and c["camera_id"] != "FAR"
    ]
    syn_ids.sort()
    wanted.update(syn_ids[:18])
    removed: list[str] = []
    for cam in store.list_cameras():
        cid = str(cam["camera_id"])
        if cid in wanted:
            continue
        # Prune this function's own fixtures, and nothing else.
        #
        # This used to delete every camera it did not recognise, which made the
        # registry's onboarding endpoints pointless: a department could import
        # a spreadsheet, see the cameras appear, and find them gone after the
        # next restart, with no error anywhere. A fixture guard is entitled to
        # tidy up its own fixtures; it is not entitled to delete an operator's
        # data because it does not recognise the name.
        if not _is_evaluation_fixture(cid, cam):
            continue
        try:
            store.delete_camera(cid)
        except ValueError as exc:
            # A department put a zone rule on it: not ours to remove.
            log.warning("kept fixture camera %s: %s", cid, exc)
            continue
        removed.append(cid)
    comp = wall_composition(store, target=50)
    return {"removed": removed, "composition": comp, "onboarded": comp["onboarded"]}


def jump_playback(store: Store, camera_id: str, *,
                  pts_s: float | None) -> dict[str, Any]:
    """Honest seek contract: own-feed files can seek; live WHEP cannot."""
    replay = bool(local_media_url(camera_id))
    domain = classify_source_domain(
        camera_id,
        stored=(store.get_camera(camera_id) or {}).get("source_domain"))
    if replay and domain == OWN_FEED:
        return {
            "kind": "OWN_FEED_REPLAY",
            "seekable": True,
            "event_pts_s": pts_s,
            "current_live_position": None,
            "note": ("Own-feed recording can seek to the event PTS. "
                     "This is replay, not a second live session."),
        }
    if replay:
        return {
            "kind": "FILE_REPLAY",
            "seekable": True,
            "event_pts_s": pts_s,
            "current_live_position": None,
            # Shown to the officer in the jump dialog; "source_domain" was a
            # field name, not something they could act on.
            "note": "Recorded file replay — not a live government feed.",
        }
    return {
        "kind": "LIVE_POSITION",
        "seekable": False,
        "event_pts_s": pts_s,
        "current_live_position": "CURRENT LIVE POSITION",
        "note": ("Live WHEP/RTSP cannot seek to an arbitrary event time. "
                 "EVENT TIMESTAMP is the observation; the player shows now."),
    }


def product_modes() -> list[dict[str, Any]]:
    return [
        {"id": "operations", "label": "OPERATIONS",
         "view": "live", "wall": 30,
         "purpose": "30/50 camera wall — government interoperability"},
        {"id": "intelligence", "label": "INTELLIGENCE",
         "view": "intelligence", "wall": 2,
         "purpose": "Model 4 central analytics on own golden feeds"},
        {"id": "investigation", "label": "INVESTIGATION",
         "view": "investigate",
         "purpose": "Target / incident workflow: track, route, evidence"},
        {"id": "system", "label": "SYSTEM",
         "view": "system",
         "purpose": "Health, VMS connectors, capacity, AI workers, audit"},
    ]


def architecture_diagram() -> dict[str, Any]:
    return {
        "claim": ARCHITECTURE_CLAIM,
        "not_claimed": ARCHITECTURE_NOT,
        "planes": {
            "video": "WHEP / HLS / stills — browser viewing",
            "ai": "RTSP/TCP detection, ANPR, tracking, ReID, watchlist, alerts",
        },
        "layers": [
            "CAMERA SOURCES",
            "REGIONAL INGEST LAYER",
            "MEDIA / EVENT FABRIC",
            "VIDEO PLANE | AI PLANE",
            "COMMAND CENTER",
            "VIDEO · GIS · INVESTIGATION",
        ],
        "golden_feeds": list(GOLDEN_IDS),
        "label": "DESIGNED architecture. Statewide GPU pools are not measured here.",
    }
