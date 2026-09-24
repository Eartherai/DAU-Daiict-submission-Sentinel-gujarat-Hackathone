"""Negative security tests for the HTTP surface.

Written adversarially: every test here tries to get data it is not entitled to,
and passes only when it is refused for the *right reason*. A 500 is not a pass —
an endpoint that crashes on a malformed id has not enforced anything, it has
merely failed differently.

Coverage follows the OWASP API list that actually applies to this system:
broken authentication, broken object-level authorisation, broken function-level
authorisation, injection, path traversal, and unrestricted resource consumption.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.security import Role, TokenService
from tests.conftest import make_observation

DISTRICT_A = "Ahmedabad"
DISTRICT_B = "Gandhinagar"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("apisec")
    state = AppState(f"sqlite:///{tmp / 'api.db'}", evidence_root=tmp / "evidence")
    state.require_auth = True
    store = state.store

    # Two districts, so cross-jurisdiction access has something to fail against.
    store.upsert_camera({"camera_id": "CAM-001", "name": "A-1",
                         "district": DISTRICT_A, "department": "Home (Traffic)",
                         "lat": 23.03, "lon": 72.58, "tier": "A", "enabled": True})
    store.upsert_camera({"camera_id": "CAM-002", "name": "B-1",
                         "district": DISTRICT_B, "department": "Municipal",
                         "lat": 23.21, "lon": 72.63, "tier": "B", "enabled": True})
    store.add_observations([
        make_observation("CAM-001", plate="GJ01AA1111", offset_s=0,
                         district=DISTRICT_A),
        make_observation("CAM-002", plate="GJ02BB2222", offset_s=60,
                         district=DISTRICT_B, track="T2"),
    ])

    ts = TokenService(store)
    # A statewide supervisor: the only role that both searches and reads the
    # audit log, and therefore the one that can check that searching is audited.
    ts.upsert_user("sup.1", Role.SUPERVISOR)
    ts.upsert_user("inv.a", Role.INVESTIGATOR, districts=(DISTRICT_A,))
    ts.upsert_user("inv.b", Role.INVESTIGATOR, districts=(DISTRICT_B,))
    ts.upsert_user("op.1", Role.OPERATOR, districts=(DISTRICT_A,))
    ts.upsert_user("admin.1", Role.ADMIN)
    ts.upsert_user("audit.1", Role.AUDITOR)
    ts.upsert_user("edge.1", Role.SERVICE)

    tokens = {u: ts.mint(u) for u in
              ("sup.1", "inv.a", "inv.b", "op.1", "admin.1", "audit.1", "edge.1")}
    state.investigation.refresh()
    client = TestClient(create_app(state), raise_server_exceptions=False)
    return {"client": client, "tokens": tokens, "state": state}


def hdr(world, user, *, case="FIR-1/2026", purpose="stolen vehicle enquiry"):
    h = {"Authorization": f"Bearer {world['tokens'][user]}"}
    if case:
        h["X-Case-Id"] = case
    if purpose:
        h["X-Purpose"] = purpose
    return h


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
def test_no_token_is_rejected(world):
    r = world["client"].get("/search?plate=GJ01AA1111")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.parametrize("value", [
    "", "Bearer", "Bearer ", "Basic abc", "Bearer skv_notarealtoken",
    "Bearer " + "A" * 5000,
])
def test_malformed_authorisation_headers(world, value):
    r = world["client"].get("/search?plate=GJ01AA1111",
                            headers={"Authorization": value})
    assert r.status_code == 401, f"{value[:24]!r} was not rejected"


def test_revoked_token_stops_working(world, tmp_path):
    ts = TokenService(world["state"].store)
    ts.upsert_user("temp.1", Role.INVESTIGATOR, districts=(DISTRICT_A,))
    token = ts.mint("temp.1")
    h = {"Authorization": f"Bearer {token}", "X-Case-Id": "FIR-9",
         "X-Purpose": "temporary access test"}
    assert world["client"].get("/search?plate=GJ01AA1111", headers=h).status_code == 200
    with world["state"].store.engine.connect() as c:
        from sqlalchemy import select

        from saakshya.store import schema as S
        tid = c.execute(select(S.api_tokens.c.token_id)
                        .where(S.api_tokens.c.user_id == "temp.1")).scalar()
    ts.revoke(tid)
    assert world["client"].get("/search?plate=GJ01AA1111", headers=h).status_code == 401


# --------------------------------------------------------------------------- #
# Purpose binding
# --------------------------------------------------------------------------- #
def test_search_without_case_id_is_refused(world):
    r = world["client"].get("/search?plate=GJ01AA1111",
                            headers={"Authorization": f"Bearer {world['tokens']['inv.a']}"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PURPOSE_REQUIRED"


def test_search_with_trivial_purpose_is_refused(world):
    r = world["client"].get("/search?plate=GJ01AA1111",
                            headers=hdr(world, "inv.a", purpose="x"))
    assert r.status_code == 400
    assert "purpose" in r.json()["detail"]["message"].lower()


def test_purpose_reaches_the_audit_log(world):
    purpose = "purpose binding end to end check"
    world["client"].get("/search?plate=GJ01AA1111",
                        headers=hdr(world, "inv.a", case="FIR-AUDIT",
                                    purpose=purpose))
    r = world["client"].get("/audit?case_id=FIR-AUDIT",
                            headers=hdr(world, "audit.1"))
    assert r.status_code == 200
    body = r.json()
    assert body["chain_verified"], body["chain_error"]
    assert any(e["purpose"] == purpose for e in body["entries"]), \
        "the stated purpose was not recorded"


def test_watchlist_read_is_purpose_bound(world):
    r = world["client"].get(
        "/watchlist", headers={"Authorization": f"Bearer {world['tokens']['inv.a']}"})
    assert r.status_code == 400, "watchlist read must require a purpose"


# --------------------------------------------------------------------------- #
# Object-level authorisation
# --------------------------------------------------------------------------- #
def test_district_officer_cannot_see_another_district(world):
    r = world["client"].get(f"/search?plate=GJ02BB2222&district={DISTRICT_B}",
                            headers=hdr(world, "inv.a"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "OUT_OF_JURISDICTION"


def test_out_of_scope_results_are_filtered_not_leaked(world):
    """Searching a plate that only exists in another district returns nothing —
    and says which cameras it searched, so the officer knows it was scoped."""
    r = world["client"].get("/search?plate=GJ02BB2222", headers=hdr(world, "inv.a"))
    assert r.status_code == 200
    body = r.json()
    assert body["result_count"] == 0
    assert "CAM-002" not in body["search_strategy"]["cameras_searched"]
    assert any(e["reason"] == "OUTSIDE_JURISDICTION"
               for e in body["search_strategy"]["cameras_excluded"])


def test_camera_context_is_scope_checked(world):
    r = world["client"].get("/cameras/CAM-002", headers=hdr(world, "inv.a"))
    assert r.status_code == 403


def test_explicit_camera_outside_scope_is_refused(world):
    r = world["client"].get("/search?plate=GJ01AA1111&camera=CAM-002",
                            headers=hdr(world, "inv.a"))
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Function-level authorisation
# --------------------------------------------------------------------------- #
def test_operator_cannot_search_vehicles(world):
    r = world["client"].get("/search?plate=GJ01AA1111", headers=hdr(world, "op.1"))
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_admin_cannot_search_vehicles(world):
    """Separation of duty: running the estate is not investigating people."""
    r = world["client"].get("/search?plate=GJ01AA1111", headers=hdr(world, "admin.1"))
    assert r.status_code == 403


def test_auditor_cannot_read_evidence(world):
    r = world["client"].get("/evidence/chain/verify", headers=hdr(world, "audit.1"))
    assert r.status_code == 403


def test_investigator_cannot_read_the_audit_log(world):
    r = world["client"].get("/audit", headers=hdr(world, "inv.a"))
    assert r.status_code == 403


def test_edge_service_token_cannot_search(world):
    r = world["client"].get("/search?plate=GJ01AA1111", headers=hdr(world, "edge.1"))
    assert r.status_code == 403


def test_investigator_cannot_post_edge_events(world):
    r = world["client"].post("/edge/node-x/events", json={"events": []},
                             headers=hdr(world, "inv.a"))
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Injection, traversal, malformed input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("evil", [
    "GJ01AA1111'; DROP TABLE observations;--",
    "' OR '1'='1",
    "%27%20OR%201=1--",
    "GJ01AA1111\x00",
    "../../etc/passwd",
    "<script>alert(1)</script>",
    "{{7*7}}",
])
def test_injection_payloads_are_inert(world, evil):
    r = world["client"].get("/search", params={"plate": evil},
                            headers=hdr(world, "inv.a"))
    assert r.status_code in (200, 400, 422), f"unexpected {r.status_code}"
    # The table must still be there afterwards.
    assert world["state"].store.stats()["observations"] >= 2


@pytest.mark.parametrize("path", [
    "/evidence/..%2F..%2Fetc%2Fpasswd/frame",
    "/evidence/../../../etc/passwd/frame",
    "/observations/..%2F..%2Fvar%2Fsaakshya.db",
])
def test_path_traversal_is_refused(world, path):
    r = world["client"].get(path, headers=hdr(world, "inv.a"))
    assert r.status_code in (400, 404, 422), f"{path} returned {r.status_code}"
    assert b"root:" not in r.content


def test_unfiltered_search_is_refused(world):
    r = world["client"].get("/search", headers=hdr(world, "inv.a"))
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "QUERY_TOO_BROAD"


@pytest.mark.parametrize("params,expect", [
    ("limit=100000", 422),
    ("plate=X&t_from=notatime", 400),
    ("plate=X&t_from=2026-09-01T00:00:00", 400),   # naive: no offset
    ("plate=X&t_from=2020-01-01T00:00:00Z&t_to=2026-01-01T00:00:00Z", 400),
    ("plate=X&t_to=2020-01-01T00:00:00Z&t_from=2026-01-01T00:00:00Z", 400),
])
def test_bad_query_parameters(world, params, expect):
    r = world["client"].get(f"/search?{params}", headers=hdr(world, "inv.a"))
    assert r.status_code == expect, r.text


def test_bad_bbox_is_rejected(world):
    for bad in ("1,2,3", "a,b,c,d", "0,100,0,100", "0,80,0,10"):
        r = world["client"].get(f"/gis/cameras?bbox={bad}", headers=hdr(world, "inv.a"))
        assert r.status_code == 400, f"bbox {bad!r} was accepted"


def test_nearby_cameras_stay_inside_the_officers_districts(world):
    # 30 km around CAM-001 reaches CAM-002 (about 20 km off, another district).
    q = "/gis/near?lat=23.03&lon=72.58&radius_m=30000"
    sup = world["client"].get(q, headers=hdr(world, "sup.1")).json()
    assert {c["camera_id"] for c in sup["cameras"]} == {"CAM-001", "CAM-002"}
    a = world["client"].get(q, headers=hdr(world, "inv.a")).json()
    assert [c["camera_id"] for c in a["cameras"]] == ["CAM-001"]
    for bad in ("lat=91&lon=72&radius_m=10", "lat=23&lon=72&radius_m=900000"):
        assert world["client"].get(f"/gis/near?{bad}",
                                   headers=hdr(world, "inv.a")).status_code == 422


def test_unknown_ids_return_404_not_500(world):
    for path in ("/observations/OB-nope", "/cameras/NOPE-999",
                 "/evidence/EV-nope", "/cases/NOPE"):
        r = world["client"].get(path, headers=hdr(world, "inv.a"))
        assert r.status_code in (403, 404), f"{path} returned {r.status_code}"


def test_case_id_pattern_is_enforced(world):
    r = world["client"].post("/cases", headers=hdr(world, "inv.a"), json={
        "case_id": "../../etc", "title": "traversal attempt",
        "purpose": "checking identifier validation"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Responses must not leak
# --------------------------------------------------------------------------- #
def test_errors_do_not_echo_input(world):
    r = world["client"].post("/cases", headers=hdr(world, "inv.a"), json={
        "case_id": "OK-1", "title": "x", "purpose": "SENSITIVE-CANARY-VALUE"})
    assert r.status_code == 422
    assert "SENSITIVE-CANARY-VALUE" not in r.text


def test_stream_urls_are_not_exposed_to_investigators(world):
    world["state"].store.upsert_camera({
        "camera_id": "CAM-001", "name": "A-1", "district": DISTRICT_A,
        "lat": 23.03, "lon": 72.58,
        "rtsp_url": "rtsp://user:secret@10.0.0.1:8554/stream/1"})
    r = world["client"].get("/cameras/CAM-001", headers=hdr(world, "inv.a"))
    assert r.status_code == 200
    assert "secret" not in r.text and "rtsp://" not in r.text


def test_security_headers_are_present(world):
    r = world["client"].get("/healthz")
    for header in ("Content-Security-Policy", "X-Content-Type-Options",
                   "X-Frame-Options", "Referrer-Policy"):
        assert header in r.headers, f"missing {header}"
    assert "X-Request-Id" in r.headers


def test_request_id_is_echoed(world):
    r = world["client"].get("/healthz", headers={"X-Request-Id": "abc123"})
    assert r.headers["X-Request-Id"] == "abc123"


def test_openapi_documents_every_route(world):
    spec = world["client"].get("/openapi.json").json()
    assert spec["info"]["title"].startswith("SAAKSHYA")
    assert len(spec["paths"]) >= 30
    assert json.dumps(spec).count("purpose") > 0


# --------------------------------------------------------------------------- #
# Positive control.
#
# Every test above asserts that something is refused. Without this, a system
# that refused *everything* — or returned nothing at all — would pass the whole
# file. This is the test that makes the others mean something.
# --------------------------------------------------------------------------- #
def test_the_permitted_path_actually_works(world):
    r = world["client"].get("/search?plate=GJ01AA1111", headers=hdr(world, "inv.a"))
    assert r.status_code == 200
    body = r.json()
    assert body["result_count"] == 1, "the authorised search returned nothing"
    c = body["candidates"][0]
    assert c["camera_id"] == "CAM-001"
    assert c["status"] == "CONFIRMED_BY_PLATE"
    assert c["why"]["terms"], "no score decomposition was returned"
    assert body["search_strategy"]["cameras_searched"] == ["CAM-001"]

    other = world["client"].get("/search?plate=GJ02BB2222", headers=hdr(world, "inv.b"))
    assert other.status_code == 200
    assert other.json()["result_count"] == 1, \
        "the other district's officer cannot see their own data"


def test_every_search_audit_record_names_the_role(world):
    """An audit row saying "someone searched" without saying under what
    authority is weaker evidence than one that does.

    Regression: `search_plate` audited without a role while `trajectory_build`
    audited with one, so the audit view showed a dash in the ROLE column for
    precisely the queries that matter most to an oversight body.
    """
    c = world["client"]
    c.get("/search?plate=GJ01AA1111", headers=hdr(world, "sup.1"))
    c.get("/trajectory/GJ01AA1111", headers=hdr(world, "sup.1"))

    entries = c.get("/audit?limit=100", headers=hdr(world, "sup.1")).json()["entries"]
    searches = [e for e in entries
                if e["action"] in ("search_plate", "search_gap_candidates",
                                   "trajectory_build")]
    assert searches, "no search was audited at all"
    for e in searches:
        assert e["role"], f"{e['action']} was audited without a role"


# --------------------------------------------------------------------------- #
# Administration (§43) — small, read-only, and not a side door
# --------------------------------------------------------------------------- #
def test_admin_endpoints_refuse_investigators(world):
    """An investigator must not reach the registry's stream URLs through the
    admin router, and must not read the user list."""
    c = world["client"]
    for path in ("/admin/users", "/admin/roles", "/admin/cameras", "/admin/policy"):
        r = c.get(path, headers=hdr(world, "inv.a"))
        assert r.status_code == 403, f"{path} was reachable by an investigator"


def test_admin_user_list_never_returns_token_material(world):
    """Not a token, not a prefix, not a hint. The only place a token exists in
    readable form is the terminal that minted it."""
    r = world["client"].get("/admin/users", headers=hdr(world, "admin.1"))
    assert r.status_code == 200

    # The user records themselves, not the response prose: the explanatory note
    # legitimately contains the word "token" while carrying no token material.
    for u in r.json()["users"]:
        for key in u:
            assert not any(bad in key.lower()
                           for bad in ("token", "sha", "secret", "digest", "hash")), (
                f"user record exposes field {key!r}")

    # And nothing anywhere in the response that looks like a credential.
    body = r.text
    assert "skv_" not in body, "a bearer token appears in the response"
    assert not re.search(r"\b[0-9a-f]{40,}\b", body), (
        "something hash-shaped appears in the response")


def test_separation_of_duty_is_published_and_true(world):
    """The role table is served as data so it can be checked rather than
    trusted. Both flags must be false."""
    r = world["client"].get("/admin/roles", headers=hdr(world, "admin.1"))
    sod = r.json()["separation_of_duty"]
    assert sod["admin_may_search"] is False
    assert sod["auditor_may_read_evidence"] is False


def test_policy_endpoint_states_that_the_score_is_not_a_probability(world):
    """Thresholds an operator cannot read are thresholds nobody can dispute."""
    r = world["client"].get("/admin/policy", headers=hdr(world, "admin.1"))
    assert r.status_code == 200
    body = r.json()
    assert body["trajectory"]["score_is_probability"] is False
    assert body["capability_grading"]["version"]
    assert "search:plate" in body["purpose_bound_operations"]


def test_no_endpoint_mints_a_credential(world):
    """Minting a token over HTTP would make a credential factory reachable from
    the network. It is a host-side CLI on purpose."""
    paths = [r.path for r in world["client"].app.routes if hasattr(r, "path")]
    for p in paths:
        assert "token" not in p.lower(), f"{p} looks like a credential endpoint"


def test_a_case_id_containing_a_slash_is_addressable(world):
    """An Indian FIR number is NNN/YYYY, so a case identifier containing a slash
    is the normal case, not an exotic input.

    Regression: every case route took `{case_id}`, which stops at a slash. The
    case could be created and listed but never opened, attached to, annotated or
    exported — a 404 on the identifier the system had just issued. Found by
    clicking a case in the interface, not by a test.
    """
    c, h = world["client"], hdr(world, "sup.1")
    case_id = "FIR-777/2026"

    created = c.post("/cases", headers=h, json={
        "case_id": case_id, "title": "Slash in the identifier",
        "purpose": "verifying that an ordinary FIR number is addressable"})
    assert created.status_code in (201, 409)

    got = c.get(f"/cases/{case_id}", headers=h)
    assert got.status_code == 200, f"case {case_id} is unreachable: {got.text[:200]}"
    assert got.json()["case"]["case_id"] == case_id

    attached = c.post(f"/cases/{case_id}/items", headers=h, json={
        "item_type": "target", "item_ref": "GJ01AA1111"})
    assert attached.status_code == 200, attached.text[:200]

    noted = c.post(f"/cases/{case_id}/notes", headers=h,
                   json={"body": "a note on a slash-bearing case"})
    assert noted.status_code == 200, noted.text[:200]

    exported = c.get(f"/cases/{case_id}/export", headers=h)
    assert exported.status_code == 200, exported.text[:200]
    body = exported.json()
    assert body["case"]["case_id"] == case_id
    assert any(i["item_ref"] == "GJ01AA1111" for i in body["items"])
    assert body["notes"], "the note did not reach the export"


def test_case_routes_do_not_shadow_one_another(world):
    """A `path` converter is greedy, so the suffixed routes must be declared
    before the bare one. If they are not, `/cases/X/export` is read as a case
    named "X/export" and silently 404s instead of exporting."""
    c, h = world["client"], hdr(world, "sup.1")
    c.post("/cases", headers=h, json={
        "case_id": "FIR-888/2026", "title": "Route ordering",
        "purpose": "verifying that suffixed case routes still match"})
    r = c.get("/cases/FIR-888/2026/export", headers=h)
    assert r.status_code == 200
    assert r.json()["case"]["case_id"] == "FIR-888/2026"
