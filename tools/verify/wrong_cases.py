"""Exercise the cases where the right answer is "no".

Most testing asks whether a system finds what is there. This asks what it does
when the answer should be nothing — which is where a public-safety system earns
or loses trust. Every case below has a correct refusal, and a refusal is only
useful if it is *specific*: "no observations" and "this camera cannot read
plates" and "these two cameras never shared a clock" are different findings, and
an investigator acts differently on each.

Run against the live store, after an ingest:

    python tools/verify/wrong_cases.py --db sqlite:///var/live.db
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.common.paths import display
from saakshya.live.timebase import Correlation, TimebaseRegistry
from saakshya.store import Store
from saakshya.store.repository import VehicleObservation
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)

#: A syntactically valid Gujarat mark that is not in the store. Deliberately not
#: a random string: "no results" for something malformed proves nothing, because
#: the query never had a chance.
ABSENT_PLATE = "GJ07XZ4409"
MALFORMED_PLATE = "NOT-A-PLATE-!!"


@dataclass
class Case:
    name: str
    expectation: str
    passed: bool = False
    observed: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _observation(plate: str | None, camera: str, *, quality: float,
                 confidence: float, oid: str) -> VehicleObservation:
    now = datetime.now(UTC)
    return VehicleObservation(
        observation_id=oid, camera_id=camera, track_id=f"TR-{oid}",
        segment_id=f"{camera}-S1", pts_s=1.0, t_norm=now, t_ingest=now,
        dedup_key=f"{camera}:{oid}", plate=plate, plate_confidence=confidence,
        observation_quality=quality,
        model_versions={"model": "wrong-cases-harness"})


def run(store: Store) -> list[Case]:
    cases: list[Case] = []
    wl = WatchlistService(store)
    alerts = AlertEngine(store)
    timebase = TimebaseRegistry(store)

    # ---- searching for something that is not there ------------------------ #
    hits = store.search_plate(ABSENT_PLATE)
    cases.append(Case(
        "a valid mark that was never seen",
        "returns nothing, and says nothing about where the vehicle was",
        passed=len(hits) == 0,
        observed=f"{len(hits)} observation(s)"))

    hits = store.search_plate(MALFORMED_PLATE)
    cases.append(Case(
        "a malformed mark",
        "returns nothing rather than erroring",
        passed=len(hits) == 0,
        observed=f"{len(hits)} observation(s)"))

    # ---- watchlist entries that must not fire ----------------------------- #
    expired = wl.add(VehicleOfInterest(
        plate="GJ99EX0001", category=Category.STOLEN_VEHICLE,
        authority="wrong-cases harness", reason="expired entry under test",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="harness",
        valid_until=datetime.now(UTC) - timedelta(days=1)), actor="harness")
    matches = wl.match(_observation("GJ99EX0001", "cam01", quality=0.95,
                                    confidence=0.99, oid="WC-EXP"))
    cases.append(Case(
        "an expired watchlist entry",
        "does not match; an entry past its validity is not authority to act",
        passed=len(matches) == 0,
        observed=f"{len(matches)} match(es)",
        detail={"watchlist_id": expired.watchlist_id}))

    revoked = wl.add(VehicleOfInterest(
        plate="GJ99RV0002", category=Category.STOLEN_VEHICLE,
        authority="wrong-cases harness", reason="revoked entry under test",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="harness"), actor="harness")
    wl.revoke(revoked.watchlist_id, actor="harness", reason="revoked under test")
    matches = wl.match(_observation("GJ99RV0002", "cam01", quality=0.95,
                                    confidence=0.99, oid="WC-REV"))
    cases.append(Case(
        "a revoked watchlist entry",
        "does not match after revocation",
        passed=len(matches) == 0,
        observed=f"{len(matches)} match(es)",
        detail={"watchlist_id": revoked.watchlist_id}))

    # ---- a read too poor to act on ---------------------------------------- #
    live = wl.add(VehicleOfInterest(
        plate="GJ99LQ0003", category=Category.STOLEN_VEHICLE,
        authority="wrong-cases harness", reason="low-quality read under test",
        priority=Priority.HIGH, jurisdiction="Ahmedabad",
        created_by="harness"), actor="harness")
    before = alerts.suppressed_low_confidence
    raised = [alerts.process(m) for m in wl.match(
        _observation("GJ99LQ0003", "cam01", quality=0.04, confidence=0.05,
                     oid="WC-LOW"))]
    raised = [a for a in raised if a is not None]
    cases.append(Case(
        "a plate read too poor to act on",
        "raises no alert, and counts the suppression rather than hiding it",
        passed=not raised and alerts.suppressed_low_confidence > before,
        observed=f"{len(raised)} alert(s), "
                 f"{alerts.suppressed_low_confidence - before} suppressed",
        detail={"watchlist_id": live.watchlist_id}))

    # ---- capability: a camera that cannot answer the question -------------- #
    graded = {r["camera_id"]: r for r in store.list_capability()}
    unsuitable = [c for c, r in graded.items()
                  if str(r.get("anpr_grade")) == "UNSUITABLE"]
    unknown = [c for c, r in graded.items()
               if str(r.get("anpr_grade")) == "UNKNOWN"]
    # The property is "no camera is graded able to read plates without evidence
    # for it", not "some camera happens to be UNSUITABLE". An empty store has
    # neither, and asserting the latter would fail on a fresh install for a
    # reason that says nothing about the system.
    good = [c for c, r in graded.items() if str(r.get("anpr_grade")) == "GOOD"]
    unevidenced = [c for c in good if not (graded[c].get("samples") or 0)]
    cases.append(Case(
        "a camera graded able to read plates",
        "is only ever GOOD on measured samples; UNSUITABLE and UNKNOWN are used "
        "rather than a default of good",
        passed=not unevidenced,
        observed=(f"{len(good)} GOOD, {len(unsuitable)} UNSUITABLE, "
                  f"{len(unknown)} UNKNOWN"
                  + (f"; {len(unevidenced)} GOOD with no samples" if unevidenced
                     else "")),
        detail={"unsuitable": unsuitable[:6], "unevidenced_good": unevidenced}))

    ungraded = [c["camera_id"] for c in store.list_cameras()
                if c["camera_id"] not in graded]
    cases.append(Case(
        "a camera never exercised",
        "is absent from the grading, not graded good by default",
        passed=all(str(graded.get(c, {}).get("anpr_grade", "UNKNOWN"))
                   != "GOOD" for c in ungraded),
        observed=f"{len(ungraded)} camera(s) never graded"))

    # ---- timing that cannot support a route -------------------------------- #
    health = timebase.all()
    clustered = [c for c, h in health.items() if h.time_cluster]
    unclustered = [c for c, h in health.items() if not h.time_cluster]
    if clustered and unclustered:
        verdict, why = timebase.may_correlate(clustered[0], unclustered[0])
        cases.append(Case(
            "two cameras with no shared timebase",
            "refuses or restricts correlation rather than inventing a clock",
            passed=verdict is not Correlation.ALLOWED,
            observed=f"{verdict}: {why[:90]}",
            detail={"pair": [clustered[0], unclustered[0]]}))
    if len(clustered) >= 2:
        verdict, why = timebase.may_correlate(clustered[0], clustered[1])
        cases.append(Case(
            "two cameras in one measured cluster",
            "is allowed — the refusal above must not be a blanket refusal",
            passed=verdict is Correlation.ALLOWED,
            observed=f"{verdict}: {why[:90]}",
            detail={"pair": clustered[:2]}))

    unreliable = [c for c, h in health.items() if not h.usable_for_correlation
                  and str(h.pts_health) == "UNRELIABLE"]
    if unreliable and clustered:
        verdict, _ = timebase.may_correlate(unreliable[0], clustered[0])
        cases.append(Case(
            "a camera whose own timing is unreliable",
            "cannot be placed on any timeline, cluster or no",
            passed=verdict is not Correlation.ALLOWED,
            observed=f"{verdict} for {unreliable[0]}",
            detail={"camera": unreliable[0]}))

    # ---- a camera that is not streaming ------------------------------------ #
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(select(S.camera_health))]
    never = len(store.list_cameras()) - len(rows)
    cases.append(Case(
        "a camera never observed",
        "is reported as unknown, never as healthy",
        passed=all(str(r.get("state")) != "STREAMING" or (r.get("frames") or 0) > 0
                   for r in rows),
        observed=f"{never} never ingested, {len(rows)} with recorded health"))

    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=f"sqlite:///{ROOT}/var/live.db")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    store = Store(a.db)
    store.create_all()
    cases = run(store)

    width = max(len(c.name) for c in cases)
    for c in cases:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name:<{width}}  {c.observed}")
        if not c.passed:
            print(f"      expected: {c.expectation}")
    failed = sum(not c.passed for c in cases)
    print(f"\n{len(cases) - failed} of {len(cases)} refusals were correct and "
          f"specific")
    if not failed:
        print("Every case above has a right answer of 'no'. A system that "
              "cannot say no precisely is not safe to say yes.")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(
            {"cases": [c.__dict__ for c in cases], "failed": failed}, indent=2))
        print(f"written: {display(a.json, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
