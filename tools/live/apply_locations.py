#!/usr/bin/env python3
"""Apply derived camera locations to the registry.

The authoritative catalogue carries coordinates and needs a signed-in session we
do not hold. Without them the map cannot be populated at all — thirty working,
graded cameras with nowhere to draw them.

So locations are derived from the place names the cameras themselves carry, and
**every one is labelled with how far it can be trusted**:

    LANDMARK   ~150 m   a specific named junction, bridge or building
    LOCALITY   ~1.5 km  a named neighbourhood or village
    CITY       ~6 km    only the town is known
    UNKNOWN    no coordinate assigned

A camera whose name does not identify a place gets **no coordinate**. Several
carry only a device label — "IPC", "CP IP Cam". Guessing at those would put a
marker somewhere plausible and wrong, which is worse for an investigator than
an honest gap.

These positions let an investigator reason about corridors. They are not
evidence of where a vehicle was, and nothing in the system treats them as such:
travel-time plausibility already comes from *observed* transitions, not from
straight-line distance.

    python tools/live/apply_locations.py --db sqlite:///var/live.db
    python tools/live/apply_locations.py --db ... --clear   # remove derived ones
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.common.paths import display
from saakshya.store import Store

DEFAULT_FILE = ROOT / "config" / "camera_locations.json"

#: Rough bounds of Gujarat. A derived coordinate outside them is a mistake in
#: this file, not a camera in the Arabian Sea — so it is refused rather than
#: drawn.
GUJARAT = {"south": 20.0, "north": 24.8, "west": 68.0, "east": 74.6}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="sqlite:///var/live.db")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--clear", action="store_true",
                    help="remove coordinates that were derived from names, "
                         "leaving anything the catalogue supplied")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    store = Store(args.db)
    store.create_all()
    known = {c["camera_id"]: c for c in store.list_cameras()}
    if not known:
        print("the registry is empty — import or discover the camera set first",
              file=sys.stderr)
        return 2

    if args.clear:
        cleared = 0
        for cam in known.values():
            if cam.get("location_basis") == "DERIVED_FROM_NAME":
                store.upsert_camera({**cam, "lat": None, "lon": None,
                                     "location_basis": "UNKNOWN",
                                     "location_precision": "UNKNOWN"})
                cleared += 1
        print(f"cleared {cleared} derived coordinate(s)")
        return 0

    data = json.loads(args.file.read_text())
    basis = data.get("basis", "DERIVED_FROM_NAME")
    applied = skipped = refused = unmatched = 0
    rejected: list[str] = []

    for entry in data["cameras"]:
        cid = entry["id"]
        cam = known.get(cid)
        if cam is None:
            unmatched += 1
            continue

        # The catalogue is authoritative wherever it has spoken.
        if cam.get("location_basis") == "CATALOGUE":
            skipped += 1
            continue

        lat, lon = entry.get("lat"), entry.get("lon")
        if lat is None or lon is None:
            # Recorded as deliberately unlocated, with the reason, rather than
            # left indistinguishable from "not looked at yet".
            if not args.dry_run:
                store.upsert_camera({
                    **cam,
                    "name": entry.get("name") or cam.get("name") or cid,
                    "site": entry.get("site") or cam.get("site"),
                    "district": entry.get("district") or cam.get("district"),
                    "department": entry.get("department") or cam.get("department"),
                    "location_basis": "NAME_INSUFFICIENT",
                    "location_precision": "UNKNOWN",
                    "location_note": entry.get("note") or entry.get("source")
                    or cam.get("location_note"),
                    "quality_note": entry.get("note") or cam.get("quality_note"),
                    "lat": None,
                    "lon": None,
                }, clear={"lat", "lon"})
            skipped += 1
            continue

        if not (GUJARAT["south"] <= lat <= GUJARAT["north"]
                and GUJARAT["west"] <= lon <= GUJARAT["east"]):
            rejected.append(f"{cid} at {lat},{lon} is outside Gujarat")
            refused += 1
            continue

        if not args.dry_run:
            store.upsert_camera({
                **cam,
                "name": entry.get("name") or cam.get("name") or cid,
                "site": entry.get("site"),
                "district": entry.get("district") or cam.get("district"),
                # Recorded only where the camera's own name or signage states
                # it. A traffic junction in Gujarat could belong to either
                # Police or Municipal Corporation, and guessing between them
                # would put a department on a slide that nobody verified.
                "department": entry.get("department") or cam.get("department"),
                "lat": lat, "lon": lon,
                "location_basis": basis,
                "location_precision": entry.get("precision", "UNKNOWN"),
                "location_note": entry.get("source") or entry.get("note")
                or cam.get("location_note"),
            })
        applied += 1

    print(f"file      : {display(args.file, ROOT)}")
    print(f"basis     : {basis}")
    print(f"applied   : {applied} camera(s) placed")
    print(f"unlocated : {skipped} (name does not identify a place, or the "
          "catalogue already spoke)")
    if refused:
        print(f"refused   : {refused}")
        for r in rejected:
            print(f"  ! {r}")
    if unmatched:
        print(f"not in the registry: {unmatched}")

    if not args.dry_run:
        located = [c for c in store.list_cameras() if c.get("lat") is not None]
        from collections import Counter
        print(f"\nregistry  : {len(located)} located of {len(known)}")
        print("precision :", dict(Counter(
            c.get("location_precision") for c in located)))
        print("districts :", dict(Counter(
            c.get("district") for c in located)))
        ext = store.camera_extent()
        print(f"extent    : {ext}")
    print("\nThese are approximate positions derived from camera names. They "
          "place a camera near the right junction so corridors can be reasoned "
          "about. They are not surveyed positions and are never evidence of "
          "where a vehicle was.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
