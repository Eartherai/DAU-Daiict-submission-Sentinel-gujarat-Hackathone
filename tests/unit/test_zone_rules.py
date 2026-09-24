"""Restricted-zone entries: a department's rule, and a measurement against it.

The platform does not call anyone an intruder. A department draws a zone on a
camera's frame and says when it applies; entries are the stored sightings
whose ground position falls inside it in those hours. These tests pin the
geometry, the hours (including a window across midnight), who may write a
rule, who may read its entries, and that both are audited.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from saakshya.analytics.zones import in_hours, inside
from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.store import VehicleObservation
from saakshya.security import Role, TokenService

IST = timezone(timedelta(hours=5, minutes=30))
ZONE = [[100, 500], [900, 500], [900, 1000], [100, 1000]]


def test_the_ground_point_and_the_hours() -> None:
    assert inside(500, 800, ZONE) and not inside(1000, 800, ZONE)
    assert in_hours(datetime(2026, 9, 1, 23, 30, tzinfo=IST), "22:00", "06:00")
    assert in_hours(datetime(2026, 9, 2, 5, 59, tzinfo=IST), "22:00", "06:00")
    assert not in_hours(datetime(2026, 9, 2, 12, 0, tzinfo=IST), "22:00", "06:00")
    assert in_hours(datetime(2026, 9, 2, 12, 0, tzinfo=IST), None, None)


def _person(cam, when, box, key):
    return VehicleObservation(camera_id=cam, pts_s=0.0, t_norm=when, t_ingest=when,
                              dedup_key=key, track_id=key, segment_id="S", object_type="person",
                              bbox=box, detection_confidence=0.9, district="Ahmedabad",
                              model_versions={"dwell_s": 20.0})


def test_rules_are_written_by_admin_read_by_officers_and_audited(tmp_path) -> None:
    state = AppState(f"sqlite:///{tmp_path / 'z.db'}", evidence_root=tmp_path / "ev")
    state.require_auth = True
    s = state.store
    s.upsert_camera({"camera_id": "CAM-Z", "name": "Toll lane", "district": "Ahmedabad",
                     "tier": "A", "enabled": True})
    night = datetime(2026, 9, 1, 23, 10, tzinfo=IST).astimezone(UTC)
    noon = datetime(2026, 9, 2, 12, 0, tzinfo=IST).astimezone(UTC)
    s.add_observations([
        _person("CAM-Z", night, (400.0, 600.0, 460.0, 800.0), "in-night"),     # counted
        _person("CAM-Z", night, (1200.0, 600.0, 1260.0, 800.0), "out-night"),  # outside zone
        _person("CAM-Z", noon, (400.0, 600.0, 460.0, 800.0), "in-noon"),       # outside hours
    ])
    ts = TokenService(s)
    for u, r in (("adm", Role.ADMIN), ("sup", Role.SUPERVISOR), ("aud", Role.AUDITOR)):
        ts.upsert_user(u, r)
    tok = {u: ts.mint(u) for u in ("adm", "sup", "aud")}
    c = TestClient(create_app(state), raise_server_exceptions=False)
    h = lambda u: {"Authorization": f"Bearer {tok[u]}"}  # noqa: E731
    body = {"camera_id": "CAM-Z", "name": "No pedestrians in the toll lane at night",
            "polygon": ZONE, "active_from": "22:00", "active_to": "06:00",
            "classes": ["person"], "reason": "lane closed to pedestrians after dark",
            "authority": "Toll plaza standing order 4/2026"}
    assert c.post("/zones", json=body, headers=h("sup")).status_code == 403
    r = c.post("/zones", json=body, headers=h("adm"))
    assert r.status_code == 201, r.text[:300]
    rule_id = r.json()["rule_id"]
    got = c.get(f"/zones/{rule_id}/entries", headers=h("sup")).json()
    assert got["count"] == 1 and got["entries"][0]["observation_id"]
    assert got["entries"][0]["dwell_s"] == 20.0
    assert c.get(f"/zones/{rule_id}/entries", headers=h("aud")).status_code == 403
    audit = c.get("/audit?limit=100", headers=h("sup")).json()["entries"]
    acts = {e["action"] for e in audit}
    assert {"zone_rule_create", "zone_entries_read"} <= acts
