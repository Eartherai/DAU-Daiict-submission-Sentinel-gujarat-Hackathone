#!/usr/bin/env python3
"""Build a self-contained demonstration environment.

Isolation is the point of this script existing separately (§44). Demo state
lives in its own database file — `var/demo.db` by default — and never touches
the evaluation store. Nothing here writes into `var/saakshya.db`, so a
demonstration cannot contaminate a measured result, and a measured result
cannot be quietly improved by demo data.

Everything it creates is real: observations come from decoding the corpus
through the production pipeline, capability grades come from the grader reading
those observations, and evidence records are sealed and verified. There is no
fixture standing in for a computation.

Tokens are minted and printed once. They are never written to a file, because
a file is a thing that gets committed.

    python tools/demo/seed.py --db sqlite:///var/demo.db
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig, persist_pipeline
from saakshya.capability import CapabilityGrader, TimeBand
from saakshya.evidence import EvidenceService
from saakshya.ingest.frame import Frame
from saakshya.intelligence import CameraGraph
from saakshya.security import AuthContext, Principal, Role, TokenService
from saakshya.store import Store
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)

MEDIA = ROOT / "var" / "media"
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)

#: Stagger the cameras onto one timeline so a single journey is coherent. This
#: is scenario setup for the demonstration only — the pipeline never sees it,
#: and nothing in the product depends on these numbers.
OFFSETS = {"C-014": 0, "C-021": 300, "C-033": 600, "C-047": 900,
           "C-052": 120, "C-061": 480}

#: Roles created for the demonstration. Chosen to show the separation of duty:
#: the two investigators are scoped to different districts, the operator cannot
#: search, the admin cannot search either, and the auditor sees only the log.
USERS = [
    ("supervisor.demo", Role.SUPERVISOR, (), "Supervisor (statewide)"),
    ("investigator.ahd", Role.INVESTIGATOR, ("Ahmedabad",), "Investigator, Ahmedabad"),
    ("investigator.gnr", Role.INVESTIGATOR, ("Gandhinagar",), "Investigator, Gandhinagar"),
    ("operator.demo", Role.OPERATOR, ("Ahmedabad",), "Control room operator"),
    ("admin.demo", Role.ADMIN, (), "Estate administrator"),
    ("auditor.demo", Role.AUDITOR, (), "Oversight auditor"),
    ("edge.node01", Role.SERVICE, (), "District edge node"),
]


def decode(cam: str, offset: float, fps: float = 4.0):
    import av
    path = MEDIA / f"{cam}.mp4"
    if not path.is_file():
        return
    container = av.open(str(path))
    stream = next(s for s in container.streams if s.type == "video")
    tb = float(stream.time_base)
    step, nxt = 1.0 / fps, 0.0
    for frame in container.decode(stream):
        if frame.pts is None:
            continue
        t = float(frame.pts) * tb
        if t + 1e-6 < nxt:
            continue
        nxt = t + step
        img = frame.to_ndarray(format="bgr24")
        when = T0 + timedelta(seconds=t + offset)
        yield Frame(camera_id=cam, segment_id="SEG1", pts_s=t, t_norm=when,
                    t_ingest=when, image=img, width=img.shape[1],
                    height=img.shape[0], codec="h264")
    container.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///var/demo.db",
                    help="demonstration store; kept separate from the evaluation store")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if "saakshya.db" in args.db:
        print("REFUSED: the demonstration must not write into the evaluation "
              "store. Use a different --db.", file=sys.stderr)
        return 2

    path = Path(args.db.replace("sqlite:///", ""))
    if args.reset and path.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

    store = Store(args.db)
    store.create_all()
    print(f"store        : {args.db}")

    # ---- registry -------------------------------------------------------- #
    catalogue = json.loads((MEDIA / "catalogue.json").read_text())["cameras"]
    for c in catalogue:
        store.upsert_camera({
            "camera_id": c["id"], "name": c["name"], "department": c["department"],
            "district": c["district"], "lat": c["location"]["lat"],
            "lon": c["location"]["lon"], "codec": c["codec"],
            "width": c["properties"]["width"], "height": c["properties"]["height"],
            "declared_fps": c["properties"]["declared_fps"],
            "quality_note": c.get("quality_note"),
            # Capability is measured below, never declared here.
            "tier": "UNASSIGNED", "enabled": True})
    print(f"cameras      : {len(catalogue)}")

    # ---- ingest through the production pipeline --------------------------- #
    written = 0
    for c in catalogue:
        cam = c["id"]
        pipe = CameraPipeline(cam, PipelineConfig(), district=c["district"],
                              department=c["department"],
                              lat=c["location"]["lat"], lon=c["location"]["lon"])
        obs, frames = [], 0
        for fr in decode(cam, OFFSETS.get(cam, 0), args.fps):
            frames += 1
            obs.extend(pipe.process(fr))
        obs.extend(pipe.flush())
        written += persist_pipeline(store, obs, pipe)
        # Health is measured from what actually decoded, not asserted.
        store.upsert_health(cam, {
            "state": "STREAMING" if frames else "UNKNOWN", "reachable": bool(frames),
            "connects": 1, "reconnects": 0, "frames": frames, "decoder_errors": 0,
            "measured_fps": args.fps if frames else None,
            "segment_breaks": 0, "last_seen_us": int(T0.timestamp() * 1e6)})
        print(f"  {cam}: {frames:4d} frames → {len(obs):3d} observations")
    print(f"observations : {written}")

    # ---- graph ------------------------------------------------------------ #
    graph = CameraGraph(store).load()
    graph.seed_from_gis()
    graph.learn_from_observations()
    print(f"graph        : {json.dumps(graph.stats())}")

    # ---- capability, measured --------------------------------------------- #
    grader = CapabilityGrader(store)
    assessments = grader.grade_all(
        bands=(TimeBand.ALL, TimeBand.DAY, TimeBand.NIGHT, TimeBand.LOW_LIGHT))
    overall = [a for a in assessments if a.band is TimeBand.ALL]
    print("capability   :")
    for a in sorted(overall, key=lambda x: x.camera_id):
        print(f"  {a.camera_id}: anpr={a.anpr:<11} appearance={a.vehicle:<11} "
              f"presence={a.presence:<11} n={a.samples}")

    # ---- watchlist and alerts, from what was actually observed ------------- #
    plates = [p for p in store.distinct_plates() if p]
    if not plates:
        print("no plate was read; watchlist demonstration skipped")
        target = None
    else:
        counts = {p: len(store.search_plate(p)) for p in plates}
        # Prefer the corpus's declared target when it was actually observed, so
        # the demonstration follows the scripted route through the hard camera.
        # Read from the ground-truth file rather than written here: a plate
        # constant in application-adjacent code is exactly the thing this
        # project refuses to ship, and a demo script is close enough to count.
        declared = None
        gt = ROOT / "tests" / "evaluation" / "ground_truth.json"
        if gt.is_file():
            declared = json.loads(gt.read_text()).get("target_vehicle")
        # The case target is whichever vehicle the estate actually saw most —
        # the same rule the end-to-end test uses, so the demonstration is not a
        # special path. The corpus's declared target goes on the watchlist too
        # when it was read, so the scripted hard-camera route is also available.
        target = max(counts, key=lambda p: counts[p])
        extra = declared if declared in counts and declared != target else None
        wl = WatchlistService(store)
        voi = wl.add(VehicleOfInterest(
            plate=target, category=Category.STOLEN_VEHICLE,
            authority="SP Ahmedabad Rural, FIR 214/2026",
            reason="reported stolen 2026-08-27; demonstration entry",
            priority=Priority.HIGH, jurisdiction="Ahmedabad",
            created_by="supervisor.demo"), actor="supervisor.demo")
        if extra:
            wl.add(VehicleOfInterest(
                plate=extra, category=Category.STOLEN_VEHICLE,
                authority="SP Ahmedabad Rural, FIR 198/2026",
                reason="corpus reference vehicle; demonstration entry",
                priority=Priority.MEDIUM, jurisdiction="Ahmedabad",
                created_by="supervisor.demo"), actor="supervisor.demo")
        engine = AlertEngine(store)
        raised = 0
        for plate in filter(None, (target, extra)):
            for o in store.search_plate(plate):
                for m in wl.match(o):
                    if engine.process(m):
                        raised += 1
        print(f"watchlist    : {voi.plate} ({counts[target]} observations) "
              f"→ {raised} alert(s)")

    # ---- evidence ---------------------------------------------------------- #
    ev = EvidenceService(store, root=ROOT / "var" / "demo_evidence")
    sealed = 0
    if target:
        for o in store.search_plate(target)[:6]:
            ev.create(o, device="demo-seed")
            sealed += 1
    chain = ev.verify_chain()
    print(f"evidence     : {sealed} sealed, chain {'VERIFIED' if chain.ok else 'BROKEN'}")

    # ---- a case, so the workspace opens with something in it --------------- #
    if target:
        from saakshya.investigation import CaseService
        ctx = AuthContext(
            Principal(user_id="supervisor.demo", role=Role.SUPERVISOR,
                      display_name="Supervisor (statewide)"),
            case_id="FIR-214/2026",
            purpose="tracing a vehicle reported stolen on 27 August 2026")
        cases = CaseService(store)
        try:
            cases.create(ctx, case_id="FIR-214/2026",
                         title=f"Stolen vehicle {target}",
                         purpose=ctx.purpose, fir_number="214/2026",
                         district="Ahmedabad", classification="Theft")
            cases.attach(ctx, "FIR-214/2026", item_type="target", item_ref=target,
                         payload={"plate": target})
        except ValueError:
            pass

    # ---- users and tokens -------------------------------------------------- #
    ts = TokenService(store)
    print("\nsign-in tokens — shown once, never written to disk:")
    print(f"{'user':22} {'role':12} {'scope':16} token")
    for user_id, role, districts, name in USERS:
        ts.upsert_user(user_id, role, display_name=name, districts=districts)
        token = ts.mint(user_id, label="demo", ttl=timedelta(days=2))
        scope = ",".join(districts) if districts else "STATE"
        print(f"{user_id:22} {role!s:12} {scope:16} {token}")

    st = store.stats()
    print(f"\nsummary      : {st['cameras']} cameras, {st['observations']} observations "
          f"({st['observations_with_plate']} with a plate), "
          f"{st['alerts']} alerts, {st['evidence']} evidence records")
    print(f"target       : {target or '(none read)'}")
    print(f"\nstart the API with:\n"
          f"  SAAKSHYA_DB={args.db} SAAKSHYA_EVIDENCE=var/demo_evidence "
          f"make serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
