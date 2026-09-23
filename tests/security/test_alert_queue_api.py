"""The alert queue over HTTP: grouping, lifecycle and the evidence still.

Written the way the rest of this directory is: each access test tries to get
something it should not, and passes only when refused for the right reason.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.security import Role, TokenService
from saakshya.store import VehicleObservation
from saakshya.store import schema as S
from saakshya.watchlist import (
    AlertEngine,
    AlertPolicy,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)

T0 = datetime(2026, 9, 21, 4, 0, 0, tzinfo=UTC)
PLATE = "GJ05ZZ0101"        # fictional
PLATE_B = "GJ05ZZ0202"      # fictional, in the other district


def _ob(cam, district, plate, minute, key, votes=4):
    t = T0 + timedelta(minutes=minute)
    return VehicleObservation(camera_id=cam, pts_s=minute * 60.0, t_norm=t,
                              t_ingest=t, dedup_key=key, plate=plate,
                              object_type="car", observation_quality=0.9,
                              plate_confidence=0.97, plate_votes=votes,
                              bbox=(40.0, 30.0, 200.0, 150.0), district=district)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("alertq")
    state = AppState(f"sqlite:///{tmp / 'api.db'}", evidence_root=tmp / "evidence")
    state.require_auth = True
    store = state.store
    store.upsert_camera({"camera_id": "CAM-A", "name": "A-1", "district": "Ahmedabad",
                         "tier": "A", "enabled": True})
    store.upsert_camera({"camera_id": "CAM-B", "name": "B-1", "district": "Gandhinagar",
                         "tier": "A", "enabled": True})
    wl = WatchlistService(store)
    eng = AlertEngine(store, AlertPolicy(cooldown_s=60))
    for plate in (PLATE, PLATE_B):
        wl.add(VehicleOfInterest(plate=plate, category=Category.WANTED_VEHICLE,
                                 authority="test authority",
                                 reason="fictional entry under test",
                                 priority=Priority.HIGH))
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[30:150, 40:200] = (0, 0, 255)
    evidence = {}
    for k, minute in enumerate((0, 30, 60, 90)):
        o = _ob("CAM-A", "Ahmedabad", PLATE, minute, f"a{k}", votes=1 if k == 0 else 5)
        store.add_observations([o])
        eng.process(wl.match(o)[0])
        evidence[k] = state.evidence.create(o, frame=frame).evidence_id
    ob = _ob("CAM-B", "Gandhinagar", PLATE_B, 10, "b0")
    store.add_observations([ob])
    eng.process(wl.match(ob)[0])
    loose = _ob("CAM-A", "Ahmedabad", "GJ05ZZ0999", 5, "loose")
    store.add_observations([loose])
    unrelated = state.evidence.create(loose, frame=frame).evidence_id

    ts = TokenService(store)
    ts.upsert_user("sup.1", Role.SUPERVISOR)
    ts.upsert_user("op.a", Role.OPERATOR, districts=("Ahmedabad",))
    ts.upsert_user("audit.1", Role.AUDITOR)
    tokens = {u: ts.mint(u) for u in ("sup.1", "op.a", "audit.1")}
    state.investigation.refresh()
    client = TestClient(create_app(state), raise_server_exceptions=False)
    return {"client": client, "tokens": tokens, "state": state,
            "evidence": evidence, "unrelated": unrelated}


def h(world, user):
    return {"Authorization": f"Bearer {world['tokens'][user]}"}


def test_grouped_view_is_one_row_per_vehicle(world):
    r = world["client"].get("/alerts?grouped=true&status=OPEN", headers=h(world, "sup.1"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert_count"] == 5
    assert body["group_count"] == 2
    g = next(x for x in body["groups"] if x["plate"] == PLATE)
    assert g["count"] == 4 and g["camera_count"] == 1
    assert g["passes"] == 4, "30-minute gaps exceed the 10-minute window"
    assert g["evidence"]["evidence_id"] == world["evidence"][3], "newest sealed read"
    assert g["first_seen"] and g["last_seen"]
    assert body["status_counts"]["OPEN"] == 5


def test_ungrouped_view_still_answers_with_alerts(world):
    r = world["client"].get("/alerts?status=OPEN&limit=2", headers=h(world, "sup.1"))
    assert r.status_code == 200
    body = r.json()
    assert len(body["alerts"]) == 2
    a = body["alerts"][0]
    for key in ("alert_id", "plate", "t_norm", "display_priority",
                "priority_reason", "match", "evidence"):
        assert key in a


def test_single_frame_alert_is_shown_below_its_listed_priority(world):
    body = world["client"].get("/alerts?status=OPEN&limit=50",
                               headers=h(world, "sup.1")).json()
    first = min((a for a in body["alerts"] if a["plate"] == PLATE),
                key=lambda a: a["t_norm_us"])
    assert first["listed_priority"] == "HIGH"
    assert first["display_priority"] == "MEDIUM"
    assert "single-frame" in first["priority_reason"]


def test_operator_cannot_see_or_touch_another_districts_alert(world):
    body = world["client"].get("/alerts?grouped=true&status=",
                               headers=h(world, "op.a")).json()
    assert {g["plate"] for g in body["groups"]} == {PLATE}
    with world["state"].store.engine.connect() as c:
        other = c.execute(select(S.alerts.c.alert_id)
                          .where(S.alerts.c.plate == PLATE_B)).scalar()
    r = world["client"].post("/alerts/transition", headers=h(world, "op.a"),
                             json={"alert_ids": [other], "action": "acknowledge"})
    assert r.status_code == 403
    r = world["client"].post(f"/alerts/{other}/acknowledge", headers=h(world, "op.a"))
    assert r.status_code == 403, "the single-alert route must check scope too"


def test_resolve_without_disposition_is_refused(world):
    body = world["client"].get("/alerts?grouped=true", headers=h(world, "sup.1")).json()
    g = next(x for x in body["groups"] if x["plate"] == PLATE)
    r = world["client"].post("/alerts/transition", headers=h(world, "sup.1"),
                             json={"alert_ids": g["alert_ids"], "action": "resolve",
                                   "reason": "looked at it"})
    assert r.status_code == 400
    assert "disposition" in r.json()["detail"]["message"]


def test_group_lifecycle_over_http_is_recorded(world):
    c = world["client"]
    body = c.get("/alerts?grouped=true&status=OPEN", headers=h(world, "sup.1")).json()
    g = next(x for x in body["groups"] if x["plate"] == PLATE)
    r = c.post("/alerts/transition", headers=h(world, "op.a"),
               json={"alert_ids": g["alert_ids"], "action": "acknowledge",
                     "group_id": g["group_id"]})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["changed"]) == sorted(g["alert_ids"])
    r = c.post("/alerts/transition", headers=h(world, "sup.1"),
               json={"alert_ids": g["alert_ids"], "action": "resolve",
                     "disposition": "confirmed", "reason": "vehicle intercepted"})
    assert r.status_code == 200
    body = c.get("/alerts?grouped=true&status=RESOLVED", headers=h(world, "sup.1")).json()
    [done] = body["groups"]
    assert done["plate"] == PLATE and done["statuses"] == {"CLEARED": 4}
    last = done["lifecycle"][-1]
    assert last["by"] == "sup.1" and last["disposition"] == "confirmed"
    assert body["status_counts"]["RESOLVED"] == 4
    # A second acknowledge of a resolved alert is a conflict, not a silent reopen.
    r = c.post(f"/alerts/{g['alert_ids'][0]}/acknowledge", headers=h(world, "sup.1"))
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# The evidence still
# --------------------------------------------------------------------------- #
def test_supervisor_gets_the_vehicle_crop_with_its_digest(world):
    eid = world["evidence"][3]
    r = world["client"].get(f"/evidence/{eid}/frame.jpg?crop=vehicle",
                            headers=h(world, "sup.1"))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["X-Frame-Verified"] == "true"
    assert r.headers["X-Crop"] == "vehicle"
    from io import BytesIO

    from PIL import Image
    im = Image.open(BytesIO(r.content))
    assert im.width < 320, "cropped to the vehicle, not the whole scene"


def test_operator_sees_an_alert_crop_but_not_the_whole_scene(world):
    eid = world["evidence"][2]
    ok = world["client"].get(f"/evidence/{eid}/frame.jpg?crop=vehicle",
                             headers=h(world, "op.a"))
    assert ok.status_code == 200
    full = world["client"].get(f"/evidence/{eid}/frame.jpg?crop=full",
                               headers=h(world, "op.a"))
    assert full.status_code == 403


def test_operator_cannot_read_evidence_that_is_not_on_an_alert(world):
    r = world["client"].get(f"/evidence/{world['unrelated']}/frame.jpg",
                            headers=h(world, "op.a"))
    assert r.status_code == 403


def test_auditor_cannot_see_the_picture(world):
    r = world["client"].get(f"/evidence/{world['evidence'][1]}/frame.jpg",
                            headers=h(world, "audit.1"))
    assert r.status_code == 403


def test_plate_crop_is_refused_honestly(world):
    r = world["client"].get(f"/evidence/{world['evidence'][1]}/frame.jpg?crop=plate",
                            headers=h(world, "sup.1"))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PLATE_BOX_NOT_STORED"


def test_frame_view_is_audited(world):
    eid = world["evidence"][0]
    world["client"].get(f"/evidence/{eid}/frame.jpg", headers=h(world, "sup.1"))
    with world["state"].store.engine.connect() as c:
        hits = c.execute(select(S.audit_log.c.actor).where(
            S.audit_log.c.action == "evidence_frame_view")
            .where(S.audit_log.c.target == eid)).all()
    assert hits and hits[-1].actor == "sup.1"


def test_a_tampered_frame_is_refused_not_shown(world, tmp_path):
    from pathlib import Path
    m = world["state"].evidence.load(world["evidence"][0])
    p = Path(m.frame_path)
    original = p.read_bytes()
    try:
        p.write_bytes(original[:-16] + b"\x00" * 16)
        r = world["client"].get(f"/evidence/{m.evidence_id}/frame.jpg",
                                headers=h(world, "sup.1"))
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "FRAME_DIGEST_MISMATCH"
    finally:
        p.write_bytes(original)
