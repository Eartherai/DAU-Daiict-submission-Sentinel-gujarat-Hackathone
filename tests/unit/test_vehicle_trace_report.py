"""The printable vehicle trace report.

An officer asked for "the route of this vehicle" gets a page to print and
sign. These tests pin what makes it fit for a case diary rather than a
screenshot: the reads come from the store and nowhere else, the caller's
jurisdiction bounds them, an impossible leg is flagged rather than drawn as a
route, the page runs no script, the same store gives the same digest, a still
that no longer matches its seal is withheld, and the whole thing is gated and
audited as the plate search it is.

All plates here are synthetic fixtures.
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.reports.vehicle_trace import _still, legs
from saakshya.security import Role, TokenService
from tests.conftest import make_observation

A, B = "Ahmedabad", "Gandhinagar"
PLATE = "GJ01TR0001"
HOSTILE = '<img src=x onerror="alert(1)">'
PURPOSE = {"X-Case-Id": "CASE-TR-1", "X-Purpose": "trace for FIR 12/2026 theft enquiry"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("trace")
    state = AppState(f"sqlite:///{tmp / 't.db'}", evidence_root=tmp / "ev")
    state.require_auth = True
    s = state.store
    for cid, name, d, lat, lon in (("CAM-A", "Paldi crossing", A, 23.0100, 72.5600),
                                   ("CAM-A2", HOSTILE, A, 23.0300, 72.5700),
                                   ("CAM-B", "Infocity gate", B, 23.1900, 72.6300)):
        s.upsert_camera({"camera_id": cid, "name": name, "district": d,
                         "department": "Home (Traffic)", "lat": lat, "lon": lon,
                         "tier": "A", "enabled": True})
    s.add_observations([
        make_observation("CAM-A", plate=PLATE, offset_s=0, district=A, track="T1"),
        # ~2.4 km in ten minutes: a drive.
        make_observation("CAM-A2", plate=PLATE, offset_s=600, district=A, track="T2"),
        # ~18 km in one minute: not a drive.
        make_observation("CAM-B", plate=PLATE, offset_s=660, district=B, track="T3"),
    ])
    ts = TokenService(s)
    ts.upsert_user("sup.1", Role.SUPERVISOR)
    ts.upsert_user("inv.a", Role.INVESTIGATOR, districts=(A,))
    ts.upsert_user("admin.1", Role.ADMIN)
    tokens = {u: ts.mint(u) for u in ("sup.1", "inv.a", "admin.1")}
    state.investigation.refresh()
    return {"client": TestClient(create_app(state), raise_server_exceptions=False),
            "tokens": tokens, "state": state}


def get(world, user, plate=PLATE, **headers):
    return world["client"].get(f"/reports/vehicle/{plate}.html", headers={
        "Authorization": f"Bearer {world['tokens'][user]}", **headers})


def test_supervisor_gets_every_read_and_the_impossible_leg_flagged(world):
    r = get(world, "sup.1", **PURPOSE)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert body.count("<tr><td>") >= 3 + 2          # three reads, two legs
    assert "Paldi crossing" in body and "Infocity gate" in body
    assert "possible misread or cloned plate" in body
    assert body.count("plausible</span>") == 1       # the ten-minute leg only
    assert "CASE-TR-1" in body and "theft enquiry" in body
    assert r.headers["X-Report-Id"].startswith(f"TR-{PLATE}-")


def test_page_runs_no_script_and_escapes_what_the_store_holds(world):
    body = get(world, "sup.1", **PURPOSE).text
    assert "<script" not in body.lower()
    assert HOSTILE not in body
    assert "&lt;img src=x" in body


def test_same_store_same_digest(world):
    a = get(world, "sup.1", **PURPOSE).headers["X-Report-Digest"]
    b = get(world, "sup.1", **PURPOSE).headers["X-Report-Digest"]
    assert a == b and len(a) == 64


def test_district_officer_sees_only_their_district(world):
    r = get(world, "inv.a", **PURPOSE)
    assert r.status_code == 200, r.text[:300]
    assert "Infocity gate" not in r.text and "CAM-B" not in r.text
    assert "Paldi crossing" in r.text
    # Two reads in scope means one leg, and a different digest from statewide.
    assert r.headers["X-Report-Digest"] != get(world, "sup.1", **PURPOSE).headers["X-Report-Digest"]


def test_needs_a_case_and_a_purpose(world):
    r = get(world, "sup.1")
    assert r.status_code in (400, 403, 428)
    assert r.json()["detail"]["code"] == "PURPOSE_REQUIRED"
    assert PLATE not in r.text or "purpose" in r.text.lower()


def test_role_without_plate_search_is_refused_and_sees_nothing(world):
    r = get(world, "admin.1", **PURPOSE)
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "PERMISSION_DENIED" and d["permission"] == "search:plate"
    assert "Paldi crossing" not in r.text


def test_generation_is_audited(world):
    get(world, "sup.1", **PURPOSE)
    r = world["client"].get("/audit?limit=500&action=vehicle_trace_report", headers={
        "Authorization": f"Bearer {world['tokens']['sup.1']}"})
    assert r.status_code == 200
    rows = [e for e in r.json()["entries"] if e["action"] == "vehicle_trace_report"]
    assert rows and rows[0]["target"] == PLATE
    assert rows[0]["purpose"] == PURPOSE["X-Purpose"]


def test_unseen_plate_is_an_answer_not_an_error(world):
    r = get(world, "sup.1", plate="GJ01ZZ9999", **PURPOSE)
    assert r.status_code == 200
    assert "No read of" in r.text


def test_repeated_reads_at_one_camera_are_a_stop_not_a_leg():
    cams = {"X": {"lat": 23.0, "lon": 72.5}, "Y": {"lat": 23.1, "lon": 72.5}}
    row = lambda cam, t: {"camera_id": cam, "timestamp_utc": t, "timestamp_ist": t}
    g = legs([row("X", "2026-09-01T10:00:00+00:00"), row("X", "2026-09-01T10:01:00+00:00"),
              row("Y", "2026-09-01T10:21:00+00:00")], cams)
    assert len(g) == 1 and g[0]["from"] == "X" and g[0]["to"] == "Y"
    assert g[0]["flag"] is None and 30 < g[0]["kmh"] < 40      # ~11 km in 20 min


def test_a_still_that_no_longer_matches_its_seal_is_withheld(tmp_path):
    from PIL import Image
    p = tmp_path / "EV1.png"
    Image.new("RGB", (64, 40), (90, 90, 90)).save(p)
    sealed = hashlib.sha256(p.read_bytes()).hexdigest()
    m = SimpleNamespace(frame_path=str(p), frame_sha256=sealed, entry_hash="h")
    state = SimpleNamespace(evidence=SimpleNamespace(load=lambda _: m, root=tmp_path))
    ok = _still(state, "EV1")
    assert ok["status"] == "verified" and ok["uri"].startswith("data:image/jpeg;base64,")
    Image.new("RGB", (64, 40), (200, 10, 10)).save(p)          # the file is changed
    bad = _still(state, "EV1")
    assert "uri" not in bad and "withheld" in bad["status"]


def test_a_purpose_in_gujarati_reaches_the_audit_log_as_written(world):
    """Header values are ISO-8859-1; the browser refused a purpose with an em
    dash before it was sent. The UI now percent-encodes and flags it."""
    from urllib.parse import quote
    purpose = "ચોરાયેલ વાહનની તપાસ — FIR 12/2026"
    r = get(world, "sup.1", **{"X-Case-Id": "CASE-GU-1", "X-Purpose": quote(purpose),
                               "X-Purpose-Encoding": "uri"})
    assert r.status_code == 200, r.text[:300]
    assert purpose in r.text                                  # printed on the report
    a = world["client"].get("/audit?limit=500&action=vehicle_trace_report", headers={
        "Authorization": f"Bearer {world['tokens']['sup.1']}"}).json()["entries"]
    assert any(e.get("purpose") == purpose and e.get("case_id") == "CASE-GU-1" for e in a)



def test_a_lead_with_no_still_is_not_told_to_check_the_still():
    """'Verify on the still' was printed beside reads with no still sealed."""
    from saakshya.reports.vehicle_trace import render_html
    row = {"plate": "GJ01TR0001", "timestamp_utc": "2026-09-01T08:00:00+00:00",
           "timestamp_ist": "2026-09-01T13:30:00+05:30", "camera_id": "CAM-A",
           "camera_name": "Paldi crossing", "district": "Ahmedabad", "confidence": "0.910",
           "votes": 1, "confirmed": "no", "plate_format_valid": "yes",
           "plate_format_note": "", "observation_id": "OB1", "evidence_id": "EV1"}
    t = {"plate": "GJ01TR0001", "rows": [row], "cameras": {}, "legs": [],
         "stills": {"EV1": {"status": "no frame sealed"}}, "watchlist": {"checked": False},
         "confirmed": 0, "leads": 1, "flagged_legs": 0,
         "generated_ist": "2026-09-24T10:00:00+05:30", "user": "u", "role": "SUPERVISOR",
         "purpose": "p", "case_id": "c", "jurisdiction": "statewide",
         "digest": "0" * 64, "report_id": "TR-X"}
    body = render_html(t)
    assert "no still retained; corroborate at the source" in body
    assert "lead — verify on the still" not in body
    t["stills"]["EV1"] = {"status": "verified", "uri": "data:image/jpeg;base64,AA", "sha256": "a" * 64}
    assert "lead — verify on the still" in render_html(t)
