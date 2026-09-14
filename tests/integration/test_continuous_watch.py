"""Live cross-referencing: an observation is matched as it is written.

The challenge asks for continuous cross-referencing of live feeds against a
watchlist, with automated alerts. The live path used to only *write*
observations; alerts were raised afterwards, by the API or by hand — a batch
forensic workflow wearing the words of a real-time one. That gap is invisible
from the outside, because the alert eventually exists either way.

These exercise the loop the ingest consumer runs, against a real store.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from saakshya.store import Store
from saakshya.store.repository import VehicleObservation
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)

PLATE = "GJ38BH5815"


@pytest.fixture
def live(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/watch.db")
    store.create_all()
    store.upsert_camera({"camera_id": "cam21", "name": "Dethali Char Rasta",
                         "district": "Ahmedabad"})
    wl = WatchlistService(store)
    wl.add(VehicleOfInterest(
        plate=PLATE, category=Category.STOLEN_VEHICLE,
        authority="evaluation panel",
        reason="designated vehicle supplied at evaluation",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="sup.test"), actor="sup.test")
    return store, wl, AlertEngine(store)


def observation(plate: str | None, *, quality: float = 0.96,
                confidence: float = 0.99, oid: str = "OB1",
                when: datetime | None = None) -> VehicleObservation:
    t = when or datetime.now(UTC)
    return VehicleObservation(
        observation_id=oid, camera_id="cam21", track_id=f"TR-{oid}",
        segment_id="cam21-S1", pts_s=93.8, t_norm=t, t_ingest=t,
        dedup_key=f"cam21:{oid}", plate=plate, plate_confidence=confidence,
        observation_quality=quality, district="Ahmedabad",
        model_versions={"model": "anpr-onnx-cpu@1.0.0"})


def consume(store, wl, alerts, obs):
    """Exactly what the ingest consumer does for a batch of observations."""
    store.add_observations(obs)
    raised = []
    for o in obs:
        if not o.plate:
            continue
        for m in wl.match(o):
            a = alerts.process(m)
            if a is not None:
                raised.append(a)
    return raised


def test_a_watchlisted_plate_alerts_as_it_is_written(live):
    store, wl, alerts = live
    raised = consume(store, wl, alerts, [observation(PLATE)])
    assert len(raised) == 1
    assert raised[0].plate == PLATE
    assert raised[0].confidence > 0.5


def test_a_plate_not_on_the_watchlist_raises_nothing(live):
    store, wl, alerts = live
    assert consume(store, wl, alerts, [observation("GJ01ZZ9999")]) == []


def test_an_observation_with_no_plate_raises_nothing(live):
    """Most live observations carry no mark. They must not cost a lookup that
    can match, and must never alert."""
    store, wl, alerts = live
    assert consume(store, wl, alerts, [observation(None)]) == []


def test_a_repeat_sighting_folds_into_the_open_alert(live):
    """A vehicle sitting in front of a camera must not produce a second alert.

    The engine folds the repeat into the open one and returns it *updated*,
    which is better than suppressing: the operator sees one alert that now
    cites two sightings. A caller counting returns rather than distinct ids
    would report two alerts where there is one — and the inflated number is the
    one that would get quoted.
    """
    store, wl, alerts = live
    first = consume(store, wl, alerts, [observation(PLATE, oid="OB1")])
    again = consume(store, wl, alerts, [observation(PLATE, oid="OB2")])
    assert len(first) == 1
    assert len(again) == 1
    assert again[0].alert_id == first[0].alert_id, "a second alert was raised"
    assert alerts.deduplicated >= 1
    assert len({a.alert_id for a in first + again}) == 1


def test_a_low_confidence_read_is_suppressed_and_counted(live):
    """Suppression is not silence: an operator can see how many were held back."""
    store, wl, alerts = live
    raised = consume(store, wl, alerts,
                     [observation(PLATE, quality=0.05, confidence=0.05)])
    assert raised == []
    assert alerts.suppressed_low_confidence >= 1


def test_an_expired_entry_does_not_alert(live):
    """A watchlist entry past its validity is not authority to stop a vehicle."""
    store, wl, alerts = live
    wl.add(VehicleOfInterest(
        plate="GJ21T4831", category=Category.STOLEN_VEHICLE,
        authority="evaluation panel", reason="expired entry",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="sup.test",
        valid_until=datetime.now(UTC) - timedelta(days=1)), actor="sup.test")
    assert consume(store, wl, alerts, [observation("GJ21T4831", oid="OB9")]) == []
