"""The Step 4 trace, as an officer runs it: plate in, wanted-or-not, route out.

Each test here is a failure an officer met on the running build:

* a plate on the stolen list came back from search looking like any other
  plate, because the watchlist was consulted only as a filter (INV-02);
* a witness fragment, GJ18X67, returned "No observation matched" although
  GJ18X6705 had been read 66 times, because a fragment was compared against the
  oldest 20,000 of a million observations (INV-08);
* sealed evidence frames are PNG and were served as image/jpeg (INV-09).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.intelligence.plate_pattern import (
    PatternError,
    char_diff,
    is_pattern,
    parse_query,
    parse_term,
)
from saakshya.security import Role, TokenService
from saakshya.store import VehicleObservation, to_us
from saakshya.store import schema as S
from saakshya.watchlist.service import Category, Priority, VehicleOfInterest
from tests.conftest import make_observation

# Fictional marks only. Nothing here is a real vehicle, and none is described
# as anything but a test entry.
TARGET = "GJ99QT6705"
OTHER = "GJ99QT6799"
NEAR = "GJ99QT67O5"          # one OCR confusion (0 -> O) from TARGET
UNLISTED = "GJ98ZZ0044"


# --------------------------------------------------------------------------- #
# The query language
# --------------------------------------------------------------------------- #
def test_a_fragment_is_read_as_starts_with_and_says_so():
    t = parse_term("GJ18X67")
    assert t.implicit_prefix
    assert t.text == "GJ18X67*"
    assert t.sql_like() == "GJ18X67%"
    assert t.literal_prefix() == "GJ18X67"
    assert "starts with" in t.describe()
    assert t.match("GJ18X6705") is not None
    assert t.match("GJ18X6805") is None


def test_single_character_unknowns_are_exactly_one_character():
    t = parse_term("GJ01??1234")
    assert t.sql_like() == "GJ01__1234"
    assert t.unknown_positions == 2
    assert "2 unknown positions" in t.describe()
    assert t.match("GJ01AB1234") is not None
    assert t.match("GJ01A1234") is None           # one short
    assert t.match("GJ01ABC1234") is None         # one long


def test_a_run_wildcard_matches_any_length_including_none():
    t = parse_term("GJ*44")
    assert t.sql_like() == "GJ%44"
    for plate in ("GJ03AZ0644", "GJ31144", "GJ44"):
        assert t.match(plate) is not None, plate
    assert t.match("GJ03AZ0645") is None


def test_a_character_set_is_one_of_the_listed_characters():
    t = parse_term("GJ0[18]AB1234")
    assert t.match("GJ01AB1234") and t.match("GJ08AB1234")
    assert t.match("GJ03AB1234") is None
    kinds = [c.kind for c in t.match("GJ08AB1234")]
    assert kinds[3] == "class"


def test_near_matches_use_the_ocr_confusion_table_and_say_which_character():
    t = parse_term("GJ1BX67*")
    assert t.match("GJ18X6705") is None
    chars = t.match("GJ18X6705", near=True)
    assert chars is not None
    assert [c.kind for c in chars][:7] == ["exact"] * 3 + ["confusion"] + ["exact"] * 3
    assert chars[3].ch == "8" and chars[3].query == "B"
    # A confusable literal cannot anchor the index range: G may be a misread 6.
    assert t.literal_prefix(near=True) == ""
    assert t.literal_prefix(near=False) == "GJ1BX67"


def test_comma_lists_are_separate_terms():
    terms = parse_query("GJ18X67, MH12*44 ,gj01??1234")
    assert [t.text for t in terms] == ["GJ18X67*", "MH12*44", "GJ01??1234"]


@pytest.mark.parametrize("bad", ["G*", "GJ", "??", "GJ[", "GJ[#]12", "GJ01%"])
def test_queries_too_loose_or_malformed_are_refused_with_a_reason(bad):
    with pytest.raises(PatternError):
        parse_query(bad)


def test_whole_marks_stay_on_the_exact_path():
    assert not is_pattern("GJ18X6705")
    assert not is_pattern("GJ 01 ZZ 9999")
    assert is_pattern("GJ18X67")
    assert is_pattern("GJ*44")
    assert is_pattern("GJ18X6705,GJ01ZZ9999")


def test_char_diff_marks_confusions_and_plain_differences():
    d = char_diff("GJ18X6705", "GJ18X67O6")
    assert [c.kind for c in d][-2:] == ["confusion", "wild"]


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("trace")
    state = AppState(f"sqlite:///{tmp / 'trace.db'}", evidence_root=tmp / "evidence")
    state.require_auth = True
    store = state.store
    store.upsert_camera({"camera_id": "CAM-A", "name": "Gate A",
                         "district": "Ahmedabad", "department": "Home (Traffic)",
                         "lat": 23.03, "lon": 72.58, "enabled": True})
    store.upsert_camera({"camera_id": "CAM-B", "name": "Gate B",
                         "district": "Gandhinagar", "department": "Municipal",
                         "lat": 23.21, "lon": 72.63, "enabled": True})

    # The regression: more than 20,000 older observations ahead of the
    # target, so a scan of "the first 20,000 rows" never reaches it.
    filler = [VehicleObservation(
        camera_id="CAM-A", pts_s=float(i), t_norm=T0 + timedelta(seconds=i),
        t_ingest=T0 + timedelta(seconds=i), dedup_key=f"fill{i}",
        object_type="car", observation_quality=0.5) for i in range(20_050)]
    store.add_observations(filler)
    late = 30_000
    store.add_observations([
        make_observation("CAM-A", plate=TARGET, offset_s=late + i * 60,
                         track=f"TT{i}", district="Ahmedabad")
        for i in range(5)] + [
        make_observation("CAM-B", plate=TARGET, offset_s=late + 900,
                         track="TB", district="Gandhinagar"),
        make_observation("CAM-A", plate=OTHER, offset_s=late + 10, track="TO",
                         district="Ahmedabad"),
        make_observation("CAM-A", plate=UNLISTED, offset_s=late + 20, track="TU",
                         district="Ahmedabad"),
    ])

    state.investigation.watchlist.add(VehicleOfInterest(
        plate=TARGET, category=Category.STOLEN_VEHICLE, priority=Priority.HIGH,
        authority="test harness", reason="fictional test entry for trace",
        source_system="REPRESENTATIVE"))
    with store.engine.begin() as c:
        for i, (cam, status) in enumerate([("CAM-A", "OPEN"), ("CAM-A", "OPEN"),
                                           ("CAM-B", "OPEN"),
                                           ("CAM-A", "CLEARED")]):
            c.execute(insert(S.alerts).values(
                alert_id=f"AL-T{i}", watchlist_id="WL-T", plate=TARGET,
                camera_id=cam, category="stolen_vehicle", priority="HIGH",
                status=status, t_norm_us=to_us(T0 + timedelta(seconds=late + i)),
                created_at_us=to_us(T0)))

    ts = TokenService(store)
    ts.upsert_user("sup.1", Role.SUPERVISOR)
    ts.upsert_user("inv.a", Role.INVESTIGATOR, districts=("Ahmedabad",))
    tokens = {u: ts.mint(u) for u in ("sup.1", "inv.a")}
    state.investigation.refresh()
    return {"client": TestClient(create_app(state), raise_server_exceptions=False),
            "tokens": tokens, "state": state}


def hdr(world, user="sup.1"):
    return {"Authorization": f"Bearer {world['tokens'][user]}",
            "X-Case-Id": "FIR-T/2026", "X-Purpose": "trace test of a fictional mark"}


def test_search_says_the_plate_is_on_the_watchlist_and_on_whose_word(world):
    r = world["client"].get(f"/search?plate={TARGET}", headers=hdr(world))
    assert r.status_code == 200, r.text
    body = r.json()
    wl = body["watchlist_status"]
    assert wl["checked"] and wl["listed"]
    e = wl["entries"][0]
    assert e["category"] == "stolen_vehicle" and e["priority"] == "HIGH"
    assert e["reason"] == "fictional test entry for trace"
    assert e["source_system"] == "REPRESENTATIVE"
    assert e["added_at"] and e["in_force"]
    assert wl["checked_at"]
    alerts = body["open_alerts"]
    assert alerts["open"] == 3 and alerts["total"] == 4
    assert alerts["latest_alert_id"]


def test_an_unlisted_plate_is_reported_as_checked_not_silently_blank(world):
    body = world["client"].get(f"/search?plate={UNLISTED}", headers=hdr(world)).json()
    assert body["watchlist_status"]["checked"] is True
    assert body["watchlist_status"]["listed"] is False
    assert body["open_alerts"]["open"] == 0


def test_open_alert_count_respects_jurisdiction(world):
    body = world["client"].get(f"/search?plate={TARGET}",
                               headers=hdr(world, "inv.a")).json()
    # Two OPEN alerts on CAM-A (Ahmedabad); the CAM-B one is outside scope.
    assert body["open_alerts"]["open"] == 2


def test_a_witness_fragment_finds_the_mark_as_one_vehicle(world):
    r = world["client"].get("/search?plate=GJ99QT67", headers=hdr(world))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"]["type"] == "plate_pattern"
    marks = {m["plate"]: m for m in body["marks"]}
    assert TARGET in marks and OTHER in marks
    m = marks[TARGET]
    assert m["reads"] == 6
    assert {c["camera_id"] for c in m["cameras"]} == {"CAM-A", "CAM-B"}
    assert m["watchlist"] == {"listed": True, "category": "stolen_vehicle",
                              "priority": "HIGH"}
    assert body["marks"][0]["plate"] == TARGET        # most-read exact first
    assert body["query"]["terms"][0]["implicit_prefix"] is True


def test_pattern_results_withhold_out_of_scope_reads(world):
    body = world["client"].get("/search?plate=GJ99QT67*",
                               headers=hdr(world, "inv.a")).json()
    m = next(m for m in body["marks"] if m["plate"] == TARGET)
    assert m["reads"] == 5                            # CAM-B's read removed
    assert [c["camera_id"] for c in m["cameras"]] == ["CAM-A"]


def test_near_matches_on_a_whole_mark_cover_the_whole_store(world):
    """The near-match scan used to stop at the oldest 20,000 observations."""
    body = world["client"].get("/search?plate=GJ99QT6706&fuzzy=true",
                               headers=hdr(world)).json()
    plates = {c["plate"] for c in body["candidates"]}
    assert TARGET in plates
    scan = body["search_strategy"]["near_match_scan"]
    assert scan["capped"] is False and scan["marks_scanned"] >= 3
    c = next(c for c in body["candidates"] if c["plate"] == TARGET)
    assert c["match_chars"][-1] == {"ch": "5", "kind": "wild", "query": "6"}


def test_multi_plate_and_wildcard_query(world):
    body = world["client"].get("/search?plate=GJ98*44,GJ99QT67??",
                               headers=hdr(world)).json()
    assert {m["plate"] for m in body["marks"]} == {UNLISTED, TARGET, OTHER}


def test_a_too_loose_pattern_is_refused_with_a_reason(world):
    r = world["client"].get("/search?plate=G*", headers=hdr(world))
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BAD_PLATE_PATTERN"


def test_pattern_search_is_audited_with_the_case(world):
    world["client"].get("/search?plate=GJ99QT6*", headers=hdr(world))
    entries = world["state"].store.engine.connect().execute(
        S.audit_log.select().where(S.audit_log.c.action == "search_plate_pattern")
    ).fetchall()
    assert entries and entries[-1]._mapping["case_id"] == "FIR-T/2026"


def test_sealed_png_frames_are_served_as_png(world):
    state = world["state"]
    obs = state.store.search_plate(TARGET)[0]
    m = state.evidence.create(obs, frame=np.zeros((12, 16, 3), dtype=np.uint8))
    r = world["client"].get(f"/evidence/{m.evidence_id}/frame", headers=hdr(world))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
