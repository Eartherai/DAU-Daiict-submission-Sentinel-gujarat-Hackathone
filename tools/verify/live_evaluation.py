"""One command that runs the whole evaluation, and reports what actually happened.

The panel supplies a registration mark. This takes it through every stage the
scenario asks for — onboarding, analytics, search, correlation, watchlist,
alerting, evidence — against the live government grid, and writes a report whose
every claim carries the measurement behind it.

It is deliberately willing to report failure. A mark that was never seen produces
a report saying so, with the cameras that were searched and why the rest were
pruned; that is the correct outcome for a vehicle that did not pass a camera, and
a harness that could not produce it would be useless for judging the ones that
did.

    python tools/verify/live_evaluation.py --plate GJ38BH5815 \
        --db sqlite:///var/live.db --json var/reports/live_evaluation.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.common.paths import display
from saakshya.evidence.manifest import EvidenceService
from saakshya.investigation import CaseService, InvestigationService
from saakshya.live.timebase import TimebaseRegistry
from saakshya.security import AuthContext, Principal, Role
from saakshya.store import Store
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)


@dataclass
class Stage:
    name: str
    ok: bool
    summary: str
    ms: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000


def evaluate(store: Store, plate: str, *, case_id: str, purpose: str,
             authority: str) -> list[Stage]:
    stages: list[Stage] = []
    ctx = AuthContext(
        principal=Principal(user_id="evaluation", role=Role.SUPERVISOR,
                            districts=()),
        case_id=case_id, purpose=purpose)
    service = InvestigationService(store)
    cases = CaseService(store)
    evidence = EvidenceService(store, root=ROOT / "var" / "live_evidence")
    wl = WatchlistService(store)
    alerts = AlertEngine(store)
    timebase = TimebaseRegistry(store)

    # ---- 1. the estate that will be searched ------------------------------ #
    cams = store.list_cameras()
    located = [c for c in cams if c.get("lat") is not None]
    health = {r["camera_id"]: r for r in _health(store)}
    streaming = [c for c in cams
                 if health.get(c["camera_id"], {}).get("state") == "STREAMING"]
    stages.append(Stage(
        "estate", bool(cams),
        f"{len(cams)} cameras onboarded, {len(located)} with a position, "
        f"{len(streaming)} streaming at last ingest",
        detail={"cameras": len(cams), "located": len(located),
                "streaming": len(streaming),
                "unlocated": [c["camera_id"] for c in cams
                              if c.get("lat") is None][:12]}))

    # ---- 2. what those cameras can answer --------------------------------- #
    graded = {r["camera_id"]: r for r in store.list_capability()}
    anpr = {}
    for r in graded.values():
        g = str(r.get("anpr_grade", "UNKNOWN"))
        anpr[g] = anpr.get(g, 0) + 1
    stages.append(Stage(
        "capability", bool(graded),
        "ANPR grades: " + (", ".join(f"{v} {k}" for k, v in sorted(anpr.items()))
                           or "nothing graded yet"),
        detail={"anpr": anpr, "graded_cameras": len(graded)}))

    # ---- 3. the case the search is bound to -------------------------------- #
    try:
        cases.create(ctx, case_id=case_id, title=f"Evaluation trace of {plate}",
                     purpose=purpose, district="Ahmedabad",
                     classification="Evaluation")
        made = "created"
    except ValueError:
        made = "already open"
    stages.append(Stage("case", True, f"{case_id} {made}; every search below is "
                                      "recorded against it"))

    # ---- 4. watchlist ------------------------------------------------------- #
    existing = [e for e in wl.active_entries(plate)]
    if not existing:
        wl.add(VehicleOfInterest(
            plate=plate, category=Category.STOLEN_VEHICLE, authority=authority,
            reason=purpose, priority=Priority.HIGH, jurisdiction="Ahmedabad",
            created_by="evaluation"), actor="evaluation")
        existing = list(wl.active_entries(plate))
    stages.append(Stage(
        "watchlist", bool(existing),
        f"{len(existing)} active entry for {plate}, authority "
        f"'{authority}' — an entry with no stated authority cannot be created",
        detail={"entries": len(existing)}))

    # ---- 5. search ---------------------------------------------------------- #
    result, ms = timed(lambda: service.search_target(ctx, plate=plate))
    cands = result.get("candidates") if isinstance(result, dict) else []
    cands = cands or []
    stages.append(Stage(
        "search", True,
        (f"{len(cands)} observation(s) of {plate}"
         if cands else
         f"no stored observation carries {plate}. That is an absence of "
         "evidence, not evidence the vehicle was absent"),
        ms=ms,
        detail={"candidates": len(cands),
                "cameras_considered": (result.get("cameras_considered")
                                       if isinstance(result, dict) else None),
                "prune_reason": (result.get("prune_reason")
                                 if isinstance(result, dict) else None)}))

    seen_on = sorted({c["camera_id"] for c in cands if c.get("camera_id")})

    # ---- 6. may those cameras be correlated? -------------------------------- #
    partition = timebase.correlatable_set(seen_on) if seen_on else {}
    clusters = partition.get("clusters", {}) if partition else {}
    if not seen_on:
        tb_summary = "not applicable — the mark was not seen"
    elif len(seen_on) == 1:
        # A single sighting has no interval to reason about. Saying "no two of
        # them share a timebase" of one camera states a failure that does not
        # arise, and reads as a defect in the estate rather than as arithmetic.
        tb_summary = (f"seen on {seen_on[0]} only; a single sighting has no "
                      "interval to reason about, so no shared timebase is "
                      "needed or claimed")
    elif clusters:
        tb_summary = (f"seen on {len(seen_on)} cameras; "
                      f"{len(clusters)} shared-timebase cluster(s) among them — "
                      "intervals within a cluster are meaningful")
    else:
        tb_summary = (f"seen on {len(seen_on)} cameras, none of which were shown "
                      "to share a timebase; no interval between them is asserted")
    stages.append(Stage("timebase", True, tb_summary, detail=partition))

    # ---- 7. route ------------------------------------------------------------ #
    if cands:
        traj, ms = timed(lambda: service.build_trajectory(ctx, plate=plate))
        hyps = traj.get("hypotheses") or []
        tb = traj.get("timebase") or {}
        best = hyps[0] if hyps else {}
        stages.append(Stage(
            "trajectory", bool(hyps),
            (f"{len(hyps)} hypothesis; best is {best.get('status')} at score "
             f"{best.get('score')} across {len(best.get('camera_sequence') or [])} "
             f"camera(s). Timebase {tb.get('verdict')}"
             if hyps else "no route hypothesis could be built"),
            ms=ms,
            detail={"hypotheses": len(hyps), "timebase": tb.get("verdict"),
                    "timebase_message": tb.get("message")}))
    else:
        stages.append(Stage("trajectory", True,
                            "not attempted — there is nothing to join"))

    # ---- 8. alert ------------------------------------------------------------ #
    raised = []
    for c in cands:
        obs = service._observation_by_id(c["observation_id"])
        if obs is None:
            continue
        for m in wl.match(obs):
            a = alerts.process(m)
            if a is not None:
                raised.append(a)
    stats = alerts.stats()
    stages.append(Stage(
        "alert", True,
        (f"{len(raised)} alert(s) raised; "
         f"{stats.get('suppressed_low_confidence', 0)} suppressed as too weak "
         f"to act on, {stats.get('deduplicated_sightings', 0)} deduplicated"),
        detail={"raised": len(raised), **stats}))

    # ---- 9. evidence ---------------------------------------------------------- #
    sealed = []
    for c in cands[:3]:
        obs = service._observation_by_id(c["observation_id"])
        if obs is None:
            continue
        existing_ev = evidence.find_by_observation(obs.observation_id)
        m = existing_ev or evidence.create(obs, device="evaluation")
        sealed.append(m)
    # Verify each record as well as the chain. These are different claims: the
    # chain says no record has been removed or reordered, a record's own
    # verification says its manifest still hashes to what was written and that
    # any retained media is unmodified. Computing the per-record result and
    # reporting only the chain — which this did — is a quieter answer than the
    # work performed.
    per_record = []
    for m in sealed:
        r = evidence.verify(m.evidence_id)
        ok = getattr(r, "ok", None)
        if ok is None and isinstance(r, dict):
            ok = r.get("verified")
        per_record.append({"evidence_id": m.evidence_id, "verified": bool(ok),
                           "media": "frame" if m.frame_sha256 else "metadata-only"})
    chain = evidence.verify_chain()
    chain_ok = getattr(chain, "ok", None)
    if chain_ok is None and isinstance(chain, dict):
        chain_ok = chain.get("verified")
    records_ok = all(r["verified"] for r in per_record)
    media = {r["media"] for r in per_record}
    stages.append(Stage(
        "evidence", bool(chain_ok) and records_ok,
        (f"{len(sealed)} record(s) sealed, "
         f"{sum(r['verified'] for r in per_record)} of {len(per_record)} verify "
         f"individually; hash chain "
         f"{'VERIFIES' if chain_ok else 'DOES NOT VERIFY'}"
         + (f"; {', '.join(sorted(media))}" if media else "")),
        detail={"records": per_record, "chain_verified": bool(chain_ok)}))

    # ---- 10. audit -------------------------------------------------------------- #
    # Read the table, not a convenience accessor that may not exist. A first
    # version guarded with hasattr, found nothing, and printed "0 actions
    # recorded ... each with actor, role, purpose" — a claim about the contents
    # of an empty list.
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        mine = [dict(r._mapping) for r in c.execute(
            select(S.audit_log).where(S.audit_log.c.case_id == case_id)
            .order_by(S.audit_log.c.t_us.desc()).limit(500))]
    actions = sorted({str(e.get("action")) for e in mine})
    stages.append(Stage(
        "audit", bool(mine),
        (f"{len(mine)} action(s) recorded against {case_id}: "
         f"{', '.join(actions)} — each with actor, role, purpose and result count"
         if mine else
         f"nothing was recorded against {case_id}, which for a run that "
         "searched and sealed is a fault in the audit path, not a quiet pass"),
        detail={"entries_for_case": len(mine), "actions": actions}))

    return stages


def _health(store: Store) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(select(S.camera_health))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plate", required=True,
                    help="the registration mark supplied for evaluation")
    ap.add_argument("--db", default=f"sqlite:///{ROOT}/var/live.db")
    ap.add_argument("--case", default=None)
    ap.add_argument("--purpose",
                    default="evaluation trace of the designated vehicle")
    ap.add_argument("--authority",
                    default="Gujarat Police Innovation Challenge evaluation panel")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    case_id = a.case or f"EVAL-{a.plate}/2026"
    store = Store(a.db)
    store.create_all()

    print(f"SAAKSHYA live evaluation — {a.plate}")
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')}  store={a.db}\n")

    t0 = time.perf_counter()
    stages = evaluate(store, a.plate, case_id=case_id, purpose=a.purpose,
                      authority=a.authority)
    elapsed = time.perf_counter() - t0

    width = max(len(s.name) for s in stages)
    for s in stages:
        timing = f"{s.ms:7.1f} ms" if s.ms else " " * 10
        print(f"  {'ok ' if s.ok else 'NO '} {s.name:<{width}} {timing}  {s.summary}")

    print(f"\ncompleted in {elapsed:.2f}s")
    print("Every line above is what happened against the live store, including "
          "the lines that report nothing was found.")

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({
            "plate": a.plate, "case_id": case_id, "store": a.db,
            "generated_at": datetime.now(UTC).isoformat(),
            "elapsed_s": round(elapsed, 3),
            "stages": [s.__dict__ for s in stages]}, indent=2, default=str))
        print(f"written: {display(a.json, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
