"""Registration marks may leave the system only through the search's own gate.

Officers found that an ADMIN or AUDITOR, refused at /search?plate=, could read
every plate with camera, district and time from the Overview strip, the ANPR
report, the Intelligence view's recent reads and the jump payload — and that
none of those reads was audited. These tests try each of those side doors with
each role, and pass only when the door is shut for the right reason (a
PERMISSION_DENIED naming search:plate), open for the roles that hold it, scoped
to jurisdiction, and recorded in the hash-chained audit log.

They also pin the two neighbouring findings: the registry CSV export must not
hand stream URLs to roles without admin:write or ignore jurisdiction, and
registry writes and refusals must appear in the audit log.

All plates here are synthetic fixtures; none is on a watchlist.
"""
from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.api.plate_access import redact_tracks
from saakshya.security import AuthContext, Principal, Role, TokenService
from tests.conftest import make_observation

A, B = "Ahmedabad", "Gandhinagar"
PLATE_A, PLATE_B = "GJ01AA1111", "GJ02BB2222"
USERS = ("sup.1", "inv.a", "op.a", "admin.1", "audit.1")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plates")
    state = AppState(f"sqlite:///{tmp / 'p.db'}", evidence_root=tmp / "ev")
    state.require_auth = True
    store = state.store
    store.upsert_camera({"camera_id": "CAM-A", "name": "A-1", "district": A,
                         "department": "Home (Traffic)", "lat": 23.03, "lon": 72.58,
                         "rtsp_url": "rtsp://user:secret@10.0.0.1/a",
                         "tier": "A", "enabled": True})
    store.upsert_camera({"camera_id": "CAM-B", "name": "B-1", "district": B,
                         "department": "Municipal", "lat": 23.21, "lon": 72.63,
                         "rtsp_url": "rtsp://user:secret@10.0.0.2/b",
                         "tier": "B", "enabled": True})
    store.add_observations([
        make_observation("CAM-A", plate=PLATE_A, offset_s=0, district=A),
        make_observation("CAM-B", plate=PLATE_B, offset_s=60, district=B, track="T2"),
    ])
    ts = TokenService(store)
    ts.upsert_user("sup.1", Role.SUPERVISOR)
    ts.upsert_user("inv.a", Role.INVESTIGATOR, districts=(A,))
    ts.upsert_user("op.a", Role.OPERATOR, districts=(A,))
    ts.upsert_user("admin.1", Role.ADMIN)
    ts.upsert_user("audit.1", Role.AUDITOR)
    tokens = {u: ts.mint(u) for u in USERS}
    state.investigation.refresh()
    client = TestClient(create_app(state), raise_server_exceptions=False)
    obs_a = store.search_plate(PLATE_A)[0].observation_id
    return {"client": client, "tokens": tokens, "state": state, "obs_a": obs_a}


def hdr(world, user, **extra):
    return {"Authorization": f"Bearer {world['tokens'][user]}", **extra}


def audit_entries(world, *, actor=None, action=None):
    q = "/audit?limit=1000"
    if actor:
        q += f"&actor={actor}"
    if action:
        q += f"&action={action}"
    r = world["client"].get(q, headers=hdr(world, "sup.1"))
    assert r.status_code == 200
    body = r.json()
    assert body["chain_verified"], body["chain_error"]
    return body["entries"]


# --------------------------------------------------------------------------- #
# ADM-01 — the side doors are shut for roles without search:plate
# --------------------------------------------------------------------------- #
SIDE_DOORS = [
    "/marks",
    "/marks?camera_id=CAM-A",
    "/reports/anpr.csv",
    "/command/plates",
    f"/cameras/CAM-A/plate.jpg?plate={PLATE_A}",
]


@pytest.mark.parametrize("user", ["admin.1", "audit.1", "op.a"])
@pytest.mark.parametrize("path", SIDE_DOORS)
def test_roles_without_search_cannot_list_plates(world, user, path):
    r = world["client"].get(path, headers=hdr(world, user))
    assert r.status_code == 403, (path, user, r.text[:300])
    d = r.json()["detail"]
    assert d["code"] == "PERMISSION_DENIED"
    assert d["permission"] == "search:plate"
    assert PLATE_A not in r.text and PLATE_B not in r.text


@pytest.mark.parametrize("user", ["admin.1", "audit.1"])
def test_overview_carries_no_plates_for_admin_and_auditor(world, user):
    r = world["client"].get("/overview", headers=hdr(world, user))
    assert r.status_code == 200
    obs = r.json()["observations"]
    assert obs["recent_marks"] == [] and obs["recent_plates"] == []
    assert obs["plates_withheld"] is True
    assert PLATE_A not in r.text and PLATE_B not in r.text


@pytest.mark.parametrize("user", ["admin.1", "audit.1"])
def test_overview_says_alerts_are_withheld_not_zero(world, user):
    """'0 open alerts' to a role that cannot see alerts is a false statement."""
    alerts = world["client"].get("/overview", headers=hdr(world, user)).json()["alerts"]
    assert alerts["withheld"] is True
    assert alerts["open"] is None
    s = world["client"].get("/command/summary", headers=hdr(world, user)).json()
    assert s["operational"]["alerts_withheld"] is True
    assert s["operational"]["alerts_open"] is None


def test_operator_still_sees_its_alert_count(world):
    alerts = world["client"].get("/overview", headers=hdr(world, "op.a")).json()["alerts"]
    assert not alerts.get("withheld")
    assert alerts["open"] == 0


@pytest.mark.parametrize("user", ["admin.1", "audit.1", "op.a"])
def test_jump_payload_withholds_the_plate(world, user):
    r = world["client"].get(f"/command/jump/{world['obs_a']}", headers=hdr(world, user))
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["plate"] is None and body["plate_withheld"] is True
    assert body["camera_id"] == "CAM-A"   # the playback jump still works


def test_live_overlay_hides_plate_text_from_admin(world):
    r = world["client"].get("/command/cameras/CAM-A/boxes", headers=hdr(world, "admin.1"))
    assert r.status_code == 200
    body = r.json()
    assert body["boxes"], "the box itself must still be drawn"
    assert all(not b.get("plate") for b in body["boxes"])
    assert body["plates_withheld"] is True


@pytest.mark.parametrize("user", ["op.a", "sup.1"])
def test_live_overlay_keeps_plate_text_for_roles_that_act_on_vehicles(world, user):
    body = world["client"].get("/command/cameras/CAM-A/boxes",
                               headers=hdr(world, user)).json()
    assert any(b.get("plate") == PLATE_A for b in body["boxes"])
    assert not body.get("plates_withheld")


def test_own_feed_track_plate_column_is_blanked_for_admin():
    data = {"frames": [[0.0, [[1, 2, 3, 4, "c", 1, 90, "GJ05ZZ9999", 3]]]],
            "plates_accepted": ["GJ05ZZ9999"]}
    admin = AuthContext(principal=Principal("a", Role.ADMIN))
    out = redact_tracks(admin, data)
    assert out["frames"][0][1][0][7] == "" and out["plates_accepted"] == []
    op = AuthContext(principal=Principal("o", Role.OPERATOR, districts=(A,)))
    kept = {"frames": [[0.0, [[1, 2, 3, 4, "c", 1, 90, "GJ05ZZ9999", 3]]]]}
    assert redact_tracks(op, kept)["frames"][0][1][0][7] == "GJ05ZZ9999"


# --------------------------------------------------------------------------- #
# ADM-01 — open for the roles that hold search:plate, scoped, and audited
# --------------------------------------------------------------------------- #
def test_supervisor_reads_marks_and_the_read_is_audited(world):
    before = len(audit_entries(world, actor="sup.1", action="marks_read"))
    r = world["client"].get("/marks", headers=hdr(world, "sup.1"))
    assert r.status_code == 200
    plates = {m["plate"] for m in r.json()["marks"]}
    assert {PLATE_A, PLATE_B} <= plates
    after = audit_entries(world, actor="sup.1", action="marks_read")
    assert len(after) == before + 1
    assert after[0]["target"] == "ALL" and after[0]["role"] == "SUPERVISOR"
    assert after[0]["result_count"] == len(r.json()["marks"])


def test_anpr_report_is_audited_as_an_export(world):
    r = world["client"].get("/reports/anpr.csv", headers=hdr(
        world, "sup.1", **{"X-Case-Id": "FIR-9/2026",
                           "X-Purpose": "submission output report"}))
    assert r.status_code == 200 and PLATE_A in r.text
    e = audit_entries(world, actor="sup.1", action="anpr_report_export")[0]
    assert e["case_id"] == "FIR-9/2026"
    assert e["purpose"] == "submission output report"


@pytest.mark.parametrize("path", ["/marks", "/reports/anpr.csv", "/command/plates",
                                  "/overview"])
def test_district_investigator_sees_only_own_district_plates(world, path):
    r = world["client"].get(path, headers=hdr(world, "inv.a"))
    assert r.status_code == 200, r.text[:300]
    assert PLATE_A in r.text
    assert PLATE_B not in r.text, f"{path} leaked a plate from outside Ahmedabad"


def test_overview_read_by_supervisor_is_audited(world):
    before = len(audit_entries(world, actor="sup.1", action="marks_read"))
    world["client"].get("/overview", headers=hdr(world, "sup.1"))
    after = audit_entries(world, actor="sup.1", action="marks_read")
    assert len(after) == before + 1 and after[0]["target"] == "overview"


def test_case_items_are_withheld_from_roles_without_search(world):
    c = world["client"]
    sup = hdr(world, "sup.1", **{"X-Case-Id": "FIR-77/2026",
                                 "X-Purpose": "tracing a stolen test vehicle"})
    assert c.post("/cases", headers=sup, json={
        "case_id": "FIR-77/2026", "title": "test", "purpose": "tracing a test vehicle",
        "district": A}).status_code == 201
    assert c.post("/cases/FIR-77/2026/items", headers=sup, json={
        "item_type": "target", "item_ref": PLATE_A}).status_code in (200, 201)
    full = c.get("/cases/FIR-77/2026", headers=sup).json()
    assert full["items"][0]["item_ref"] == PLATE_A
    r = c.get("/cases/FIR-77/2026", headers=hdr(world, "admin.1"))
    assert r.status_code == 200
    assert r.json()["items"][0]["item_ref"] == "withheld"
    assert PLATE_A not in r.text


# --------------------------------------------------------------------------- #
# ADM-03 (refusals) — attempted overreach is recorded, and explained in words
# --------------------------------------------------------------------------- #
def test_every_refused_plate_read_is_in_the_audit_log(world):
    world["client"].get("/marks", headers=hdr(
        world, "admin.1", **{"X-Case-Id": "FIR-77/2026",
                             "X-Purpose": "curious about a vehicle"}))
    e = audit_entries(world, actor="admin.1", action="denied:search:plate")
    assert e, "the refusal left no trace"
    assert e[0]["role"] == "ADMIN" and e[0]["target"] == "/marks"
    assert e[0]["case_id"] == "FIR-77/2026"
    assert e[0]["purpose"] == "curious about a vehicle"
    assert e[0]["result_count"] == 0


def test_refused_search_is_audited(world):
    world["client"].get(f"/search?plate={PLATE_A}", headers=hdr(
        world, "admin.1", **{"X-Case-Id": "FIR-77/2026",
                             "X-Purpose": "curious about a vehicle"}))
    e = audit_entries(world, actor="admin.1", action="denied:search:plate")
    assert any(x["target"] == "/search" for x in e)


def test_out_of_jurisdiction_refusal_is_audited(world):
    r = world["client"].get("/cameras/CAM-B", headers=hdr(world, "inv.a"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "OUT_OF_JURISDICTION"
    e = audit_entries(world, actor="inv.a", action="denied:jurisdiction")
    assert e and "Gandhinagar" in e[0]["target"]


def test_refusal_is_a_sentence_not_a_python_list(world):
    r = world["client"].get("/alerts", headers=hdr(world, "admin.1"))
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["code"] == "PERMISSION_DENIED"       # the machine code is kept
    assert "held:" not in d["message"] and "[" not in d["message"]
    assert d["human"].startswith("Your role (Estate administrator) cannot view alerts.")
    assert "control-room operators" in d["human"] and "supervisors" in d["human"]
    assert d["role_label"] == "Estate administrator"


def test_purpose_missing_is_not_logged_as_overreach(world):
    before = len(audit_entries(world, actor="inv.a"))
    r = world["client"].get(f"/search?plate={PLATE_A}", headers=hdr(world, "inv.a"))
    assert r.json()["detail"]["code"] == "PURPOSE_REQUIRED"
    assert len(audit_entries(world, actor="inv.a")) == before


def test_me_names_the_role_in_words(world):
    p = world["client"].get("/me", headers=hdr(world, "audit.1")).json()["principal"]
    assert p["role_label"] == "Auditor"


# --------------------------------------------------------------------------- #
# ADM-02 — registry export
# --------------------------------------------------------------------------- #
def _csv(text):
    return list(csv.DictReader(io.StringIO(text)))


@pytest.mark.parametrize("user", ["audit.1", "op.a", "inv.a", "sup.1"])
def test_export_withholds_stream_urls_without_admin_write(world, user):
    r = world["client"].get("/registry/cameras/export.csv", headers=hdr(world, user))
    assert r.status_code == 200
    header = r.text.splitlines()[0].split(",")
    for col in ("rtsp_url", "hls_url", "whep_url"):
        assert col not in header
    assert "rtsp://" not in r.text and "secret" not in r.text


def test_admin_export_keeps_stream_urls_for_round_trip(world):
    r = world["client"].get("/registry/cameras/export.csv", headers=hdr(world, "admin.1"))
    rows = _csv(r.text)
    assert {x["camera_id"] for x in rows} >= {"CAM-A", "CAM-B"}
    assert any(x["rtsp_url"].startswith("rtsp://") for x in rows)


def test_export_respects_jurisdiction(world):
    rows = _csv(world["client"].get("/registry/cameras/export.csv",
                                    headers=hdr(world, "op.a")).text)
    assert [x["camera_id"] for x in rows] == ["CAM-A"]


def test_export_is_audited(world):
    world["client"].get("/registry/cameras/export.csv", headers=hdr(world, "audit.1"))
    e = audit_entries(world, actor="audit.1", action="registry_export")
    assert e and e[0]["role"] == "AUDITOR" and "no stream URLs" in e[0]["target"]


# --------------------------------------------------------------------------- #
# ADM-03 — registry writes
# --------------------------------------------------------------------------- #
def test_json_onboarding_is_audited_with_reason(world):
    c = world["client"]
    r = c.post("/registry/cameras/import", headers=hdr(world, "admin.1"), json={
        "cameras": [{"camera_id": "ADM-AUDIT-01", "district": A}],
        "reason": "work order WO-114, new junction camera"})
    assert r.status_code == 200, r.text
    e = audit_entries(world, actor="admin.1", action="registry_import:json")[0]
    assert e["target"] == "ADM-AUDIT-01" and e["role"] == "ADMIN"
    assert e["result_count"] == 1
    assert e["purpose"] == "work order WO-114, new junction camera"


def test_csv_onboarding_and_amend_are_audited(world):
    c = world["client"]
    body = "camera_id,district\nADM-AUDIT-02,Ahmedabad\n"
    h = {**hdr(world, "admin.1"), "Content-Type": "text/csv"}
    assert c.post("/registry/cameras/import.csv", headers=h,
                  content=body).status_code == 200
    assert audit_entries(world, actor="admin.1",
                         action="registry_import:csv")[0]["target"] == "ADM-AUDIT-02"
    assert c.post("/registry/cameras/import.csv?update_existing=true", headers=h,
                  content=body).status_code == 200
    assert audit_entries(world, actor="admin.1",
                         action="registry_amend:csv")[0]["target"] == "ADM-AUDIT-02"


def test_refused_overwrite_is_audited(world):
    c = world["client"]
    r = c.post("/registry/cameras/import", headers=hdr(world, "admin.1"),
               json={"cameras": [{"camera_id": "CAM-A"}]})
    assert r.status_code == 409
    e = audit_entries(world, actor="admin.1",
                      action="registry_import_refused:ALREADY_ONBOARDED")
    assert e and e[0]["target"] == "CAM-A" and e[0]["result_count"] == 0


def test_dry_run_writes_no_audit_entry(world):
    before = len(audit_entries(world, actor="admin.1"))
    world["client"].post("/registry/cameras/import", headers=hdr(world, "admin.1"),
                         json={"cameras": [{"camera_id": "ADM-DRY"}], "dry_run": True})
    assert len(audit_entries(world, actor="admin.1")) == before


def test_non_admin_onboarding_attempt_is_audited(world):
    r = world["client"].post("/registry/cameras/import", headers=hdr(world, "sup.1"),
                             json={"cameras": [{"camera_id": "SUP-TRY"}]})
    assert r.status_code == 403
    e = audit_entries(world, actor="sup.1", action="denied:admin:write")
    assert e and e[0]["target"] == "/registry/cameras/import"


def test_redacting_for_one_role_does_not_blank_the_shared_overlay_cache(world):
    """The overlay rows are cached across callers. An admin poll that blanked
    them in place hid the plates from the next operator on the same camera."""
    c = world["client"]
    c.get("/command/cameras/CAM-A/boxes", headers=hdr(world, "admin.1"))
    body = c.get("/command/cameras/CAM-A/boxes", headers=hdr(world, "op.a")).json()
    assert any(b.get("plate") == PLATE_A for b in body["boxes"])


def test_track_redaction_leaves_the_source_untouched():
    data = {"frames": [[0.0, [[1, 2, 3, 4, "c", 1, 90, "GJ05ZZ9999", 3]]]]}
    redact_tracks(AuthContext(principal=Principal("a", Role.AUDITOR)), data)
    assert data["frames"][0][1][0][7] == "GJ05ZZ9999"
