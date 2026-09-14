#!/usr/bin/env python3
"""Import a camera catalogue into the registry and start ingestion.

No camera id, department or endpoint is hard-coded anywhere. The catalogue is
the contract; the URL pattern is not, and the camera set is expected to change
between runs and during a run.

    python tools/data_intake/import_catalogue.py --catalogue <url-or-file>
    python tools/data_intake/import_catalogue.py --catalogue <url> --start --minutes 30
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from profile import load_catalogue, normalise_entry, validate

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig, persist_pipeline
from saakshya.ingest.stream import StreamConfig, StreamManager
from saakshya.intelligence import CameraGraph
from saakshya.store import Store


def import_catalogue(store: Store, entries: list[dict]) -> dict:
    """Create or update a registry record per camera. Idempotent."""
    added = updated = 0
    for e in entries:
        existing = store.get_camera(e["camera_id"])
        store.upsert_camera({
            "camera_id": e["camera_id"], "name": e["name"],
            "department": e["department"], "district": e["district"],
            "lat": e["lat"], "lon": e["lon"],
            "codec": e["codec"], "width": e["width"], "height": e["height"],
            "declared_fps": e["declared_fps"],
            "rtsp_url": e["rtsp_url"], "hls_url": e["hls_url"],
            "whep_url": e["whep_url"], "quality_note": e["quality_note"],
            # Capability is measured, never imported. A catalogue cannot know
            # what a camera can actually deliver.
            "tier": "UNASSIGNED",
        })
        if existing:
            updated += 1
        else:
            added += 1
    return {"added": added, "updated": updated, "total": len(entries)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", required=True)
    ap.add_argument("--token", default=None)
    ap.add_argument("--db", default="sqlite:///var/saakshya.db")
    ap.add_argument("--start", action="store_true",
                    help="start ingestion and analytics after import")
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--fps", type=float, default=2.0,
                    help="analytics sampling rate per camera")
    args = ap.parse_args()

    store = Store(args.db)
    store.create_all()

    raw = load_catalogue(args.catalogue, token=args.token)
    entries = [normalise_entry(e) for e in raw]
    entries, problems = validate(entries)

    print(f"catalogue : {args.catalogue}")
    print(f"entries   : {len(entries)}")
    if problems:
        print(f"problems  : {len(problems)} (reported, not skipped)")
        for p in problems[:10]:
            print(f"  ! {p}")

    result = import_catalogue(store, entries)
    print(f"registry  : +{result['added']} new, {result['updated']} updated")
    store.audit("data_intake", "catalogue_import", target=args.catalogue,
                result_count=result["total"])

    if not args.start:
        print("\nImported. Run with --start to begin ingestion.")
        return 0

    # -- ingestion ---------------------------------------------------------- #
    catalogue = {e["camera_id"]: e["rtsp_url"] for e in entries if e["rtsp_url"]}
    if not catalogue:
        print("no RTSP sources in the catalogue; nothing to ingest")
        return 1

    mgr = StreamManager(StreamConfig())
    mgr.reconcile(catalogue)
    print(f"\ningesting {len(catalogue)} cameras for {args.minutes:.0f} min "
          f"at {args.fps} fps analytics")

    cams = {e["camera_id"]: e for e in entries}
    pipes = {cid: CameraPipeline(cid, PipelineConfig(),
                                 district=cams[cid]["district"],
                                 department=cams[cid]["department"],
                                 lat=cams[cid]["lat"], lon=cams[cid]["lon"])
             for cid in catalogue}
    queues = {cid: mgr.get(cid).subscribe("intake") for cid in catalogue}

    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    t_end = time.time() + args.minutes * 60
    last_report = time.time()
    next_analyse: dict[str, float] = {}
    written = 0

    while time.time() < t_end and not stop["now"]:
        for cid, q in queues.items():
            try:
                fr = q.get(timeout=0.01)
            except Exception:
                continue
            if fr is None:
                continue
            # Sample by PTS so the rate is identical on a 2 fps and a 25 fps feed.
            if fr.pts_s < next_analyse.get(cid, 0.0):
                continue
            next_analyse[cid] = fr.pts_s + 1.0 / args.fps
            obs = pipes[cid].process(fr)
            written += persist_pipeline(store, obs, pipes[cid])

        if time.time() - last_report >= 30:
            a = mgr.aggregate()
            print(f"  streaming={a['cameras_streaming']}/{a['cameras_total']} "
                  f"frames={a['frames']:,} reconnects={a['reconnects']} "
                  f"observations={written}")
            last_report = time.time()

    for cid, p in pipes.items():
        obs = p.flush()
        written += persist_pipeline(store, obs, p)
        health = mgr.stats().get(cid)
        if health:
            store.upsert_health(cid, health)

    mgr.stop_all()

    graph = CameraGraph(store).load()
    graph.seed_from_gis()
    graph.learn_from_observations()

    st = store.stats()
    print(f"\nobservations : {st['observations']} ({st['observations_with_plate']} with a plate)")
    print(f"graph        : {json.dumps(graph.stats())}")
    print(f"generated    : {datetime.now(UTC).isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
