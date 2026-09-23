"""Alert rows → what a control-room officer can act on.

The alert table is the audit vocabulary: one row per (vehicle, watchlist entry)
per cooldown window, which is right for the record and wrong for a queue. On the
evaluation store 128 open rows were thirteen vehicles, every one printed as
HIGH, and the queue read as spam rather than correlation. This module does the
three things the queue needs and the table cannot:

**Grouping.** One incident per (plate, watchlist entry). Inside it, reads that
arrive within a configurable window of the previous one are the same *pass*
(Genetec calls this the duplicate-hit delay); a read after the window is the
vehicle seen again, and is counted as a new pass inside the same incident rather
than as a new incident.

**Honest priority.** The listed priority is the watchlist entry's. A read that
rests on a single frame is a lead, not a hit, and is shown one step lower with
the reason in words. A vehicle seen on several distinct cameras is shown one
step higher, with the camera count as the reason.

**Read against list.** The read plate and the listed plate are aligned
character by character, and every difference is classed as an OCR confusion
(0/O, 5/S, 8/B …) or a genuine difference, so "✓ EXACT" and "≈ NEAR" are
claims the officer can check by eye.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from saakshya.analytics.plates import CONFUSIONS, normalise
from saakshya.store import Store
from saakshya.store import schema as S

PRIORITY_ORDER = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

#: Default duplicate-hit window. Ten minutes follows Genetec's default: long
#: enough that one pass under one camera is one hit, short enough that the same
#: vehicle returning after lunch is visibly a second pass.
DEFAULT_WINDOW_S = 600

#: Distinct cameras that raise a shown priority one step. Mirrors
#: AlertPolicy.escalate_after_cameras so the two never tell different stories.
ESCALATE_AFTER_CAMERAS = 3

#: How a closed alert was closed. Required on resolve, because "resolved" alone
#: cannot tell a recovered vehicle from a misread from a lawful owner, and the
#: false-positive rate per camera is only measurable if the reason is recorded.
DISPOSITIONS = {
    "confirmed": "Confirmed — vehicle of interest verified",
    "false_positive": "False positive — misread or different vehicle",
    "cleared": "Cleared — no further action",
}

#: Human labels for categories. The stored value stays the audit vocabulary.
CATEGORY_LABEL = {
    "stolen_vehicle": "stolen vehicle",
    "wanted_vehicle": "wanted vehicle",
    "suspect_vehicle": "suspect vehicle",
    "blacklisted_vehicle": "blacklisted vehicle",
    "investigation_target": "investigation target",
    "evaluation_designated": "designated vehicle of interest (evaluation)",
    "missing_person_associated": "linked to a missing person",
    "custom": "custom list",
}


def _step(priority: str, delta: int) -> str:
    try:
        i = PRIORITY_ORDER.index(str(priority).upper())
    except ValueError:
        return priority
    return PRIORITY_ORDER[max(0, min(len(PRIORITY_ORDER) - 1, i + delta))]


def derive_priority(listed: str, *, votes: int | None, cameras: int,
                    escalate_after: int = ESCALATE_AFTER_CAMERAS
                    ) -> tuple[str, str]:
    """The priority to show, and the words that justify it.

    Every alert on the evaluation store printed HIGH, including forty whose
    plate rested on one frame and which the engine itself annotated "verify
    before acting". A priority that cannot tell those apart is noise, so a
    single-frame read is shown one step below the entry's priority, and says
    why. Escalation for several cameras is applied first, because three
    independent cameras agreeing is stronger corroboration than frame votes on
    one camera; the two never both apply.
    """
    listed = str(listed or "MEDIUM").upper()
    if cameras >= escalate_after:
        return (_step(listed, +1),
                f"seen on {cameras} distinct cameras — escalated from {listed}")
    if votes is None:
        return (_step(listed, -1),
                "frame count not recorded — verify before acting")
    if votes < 2:
        return (_step(listed, -1),
                "single-frame read — verify before acting")
    return listed, f"plate agreed across {votes} frames"


# --------------------------------------------------------------------------- #
# Read plate against listed plate
# --------------------------------------------------------------------------- #
def _confusable(a: str, b: str) -> bool:
    return b in CONFUSIONS.get(a, ())


def compare_plates(read: str | None, listed: str | None) -> dict[str, Any]:
    """Align the read mark with the listed mark, character by character.

    A plain edit-distance alignment where swapping two OCR-confusable characters
    costs half a substitution, so the alignment prefers to explain a difference
    as a misread before calling it a different character. Each position is
    ``same``, ``confusion`` (an OCR lookalike), ``differ`` or ``gap``.
    """
    r = normalise(read or "")
    l = normalise(listed or "")
    n, m = len(r), len(l)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back: list[list[str]] = [[""] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, how = INF, ""
            if i and j:
                if r[i - 1] == l[j - 1]:
                    c = 0.0
                elif _confusable(r[i - 1], l[j - 1]):
                    c = 0.5
                else:
                    c = 1.0
                if cost[i - 1][j - 1] + c < best:
                    best, how = cost[i - 1][j - 1] + c, "d"
            if i and cost[i - 1][j] + 1 < best:
                best, how = cost[i - 1][j] + 1, "u"      # read has an extra char
            if j and cost[i][j - 1] + 1 < best:
                best, how = cost[i][j - 1] + 1, "l"      # read is missing a char
            cost[i][j], back[i][j] = best, how
    positions: list[dict[str, str]] = []
    i, j = n, m
    while i or j:
        how = back[i][j]
        if how == "d":
            a, b = r[i - 1], l[j - 1]
            state = ("same" if a == b else
                     "confusion" if _confusable(a, b) else "differ")
            positions.append({"read": a, "listed": b, "state": state})
            i, j = i - 1, j - 1
        elif how == "u":
            positions.append({"read": r[i - 1], "listed": "", "state": "gap"})
            i -= 1
        else:
            positions.append({"read": "", "listed": l[j - 1], "state": "gap"})
            j -= 1
    positions.reverse()
    diffs = [p for p in positions if p["state"] != "same"]
    if not diffs and r:
        kind, summary = "EXACT", "✓ EXACT — every character agrees"
    elif diffs and all(p["state"] == "confusion" for p in diffs) and len(diffs) <= 2:
        kind = "NEAR"
        pairs = ", ".join(f"{p['read']}↔{p['listed']}" for p in diffs)
        summary = (f"≈ NEAR — {len(diffs)} character(s) differ by an OCR "
                   f"lookalike ({pairs})")
    else:
        kind = "DIFFERENT"
        summary = f"≠ {len(diffs)} character(s) differ"
    return {"kind": kind, "read": r, "listed": l, "positions": positions,
            "differing": len(diffs), "summary": summary}


# --------------------------------------------------------------------------- #
# Enrichment and grouping
# --------------------------------------------------------------------------- #
def _blob(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("match_reason")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return out if isinstance(out, dict) else {}


def _chunks(items: list[str], size: int = 400):
    for k in range(0, len(items), size):
        yield items[k:k + size]


def enrich(store: Store, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add what the queue shows and the table does not store directly.

    Frame votes are read from the observations themselves. The alert's own
    ``terms`` only carried ``plate_votes`` on the first sighting, and a repeat
    sighting replaced the terms, so reading them there showed "votes unknown"
    for alerts whose observations were voted across a dozen frames.
    """
    if not rows:
        return []
    blobs = [_blob(r) for r in rows]
    obs_ids: set[str] = set()
    for r, b in zip(rows, blobs, strict=True):
        ids = [x for x in (b.get("observation_ids") or []) if isinstance(x, str)]
        if r.get("observation_id"):
            ids.append(r["observation_id"])
        obs_ids.update(ids)
    wl_ids = sorted({r["watchlist_id"] for r in rows if r.get("watchlist_id")})

    votes: dict[str, int | None] = {}
    bbox: dict[str, list[float] | None] = {}
    evidence: dict[str, dict[str, Any]] = {}
    entries: dict[str, dict[str, Any]] = {}
    camera_meta: dict[str, dict[str, Any]] = {}
    with store.engine.connect() as c:
        O = S.observations
        for chunk in _chunks(sorted(obs_ids)):
            for o in c.execute(select(O.c.observation_id, O.c.plate_votes,
                                      O.c.bbox_x1, O.c.bbox_y1, O.c.bbox_x2,
                                      O.c.bbox_y2).where(O.c.observation_id.in_(chunk))):
                votes[o.observation_id] = o.plate_votes
                if None not in (o.bbox_x1, o.bbox_y1, o.bbox_x2, o.bbox_y2):
                    bbox[o.observation_id] = [o.bbox_x1, o.bbox_y1, o.bbox_x2, o.bbox_y2]
            E = S.evidence
            for e in c.execute(select(E.c.evidence_id, E.c.observation_id,
                                      E.c.frame_path, E.c.frame_sha256,
                                      E.c.created_at_us)
                               .where(E.c.observation_id.in_(chunk))
                               .order_by(E.c.created_at_us.asc())):
                # The first sealed record is the one the evidence service
                # treats as canonical (find_by_observation), so it is the one
                # shown here. Later duplicates are left out, not merged.
                evidence.setdefault(e.observation_id, {
                    "evidence_id": e.evidence_id,
                    "has_frame": bool(e.frame_path),
                    "frame_sha256": e.frame_sha256,
                })
        W = S.watchlist
        for chunk in _chunks(wl_ids):
            for w in c.execute(select(W).where(W.c.watchlist_id.in_(chunk))):
                m = w._mapping
                entries[m["watchlist_id"]] = {
                    "plate": m["plate"], "category": m["category"],
                    "priority": m["priority"], "reason": m["reason"],
                    "authority": m["authority"], "status": m["status"],
                    "source_system": m["source_system"], "version": m["version"],
                }
        cams = sorted({r.get("camera_id") for r in rows if r.get("camera_id")})
        Cm = S.cameras
        for chunk in _chunks(cams):
            for cam in c.execute(select(Cm.c.camera_id, Cm.c.name, Cm.c.district)
                                 .where(Cm.c.camera_id.in_(chunk))):
                camera_meta[cam.camera_id] = {"name": cam.name,
                                              "district": cam.district}

    out: list[dict[str, Any]] = []
    for r, b in zip(rows, blobs, strict=True):
        ids = [x for x in (b.get("observation_ids") or []) if isinstance(x, str)]
        if r.get("observation_id") and r["observation_id"] not in ids:
            ids.insert(0, r["observation_id"])
        known = [votes[i] for i in ids if votes.get(i) is not None]
        best_votes = max(known) if known else None
        cameras = [x for x in (b.get("cameras") or []) if isinstance(x, str)] \
            or ([r["camera_id"]] if r.get("camera_id") else [])
        entry = entries.get(r.get("watchlist_id") or "", {})
        listed_priority = entry.get("priority") or r.get("priority") or "MEDIUM"
        shown, why = derive_priority(listed_priority, votes=best_votes,
                                     cameras=len(set(cameras)))
        # The newest sealed read is the one worth looking at; fall back to any
        # sealed read of this alert, and say so when there is none at all.
        ev = None
        for oid in reversed(ids):
            cand = evidence.get(oid)
            if cand and cand["has_frame"]:
                ev = {**cand, "observation_id": oid, "bbox": bbox.get(oid)}
                break
        listed_plate = entry.get("plate") or r.get("plate")
        lifecycle = []
        if r.get("lifecycle"):
            try:
                lifecycle = json.loads(r["lifecycle"]) or []
            except (TypeError, ValueError):
                lifecycle = []
        match = compare_plates(r.get("plate"), listed_plate)
        cam = camera_meta.get(r.get("camera_id") or "", {})
        out.append({
            **r,
            "observation_ids": ids,
            "cameras": cameras,
            "plate_votes": best_votes,
            "corroborated": bool(best_votes and best_votes >= 2),
            "listed_priority": listed_priority,
            "display_priority": shown,
            "priority_reason": why,
            "notes": b.get("notes") or [],
            "terms": b.get("terms") or {},
            "watchlist": {**entry, "category_label": CATEGORY_LABEL.get(
                entry.get("category") or r.get("category") or "",
                (entry.get("category") or r.get("category") or "").replace("_", " "))},
            "listed_plate": listed_plate,
            "match": match,
            "lane": "hotlist" if match["kind"] == "EXACT" else "near",
            "evidence": ev,
            "camera_name": cam.get("name"),
            "district": cam.get("district"),
            "lifecycle": lifecycle,
        })
    return out


def group(rows: list[dict[str, Any]], *, window_s: int = DEFAULT_WINDOW_S
          ) -> list[dict[str, Any]]:
    """Fold enriched alerts into incidents, newest activity first.

    One incident per (plate, watchlist entry). ``passes`` counts runs of reads
    separated by more than ``window_s``: a vehicle idling under one camera for
    eight minutes is one pass; the same vehicle back two hours later is a
    second pass, shown as "seen again", not as a second incident.
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        buckets[(r.get("plate") or "", r.get("watchlist_id") or "")].append(r)
    groups: list[dict[str, Any]] = []
    for (plate, wl), members in buckets.items():
        members.sort(key=lambda a: a.get("t_norm_us") or 0)
        passes = 0
        last = None
        for a in members:
            t = a.get("t_norm_us") or 0
            if last is None or (t - last) > window_s * 1_000_000:
                passes += 1
            last = t
        latest = members[-1]
        first = members[0]
        cameras: list[str] = []
        for a in members:
            for cam in a.get("cameras") or []:
                if cam not in cameras:
                    cameras.append(cam)
        known = [a["plate_votes"] for a in members if a.get("plate_votes") is not None]
        best_votes = max(known) if known else None
        listed = latest.get("listed_priority") or "MEDIUM"
        shown, why = derive_priority(listed, votes=best_votes, cameras=len(cameras))
        statuses: dict[str, int] = defaultdict(int)
        for a in members:
            statuses[str(a.get("status") or "OPEN")] += 1
        # The thumbnail is the newest read that was actually sealed with a
        # frame, so the picture and the "last seen" line describe one moment
        # whenever they can.
        ev = next((a["evidence"] for a in reversed(members) if a.get("evidence")), None)
        ev_alert = next((a["alert_id"] for a in reversed(members) if a.get("evidence")), None)
        single = sum(1 for a in members if not a.get("corroborated"))
        groups.append({
            "group_id": f"{plate}:{wl}",
            "plate": plate,
            "watchlist_id": wl,
            "category": latest.get("category"),
            "watchlist": latest.get("watchlist") or {},
            "count": len(members),
            # Reads, not alert rows: repeat sightings are folded into one
            # alert's observation_ids, so "1 read · 2 cameras" was printed for
            # an alert that rested on six reads across two cameras.
            "reads": len({o for a in members for o in (a.get("observation_ids") or [])})
                     or len(members),
            "passes": passes,
            "window_s": window_s,
            "cameras": cameras,
            "camera_count": len(cameras),
            "first_seen": first.get("t_norm"),
            "first_seen_us": first.get("t_norm_us"),
            "last_seen": latest.get("t_norm"),
            "last_seen_us": latest.get("t_norm_us"),
            "latest_alert_id": latest.get("alert_id"),
            "latest_camera_id": latest.get("camera_id"),
            "latest_camera_name": latest.get("camera_name"),
            "latest_district": latest.get("district"),
            "latest_observation_id": (latest.get("observation_ids") or [None])[-1],
            "alert_ids": [a["alert_id"] for a in members],
            "statuses": dict(statuses),
            "open": statuses.get("OPEN", 0),
            "max_confidence": max((a.get("confidence") or 0.0) for a in members),
            "plate_votes": best_votes,
            "single_frame_alerts": single,
            "listed_priority": listed,
            "display_priority": shown,
            "priority_reason": why,
            "lane": "hotlist" if all(a.get("lane") == "hotlist" for a in members) else "near",
            "match": latest.get("match"),
            "listed_plate": latest.get("listed_plate"),
            "notes": latest.get("notes") or [],
            "recommended_action": latest.get("recommended_action"),
            "evidence": ev,
            "evidence_alert_id": ev_alert,
            "lifecycle": latest.get("lifecycle") or [],
            "members": [{
                "alert_id": a["alert_id"], "t_norm": a.get("t_norm"),
                "t_norm_us": a.get("t_norm_us"), "camera_id": a.get("camera_id"),
                "camera_name": a.get("camera_name"), "status": a.get("status"),
                "plate_votes": a.get("plate_votes"),
                "display_priority": a.get("display_priority"),
                "confidence": a.get("confidence"),
                "observation_id": (a.get("observation_ids") or [None])[-1],
                "evidence_id": (a.get("evidence") or {}).get("evidence_id"),
            } for a in reversed(members)],
        })
    rank = {p: i for i, p in enumerate(PRIORITY_ORDER)}
    groups.sort(key=lambda g: (g["last_seen_us"] or 0), reverse=True)
    # Stable second sort: priority first, recency inside a priority.
    groups.sort(key=lambda g: rank.get(g["display_priority"], 0), reverse=True)
    return groups


def status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Counts per operator tab, so the tabs can say "New 126 · Ack 3"."""
    out = {"OPEN": 0, "ACKNOWLEDGED": 0, "INVESTIGATING": 0, "RESOLVED": 0, "ALL": 0}
    for r in rows:
        s = str(r.get("status") or "OPEN")
        out["ALL"] += 1
        if s in ("CLEARED", "FALSE_POSITIVE"):
            out["RESOLVED"] += 1
        elif s in out:
            out[s] += 1
    return out
