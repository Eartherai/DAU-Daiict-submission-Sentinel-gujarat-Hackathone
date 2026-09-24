"""GIS layer: viewport bounding, clustering, and the wording of coverage gaps.

The last of those is a correctness test, not a copy test. The distinction
between "we cannot see here" and "the vehicle was not here" is the one an
investigator is most likely to collapse under time pressure, so the language the
map produces is asserted.
"""
from __future__ import annotations

import pytest

from saakshya.gis import BBox, MapService, cluster_points, mercator_xy
from saakshya.gis.service import _worst_state

AHM = (23.03, 72.58)


@pytest.fixture
def maps(store):
    for i in range(12):
        store.upsert_camera({
            "camera_id": f"MAP-{i:02d}", "name": f"map camera {i}",
            "district": "Ahmedabad" if i < 8 else "Gandhinagar",
            "department": "Home (Traffic)" if i % 2 else "Municipal",
            "lat": AHM[0] + i * 0.004, "lon": AHM[1] + i * 0.004,
            "tier": "A" if i < 4 else "C", "enabled": True})
    # One camera with no coordinates: it must be counted, never silently dropped.
    store.upsert_camera({"camera_id": "MAP-NOLOC", "name": "unlocated",
                         "district": "Ahmedabad"})
    return MapService(store)


# --------------------------------------------------------------------------- #
# BBox
# --------------------------------------------------------------------------- #
def test_bbox_parses_west_south_east_north():
    b = BBox.parse("72.4,22.9,72.9,23.3")
    assert (b.west, b.south, b.east, b.north) == (72.4, 22.9, 72.9, 23.3)


@pytest.mark.parametrize("bad", ["1,2,3", "a,b,c,d", "0,100,0,120", "0,80,0,10"])
def test_bad_bbox_raises(bad):
    with pytest.raises(ValueError):
        BBox.parse(bad)


def test_no_bbox_means_the_world():
    assert BBox.parse(None).contains(0.0, 0.0)


def test_expand_pads_the_viewport():
    b = BBox(23.0, 72.0, 23.2, 72.2).expand(0.5)
    assert b.south < 23.0 and b.north > 23.2


# --------------------------------------------------------------------------- #
# Viewport filtering happens server-side
# --------------------------------------------------------------------------- #
def test_viewport_excludes_cameras_outside_it(maps):
    tight = BBox(AHM[0] - 0.001, AHM[1] - 0.001, AHM[0] + 0.005, AHM[1] + 0.005)
    result = maps.cameras(bbox=tight)
    assert result["matched"] < 12
    assert all(tight.contains(f["lat"], f["lon"])
               for f in result["features"] if not f["cluster"])


def test_unlocated_cameras_are_reported_not_hidden(maps):
    result = maps.cameras()
    assert result["cameras_without_location"] == 1
    assert result["registry_total"] == result["matched"] + 1
    assert {u["camera_id"] for u in result["unlocated"]} == {"MAP-NOLOC"}
    assert all(f.get("camera_id") != "MAP-NOLOC" for f in result["features"])
    assert result["unlocated"][0]["located"] is False


def test_health_layer_includes_cameras_the_map_cannot_place(maps):
    """A camera without coordinates is still in the registry.

    Excluding it from health made eleven live-grid cameras look never-ingested
    on the wall, because the wall reads health from this layer.
    """
    result = maps.health()
    ids = {f["camera_id"] for f in result["features"]}
    assert "MAP-NOLOC" in ids
    assert result["unlocated"] == 1


def test_district_filter_is_applied_in_sql(maps):
    result = maps.cameras(districts=("Gandhinagar",))
    assert result["matched"] == 4
    assert {f["district"] for f in result["features"]} == {"Gandhinagar"}


def test_tier_filter(maps):
    assert maps.cameras(tiers=("A",))["matched"] == 4


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #
def test_dense_view_clusters(maps):
    result = maps.cameras(zoom=6, max_features=4)
    assert result["clustered"] is True
    assert result["returned"] < result["matched"]
    assert any(f.get("cluster") for f in result["features"])


def test_sparse_view_does_not_cluster(maps):
    result = maps.cameras(zoom=16, max_features=100)
    assert result["clustered"] is False
    assert all(f["cluster"] is False for f in result["features"])


def test_cluster_membership_is_complete():
    points = [{"camera_id": f"C-{i}", "lat": 23.0 + i * 1e-5,
               "lon": 72.0 + i * 1e-5, "state": "STREAMING"} for i in range(50)]
    clusters = cluster_points(points, zoom=8)
    counted = sum(c.get("count", 1) for c in clusters)
    assert counted == 50, "clustering lost points"


def test_clustering_is_stable_for_the_same_view():
    points = [{"camera_id": f"C-{i}", "lat": 23.0 + i * 1e-4,
               "lon": 72.0 + i * 1e-4, "state": "STREAMING"} for i in range(30)]
    a = cluster_points(points, zoom=10)
    b = cluster_points(list(reversed(points)), zoom=10)
    assert [c.get("cluster_id") for c in a] == [c.get("cluster_id") for c in b]


def test_a_cluster_reports_its_worst_state():
    points = [{"camera_id": "A", "lat": 23.0, "lon": 72.0, "state": "STREAMING"},
              {"camera_id": "B", "lat": 23.00001, "lon": 72.00001, "state": "DOWN"}]
    c = cluster_points(points, zoom=8)[0]
    assert c["cluster"] and c["count"] == 2
    assert c["state"] == "DOWN", "a dead camera was averaged away"


def test_worst_state_ordering():
    assert _worst_state(["OK", "DEGRADED"]) == "DEGRADED"
    assert _worst_state(["STREAMING", "DOWN", "OK"]) == "DOWN"
    assert _worst_state([None, None]) == "UNKNOWN"


def test_mercator_is_monotonic():
    x1, y1 = mercator_xy(23.0, 72.0, 10)
    x2, y2 = mercator_xy(23.1, 72.1, 10)
    assert x2 > x1 and y2 < y1        # north is up


# --------------------------------------------------------------------------- #
# Coverage — the wording is part of the contract
# --------------------------------------------------------------------------- #
def test_distance_gap_never_claims_the_vehicle_was_absent(store):
    store.upsert_camera({"camera_id": "FAR-1", "name": "a", "district": "Kutch",
                         "lat": 23.0, "lon": 70.0})
    store.upsert_camera({"camera_id": "FAR-2", "name": "b", "district": "Kutch",
                         "lat": 23.4, "lon": 70.4})
    cov = MapService(store).coverage()
    assert cov["total"] >= 2
    assert all(g["kind"] == "DISTANCE" for g in cov["gaps"])
    for g in cov["gaps"]:
        assert "does not indicate that any vehicle did" in g["explanation"]
    assert "never evidence about where a vehicle was" in cov["caveat"]


def test_capability_gap_is_reported_separately(store):
    store.upsert_camera({"camera_id": "CAP-1", "name": "soft", "district": "Ahmedabad",
                         "lat": 23.0, "lon": 72.6})
    store.upsert_camera({"camera_id": "CAP-2", "name": "near", "district": "Ahmedabad",
                         "lat": 23.001, "lon": 72.601})
    store.upsert_capability("CAP-1", "ALL", {
        "samples": 40, "anpr_grade": "UNSUITABLE", "vehicle_reid_grade": "GOOD",
        "presence_grade": "GOOD"})
    cov = MapService(store).coverage()
    caps = [g for g in cov["gaps"] if g["kind"] == "CAPABILITY"]
    assert len(caps) == 1
    assert "registration numbers are not recoverable" in caps[0]["explanation"]


def test_availability_gap_says_silence_proves_nothing(store):
    store.upsert_camera({"camera_id": "AV-1", "name": "down", "district": "Ahmedabad",
                         "lat": 23.0, "lon": 72.6})
    store.upsert_camera({"camera_id": "AV-2", "name": "up", "district": "Ahmedabad",
                         "lat": 23.001, "lon": 72.601})
    store.upsert_health("AV-1", {"state": "DOWN", "last_error": "connection refused"})
    cov = MapService(store).coverage()
    av = [g for g in cov["gaps"] if g["kind"] == "AVAILABILITY"]
    assert len(av) == 1
    assert "unobserved, not clear" in av[0]["explanation"]


def test_an_ungraded_camera_produces_no_capability_gap(store):
    """UNKNOWN is not a gap. Reporting it as one would turn "we have not
    measured this yet" into an operational finding."""
    store.upsert_camera({"camera_id": "UNK-1", "name": "x", "district": "Ahmedabad",
                         "lat": 23.0, "lon": 72.6})
    store.upsert_camera({"camera_id": "UNK-2", "name": "y", "district": "Ahmedabad",
                         "lat": 23.001, "lon": 72.601})
    cov = MapService(store).coverage()
    assert not [g for g in cov["gaps"] if g["kind"] == "CAPABILITY"]


# --------------------------------------------------------------------------- #
# Trajectory geometry keeps leg kinds distinct
# --------------------------------------------------------------------------- #
def test_leg_kinds_get_distinct_styles(maps):
    hypothesis = {
        "trajectory_id": "TR-1", "target": "GJ01AA1111", "status": "LIKELY",
        "score": 0.7,
        "camera_sequence": ["MAP-00", "MAP-01", "MAP-02"],
        "timestamps": ["2026-09-01T08:00:00+00:00", "2026-09-01T08:05:00+00:00",
                       "2026-09-01T08:12:00+00:00"],
        "legs": [
            {"from_camera": "MAP-00", "to_camera": "MAP-01", "kind": "OBSERVED"},
            {"from_camera": "MAP-01", "to_camera": "MAP-02", "kind": "COVERAGE_GAP"},
        ],
    }
    geom = maps.trajectory_geometry(hypothesis)
    styles = [leg["style"]["stroke"] for leg in geom["legs"]]
    assert styles[0] != styles[1], "observed and gap legs render identically"
    assert all(n["lat"] is not None for n in geom["nodes"])
    assert "straight-line link, not a driven route" in geom["caveat"]


def test_missing_health_with_observations_is_observed_not_unknown(maps, store):
    from tests.conftest import make_observation
    store.add_observations([make_observation("MAP-00", plate=None, offset_s=1)])
    health = maps.health()
    by_id = {f["camera_id"]: f for f in health["features"]}
    assert by_id["MAP-00"]["state"] == "OBSERVED"
    assert by_id["MAP-01"]["state"] == "UNKNOWN"
    cams = maps.cameras()
    feat = next(f for f in cams["features"] if f["camera_id"] == "MAP-00")
    assert feat["state"] == "OBSERVED"


def test_unsuitable_camera_still_reports_published_marks(maps, store):
    from tests.conftest import make_observation
    confirmed = make_observation("MAP-00", plate="GJ1VV0119", offset_s=1)
    lead = make_observation("MAP-00", plate="GJ31T1460", offset_s=2, track="T2")
    lead.plate_votes = 1
    store.add_observations([confirmed, lead])
    cap = maps.capability()
    row = next(f for f in cap["features"] if f["camera_id"] == "MAP-00")
    assert row["published_marks"] == 2
    assert row["published_confirmed"] == 1
    assert row["published_leads"] == 1
    empty = next(f for f in cap["features"] if f["camera_id"] == "MAP-01")
    assert empty["published_marks"] == 0


# --------------------------------------------------------------------------- #
# Nearby cameras
# --------------------------------------------------------------------------- #
def test_nearby_cameras_are_nearest_first_within_the_radius(maps, store):
    got = store.cameras_near(AHM[0], AHM[1], 1500)
    assert got["engine"].startswith("haversine")          # SQLite: no PostGIS
    ids = [c["camera_id"] for c in got["cameras"]]
    # MAP-i sits i * ~600 m up the diagonal; 1.5 km reaches MAP-00..MAP-02.
    assert ids == ["MAP-00", "MAP-01", "MAP-02"]
    d = [c["distance_m"] for c in got["cameras"]]
    assert d[0] == 0.0 and d == sorted(d) and d[-1] <= 1500
    assert "MAP-NOLOC" not in ids


def test_nearby_cameras_respect_the_officers_districts(maps, store):
    ids = [c["camera_id"] for c in store.cameras_near(
        AHM[0] + 0.03, AHM[1] + 0.03, 3000, districts=("Gandhinagar",))["cameras"]]
    assert ids and all(int(i[-2:]) >= 8 for i in ids)
    assert store.cameras_near(AHM[0], AHM[1], 3000, districts=())["cameras"] == []


def test_nearby_cameras_are_limited_after_ordering(maps, store):
    got = store.cameras_near(AHM[0], AHM[1], 50_000, limit=2)
    assert [c["camera_id"] for c in got["cameras"]] == ["MAP-00", "MAP-01"]
