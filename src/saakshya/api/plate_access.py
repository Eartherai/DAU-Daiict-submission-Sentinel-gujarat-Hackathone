"""One rule for every route that hands out a registration mark.

The vehicle search was guarded properly: search:plate, a case, a purpose, an
audit entry. The same data also left the system through six side doors that
asked only for camera:read — the Overview's "Marks, with location" strip, the
ANPR report download, the Intelligence view's recent reads, the jump-to-event
payload, the per-camera plate strip and the plate crop. An ADMIN or AUDITOR,
refused at /search, could read every plate with place and time from the home
screen, and nothing recorded that they had.

The rule, applied here and nowhere else so it cannot drift between routes:

* **Stored marks** (any list of plates with camera and time, or one
  observation's plate) need search:plate — the permission the search needs —
  are filtered to the caller's jurisdiction, and every read is audited.
* **Plate text drawn over a live or recorded picture** is released to roles
  that act on vehicles (search:plate or alert:ack). For anyone else the box is
  still drawn, without the text, and the payload says it was withheld.

Purpose binding is deliberately *not* extended to the recent-marks strip: it
is not a targeted query, and demanding a case id to render the home screen
would push officers to invent one. It is audited instead, and a case id sent
with it is recorded.
"""
from __future__ import annotations

from typing import Any

from saakshya.api.deps import access_error
from saakshya.security import (
    AccessError,
    AuthContext,
    Permission,
    may_read_plates,
    may_see_live_plates,
)
from saakshya.store import Store

#: Keys under which a box or a track may carry machine-read plate text.
_PLATE_KEYS = ("plate", "plate_text", "plate_raw", "ocr_text")


def require_plate_read(ctx: AuthContext) -> None:
    """Refuse, as the search would, a caller who may not read stored marks."""
    try:
        ctx.principal.require(Permission.SEARCH_PLATE)
    except AccessError as exc:
        raise access_error(exc) from exc


def in_scope(ctx: AuthContext, rows: list[dict[str, Any]],
             store: Store | None = None) -> list[dict[str, Any]]:
    """Drop rows outside the caller's jurisdiction.

    `recent_marks` is statewide by construction. A district investigator
    reading it saw Surat's plates from Ahmedabad. A row with no district is
    resolved through its camera, and one that still has none is dropped:
    failing closed, as `Principal.in_scope` does.
    """
    if ctx.principal.statewide:
        return rows
    out = []
    for r in rows:
        district = r.get("district")
        if not district and store is not None and r.get("camera_id"):
            district = (store.get_camera(str(r["camera_id"])) or {}).get("district")
        if ctx.principal.in_scope(district):
            out.append(r)
    return out


def audit_plate_read(ctx: AuthContext, store: Store, action: str, *,
                     target: str, rows: int) -> None:
    ctx.audit(store, action, target=target, result_count=rows)


def redact_boxes(ctx: AuthContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Blank plate text in an overlay payload for roles that may not see it."""
    if may_see_live_plates(ctx.principal):
        return payload
    # New dicts, never an edit in place: the overlay rows come from a cache
    # shared by every caller, and blanking them there once hid the plates
    # from the next operator to poll the same camera.
    payload["boxes"] = [
        ({**box, **{k: None for k in _PLATE_KEYS if box.get(k)}}
         if isinstance(box, dict) else box)
        for box in payload.get("boxes") or []]
    payload["plates_withheld"] = True
    payload["plates_withheld_reason"] = (
        "Plate text is shown to officers who act on vehicles (investigators, "
        "supervisors, control-room operators). The boxes are drawn; the "
        "registration marks are withheld from this role.")
    return payload


def redact_tracks(ctx: AuthContext, data: dict[str, Any]) -> dict[str, Any]:
    """The own-feed frame track, with its plate column blanked if needed.

    Each frame entry is [x1, y1, x2, y2, type, track, score, plate, votes];
    position 7 is the plate text.
    """
    if may_see_live_plates(ctx.principal):
        return data

    def _blank(det: Any) -> Any:
        if isinstance(det, list) and len(det) > 7 and det[7]:
            return [*det[:7], "", *det[8:]]
        return det

    out = dict(data)
    out["frames"] = [
        [frame[0], [_blank(d) for d in (frame[1] or [])], *frame[2:]]
        if isinstance(frame, list) and len(frame) >= 2 else frame
        for frame in data.get("frames") or []]
    if data.get("plates_accepted"):
        out["plates_accepted"] = []
    out["plates_withheld"] = True
    return out


def plates_visible(ctx: AuthContext) -> bool:
    return may_read_plates(ctx.principal)


#: Case items whose reference or payload is a registration mark or a sighting.
_PLATE_ITEMS = {"target", "observation", "trajectory"}


def redact_case_items(ctx: AuthContext, items: list[dict[str, Any]]
                      ) -> list[dict[str, Any]]:
    """A case file read by a role without search:plate keeps its shape — what
    was attached, by whom, when — without the marks and sightings themselves.
    ADMIN and OPERATOR hold case:read so they can see that a case exists and
    who is working it; that was never meant to include its vehicles."""
    if may_read_plates(ctx.principal):
        return items
    out = []
    for it in items:
        if it.get("item_type") in _PLATE_ITEMS:
            it = {**it, "item_ref": "withheld", "payload": {"withheld": True}}
        out.append(it)
    return out
