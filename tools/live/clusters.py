#!/usr/bin/env python3
"""Declare and inspect camera time clusters.

A time cluster is a set of cameras believed to share a timebase, so that
observations across them may be placed on one timeline. On the live Gujarat grid
this is not a formality: twelve cameras replay a common window while others are
hours or weeks apart, and joining two of the latter produces a journey that
never happened.

Membership is **evidence, recorded with its basis**. A cluster read off the
cameras' own burned-in clocks is stronger than one asserted here, and both are
stronger than nothing — but the interface reports which, because an investigator
relying on a route is entitled to know what the timing rests on.

    python tools/live/clusters.py show   --db sqlite:///var/live.db
    python tools/live/clusters.py declare --db sqlite:///var/live.db \\
        --id GRID-14JUN-0353 --cameras cam01,cam02,cam04 \\
        --basis MEASURED_OVERLAY --reference 2026-06-14T03:53:38 \\
        --note "read from burned-in overlays within 3 minutes"
    python tools/live/clusters.py check --db sqlite:///var/live.db \\
        --cameras cam01,cam20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.live.timebase import ClusterBasis, TimebaseRegistry
from saakshya.store import Store


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="sqlite:///var/live.db")
    # Repeated on every subparser: `clusters.py show --db ...` is what anyone
    # actually types, and rejecting it because the option must precede the
    # subcommand is a needless papercut.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=None)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("show", parents=[common],
                   help="clusters and per-camera timebase health")

    d = sub.add_parser("declare", parents=[common],
                       help="record a set of cameras as one timebase")
    d.add_argument("--id", required=True)
    d.add_argument("--cameras", required=True, help="comma-separated")
    d.add_argument("--label", default="")
    d.add_argument("--basis", default="DECLARED",
                   choices=[str(b) for b in ClusterBasis])
    d.add_argument("--reference", default=None,
                   help="the shared scene time this cluster was read at")
    d.add_argument("--skew", type=float, default=None,
                   help="largest observed skew between members, seconds")
    d.add_argument("--note", default="")

    c = sub.add_parser("check", parents=[common],
                       help="may these cameras be correlated?")
    c.add_argument("--cameras", required=True)

    args = ap.parse_args()
    db = args.db or "sqlite:///var/live.db"
    store = Store(db)
    store.create_all()
    registry = TimebaseRegistry(store)

    if args.command == "show":
        clusters = registry.clusters()
        health = registry.all()
        if clusters:
            print("time clusters")
            for cl in clusters:
                print(f"\n  {cl['cluster_id']}  [{cl['basis']}]  "
                      f"{cl['member_count']} cameras")
                if cl.get("label"):
                    print(f"    label     : {cl['label']}")
                if cl.get("reference_time"):
                    print(f"    reference : {cl['reference_time']}")
                if cl.get("max_skew_s") is not None:
                    print(f"    max skew  : {cl['max_skew_s']:.0f}s")
                if cl.get("note"):
                    print(f"    note      : {cl['note']}")
                print(f"    cameras   : {', '.join(cl['cameras'])}")
        else:
            print("no time clusters declared — every cross-camera route will "
                  "carry a timebase warning")
        print(f"\n{'camera':10} {'pts':12} {'fps':7} {'ratio':7} "
              f"{'cluster':22} correlatable")
        for cam, h in sorted(health.items()):
            print(f"{cam:10} {h.pts_health!s:12} "
                  f"{h.measured_fps or '-':>7} "
                  f"{h.realtime_ratio if h.realtime_ratio is not None else '-':>7} "
                  f"{h.time_cluster or '(none)':22} "
                  f"{'yes' if h.usable_for_correlation else 'NO'}")
        return 0

    if args.command == "declare":
        cams = [x.strip() for x in args.cameras.split(",") if x.strip()]
        known = {c["camera_id"] for c in store.list_cameras()}
        missing = [c for c in cams if c not in known]
        if missing:
            print(f"REFUSED: not in the registry: {missing}. Import the "
                  "catalogue first — a cluster over cameras the system does not "
                  "know about is an assertion with nothing behind it.",
                  file=sys.stderr)
            return 2
        out = registry.declare_cluster(
            args.id, cams, label=args.label, basis=ClusterBasis(args.basis),
            reference_time=args.reference, max_skew_s=args.skew, note=args.note)
        print(json.dumps(out, indent=2))
        return 0

    if args.command == "check":
        cams = [x.strip() for x in args.cameras.split(",") if x.strip()]
        for i, a in enumerate(cams):
            for b in cams[i + 1:]:
                verdict, why = registry.may_correlate(a, b)
                print(f"{a} + {b}: {verdict}")
                print(f"    {why}")
        print()
        print(json.dumps(registry.correlatable_set(cams), indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
