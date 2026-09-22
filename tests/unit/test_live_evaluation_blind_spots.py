"""Two faults that would only have shown up during the live evaluation.

Both were found by auditing against the challenge's Step 4 test case — onboard
~50 cameras, then trace a designated vehicle handed over on the day — and
neither is visible from a passing demonstration on pre-seeded data.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from saakshya.intelligence.search import VehicleSearch
from saakshya.store import SearchFilter, Store, VehicleObservation


def _obs(store: Store, camera_id: str, when: datetime, plate: str | None = None,
         key: str = "") -> VehicleObservation:
    return VehicleObservation(
        camera_id=camera_id, pts_s=0.0, t_norm=when, t_ingest=when,
        dedup_key=key or f"{camera_id}-{when.timestamp()}-{plate}",
        plate=plate, object_type="car")


# -- 1. corroboration scanned the oldest rows, not the relevant ones ---------- #

def test_corroboration_reaches_a_sighting_behind_a_wall_of_older_rows(tmp_path):
    """The designated vehicle is seen *now*, behind a backlog of history.

    `follow_vehicle` used to fetch `SearchFilter(limit=20_000)` over the whole
    store, and `store.search` orders by time ascending — so it returned the
    OLDEST twenty thousand rows. Measured against var/live.db on 22 Sep 2026:
    1,024,103 observations, of which that scan reached 2.0%, leaving the most
    recent 453 hours unreachable. The route came back empty and nothing on
    screen explained why.

    The backlog here is deliberately larger than that old hardcoded budget.
    A smaller one passes against the broken code — the first draft of this
    test used sixty rows and proved nothing.
    """
    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    for cam, lat, lon in (("cam01", 23.02, 72.57), ("cam02", 23.03, 72.58)):
        store.upsert_camera({"camera_id": cam, "district": "Ahmedabad",
                             "department": "Home (Police)", "lat": lat, "lon": lon})

    base = datetime(2026, 9, 1, tzinfo=UTC)
    BACKLOG = 20_050            # > the 20,000 the old scan could ever reach
    store.add_observations(
        [_obs(store, "cam01", base + timedelta(seconds=i), key=f"old-{i}")
         for i in range(BACKLOG)])

    # The mark, seen on two cameras twenty days later and four minutes apart —
    # comfortably outside the oldest 20,000 rows.
    late = base + timedelta(days=20)
    store.add_observations([
        _obs(store, "cam01", late, plate="GJ18X6705", key="hit-a"),
        _obs(store, "cam02", late + timedelta(minutes=4), plate="GJ18X6705",
             key="hit-b"),
    ])

    out = VehicleSearch(store).follow_vehicle(
        "GJ18X6705", case_id="FIR-1/2026",
        purpose="tracing a designated vehicle")
    cams = {c.get("camera_id") for c in out.get("candidates", [])}
    assert "cam02" in cams, (
        "the corroborating sighting was not reached behind a backlog of "
        f"{BACKLOG:,} older rows; the scan is returning the wrong end of the "
        f"store. candidates={out.get('candidates')}")


def test_the_corroboration_window_does_not_fetch_the_whole_store(tmp_path):
    """Correct is not enough — it must also not read a million rows.

    The loop discards any candidate more than an hour after an origin, so
    fetching beyond that is pure cost. This pins the query shape, because the
    obvious 'fix' of raising the limit would restore correctness and make the
    scan worse.
    """
    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam01", "district": "Ahmedabad"})
    base = datetime(2026, 9, 1, tzinfo=UTC)
    store.add_observations(
        [_obs(store, "cam01", base, plate="GJ18X6705", key="origin")])

    seen: list[SearchFilter] = []
    real = store.search

    def spy(f: SearchFilter):
        seen.append(f)
        return real(f)

    store.search = spy                                    # type: ignore[method-assign]
    VehicleSearch(store).follow_vehicle(
        "GJ18X6705", case_id="FIR-1/2026", purpose="tracing")

    bounded = [f for f in seen if f.plate is None]
    assert bounded, "no corroboration query was issued"
    for f in bounded:
        assert f.t_from is not None and f.t_to is not None, (
            "the corroboration query is unbounded in time; it will read the "
            "whole store and return its oldest rows")
        span = (f.t_to - f.t_from).total_seconds()
        assert span <= VehicleSearch.FOLLOW_WINDOW_S + 1, (
            f"window of {span}s exceeds the {VehicleSearch.FOLLOW_WINDOW_S}s "
            "corridor the loop actually reads")


# -- 2. a camera onboarded after boot never entered the registry cache ------- #

def test_a_camera_onboarded_after_boot_still_stamps_its_observations(tmp_path):
    """Onboarding during the evaluation is the evaluation.

    The registry cache warmed once and `_ensure_cam_cache` returned early
    whenever the dict was non-empty, so a camera onboarded afterwards never
    entered it. Its observations were then stored with no district — and
    district is an access-control dimension, so a scoped investigator could not
    reach them at all. The own-feed recording onboards a camera on camera, and
    the Step 4 test case asks for ~50 of them.
    """
    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam01", "district": "Ahmedabad",
                         "department": "Home (Police)"})

    when = datetime(2026, 9, 1, tzinfo=UTC)
    store.add_observations([_obs(store, "cam01", when, key="warm")])   # warms it

    store.upsert_camera({"camera_id": "NEW-01", "district": "Rajkot",
                         "department": "Municipal Corporation",
                         "lat": 22.30, "lon": 70.80})
    store.add_observations([_obs(store, "NEW-01", when, key="late")])

    got = store.search(SearchFilter(cameras=["NEW-01"], limit=5))
    assert got, "the observation was not stored"
    assert got[0].district == "Rajkot", (
        f"district not denormalised from the registry (got {got[0].district!r}); "
        "a district-scoped investigator cannot reach this row")
    assert got[0].department == "Municipal Corporation"
    assert got[0].lat == 22.30


def test_an_unregistered_camera_is_not_requeried_on_every_batch(tmp_path):
    """The miss path must remember a negative answer.

    Observations arrive from unregistered cameras routinely. Without a negative
    cache the single-row lookup that fixes the bug above would fire on every
    batch, for every such camera, forever.
    """
    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam01", "district": "Ahmedabad"})
    when = datetime(2026, 9, 1, tzinfo=UTC)
    store.add_observations([_obs(store, "cam01", when, key="warm")])

    for i in range(3):
        store.add_observations(
            [_obs(store, "GHOST", when + timedelta(seconds=i), key=f"g{i}")])
    assert "GHOST" in store._cam_cache_absent


def test_onboarding_a_previously_unknown_camera_clears_the_negative_cache(tmp_path):
    """Otherwise the negative cache becomes the new bug.

    A camera can send observations before it is registered — which is precisely
    the onboarding order on the day.
    """
    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    store.upsert_camera({"camera_id": "cam01", "district": "Ahmedabad"})
    when = datetime(2026, 9, 1, tzinfo=UTC)
    store.add_observations([_obs(store, "cam01", when, key="warm")])
    store.add_observations([_obs(store, "LATE-01", when, key="before")])
    assert "LATE-01" in store._cam_cache_absent

    store.upsert_camera({"camera_id": "LATE-01", "district": "Junagadh"})
    store.add_observations(
        [_obs(store, "LATE-01", when + timedelta(seconds=1), key="after")])

    rows = store.search(SearchFilter(cameras=["LATE-01"], limit=5))
    latest = sorted(rows, key=lambda o: o.t_norm)[-1]
    assert latest.district == "Junagadh"


# -- 3. the fixture guard deleted the cameras being evaluated ---------------- #

def test_onboarding_fifty_government_cameras_survives_a_restart(tmp_path):
    """The evaluation grid names cameras `camNN`, and supplies about fifty.

    `enforce_evaluation_50` runs at API startup. It builds a keep-set of
    cam01..cam30, then asks `_is_evaluation_fixture` whether it may delete
    whatever is left over — and that answered yes for *any* `cam<digits>`.
    Since cam01..cam30 were already skipped as wanted, the only ids that ever
    reached the question were ones outside the seeded range: the onboarded
    ones. Onboard the challenge's ~50 cameras, restart, and cam31..cam50 were
    gone, with nothing logged and nothing on screen.
    """
    from saakshya.command.domain import enforce_evaluation_50

    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    enforce_evaluation_50(store)                      # seeds cam01..cam30

    onboarded = [f"cam{i:02d}" for i in range(31, 51)]
    for cid in onboarded:
        store.upsert_camera({
            "camera_id": cid, "name": f"Evaluation camera {cid}",
            "district": "Ahmedabad", "department": "Home (Police)",
            "source_domain": "GOVERNMENT"})

    enforce_evaluation_50(store)                      # the restart

    survivors = {c["camera_id"] for c in store.list_cameras()}
    lost = [cid for cid in onboarded if cid not in survivors]
    assert not lost, (
        f"the fixture guard deleted {len(lost)} onboarded evaluation cameras "
        f"at startup: {lost}")


def test_the_guard_still_prunes_its_own_fixtures(tmp_path):
    """The fix must not turn the guard into a no-op.

    It is still entitled to tidy up what it created — that is the whole point
    of keeping the wall at a known composition.
    """
    from saakshya.command.domain import enforce_evaluation_50

    store = Store(f"sqlite:///{tmp_path/'t.db'}")
    store.create_all()
    enforce_evaluation_50(store)
    store.upsert_camera({"camera_id": "FAR", "name": "extra fixture"})
    store.upsert_camera({"camera_id": "CTL-EXTRA", "name": "extra slot",
                         "source_domain": "SYNTHETIC_CONTROL"})

    out = enforce_evaluation_50(store)
    survivors = {c["camera_id"] for c in store.list_cameras()}
    assert "FAR" not in survivors
    assert "CTL-EXTRA" not in survivors
    assert set(out["removed"]) >= {"FAR", "CTL-EXTRA"}
