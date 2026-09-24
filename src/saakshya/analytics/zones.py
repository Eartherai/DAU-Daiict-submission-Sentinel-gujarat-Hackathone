"""Restricted-zone entries, against a rule a department wrote.

The challenge lists intrusion detection. This platform does not call a person
an intruder on its own: whether someone may stand somewhere is a question of
permission, and permission is the department's to state. So a department
states it - a zone drawn on a camera's frame, the hours it applies, which
classes it concerns - and the platform reports every stored sighting whose
position falls inside that zone inside those hours. The rule is the judgement;
the report is a measurement against it.

A sighting's position is the bottom centre of its box: where a person's feet
or a vehicle's wheels meet the ground, which is what a zone drawn on the road
or the pavement is about. Boxes are in the camera's own frame pixels, and so
is the polygon.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from saakshya.common.ist import iso_ist, to_ist


def inside(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Even-odd ray casting; a point on the boundary counts as inside."""
    hit = False
    n = len(polygon)
    for i in range(n):
        (x1, y1), (x2, y2) = polygon[i], polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x <= cross:
                hit = not hit
    return hit


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_hours(when: datetime, active_from: str | None, active_to: str | None) -> bool:
    """Whether an IST time falls in the rule's hours; a window may wrap midnight."""
    if not active_from or not active_to:
        return True
    t = to_ist(when)
    if t is None:
        return False
    now = t.hour * 60 + t.minute
    a, b = _minutes(active_from), _minutes(active_to)
    return a <= now < b if a <= b else (now >= a or now < b)


def rule_view(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["polygon"] = json.loads(row.get("polygon") or "[]")
    out["classes"] = json.loads(row.get("classes") or '["person"]')
    return out


def entries(store: Any, rule: dict[str, Any], *, t_from: datetime | None = None,
            t_to: datetime | None = None, limit: int = 200) -> dict[str, Any]:
    """Stored sightings on the rule's camera inside its zone and its hours."""
    from sqlalchemy import select

    from saakshya.store import schema as S
    from saakshya.store.repository import from_us, to_us

    rule = rule_view(rule)
    O = S.observations
    want = set(rule["classes"])
    where = [O.c.camera_id == rule["camera_id"], O.c.bbox_x1.is_not(None)]
    if want == {"person"}:
        where.append(O.c.object_type == "person")
    elif "person" not in want:
        where.append(O.c.object_type != "person")
    if t_from:
        where.append(O.c.t_norm_us >= to_us(t_from))
    if t_to:
        where.append(O.c.t_norm_us <= to_us(t_to))
    q = (select(O.c.observation_id, O.c.t_norm_us, O.c.object_type, O.c.bbox_x1,
                O.c.bbox_y1, O.c.bbox_x2, O.c.bbox_y2, O.c.model_versions)
         .where(*where).order_by(O.c.t_norm_us.desc()).limit(50_000))
    examined = 0
    hits: list[dict[str, Any]] = []
    with store.engine.connect() as c:
        for r in c.execute(q):
            examined += 1
            when = from_us(r.t_norm_us)
            if when is None or not in_hours(when, rule["active_from"], rule["active_to"]):
                continue
            fx, fy = (r.bbox_x1 + r.bbox_x2) / 2.0, float(r.bbox_y2)
            if not inside(fx, fy, rule["polygon"]):
                continue
            dwell = None
            try:
                dwell = json.loads(r.model_versions or "{}").get("dwell_s")
            except (TypeError, ValueError):
                pass
            hits.append({"observation_id": r.observation_id, "t_norm": when.isoformat(),
                         "t_ist": iso_ist(when), "object_type": r.object_type,
                         "position": [round(fx, 1), round(fy, 1)], "dwell_s": dwell})
    return {"rule": rule, "entries": hits[:limit], "count": len(hits),
            "examined": examined,
            "note": "a sighting inside the department's zone during its hours; "
                    "position is the bottom centre of the box. Not an identity."}
