#!/usr/bin/env python3
"""Prove that every registered model actually loads and infers.

A registry entry is a *claim* that a model is available. It is not evidence.
This project learned the difference the hard way: a vehicle detector sat in the
registry, behind a feature flag that defaulted to off, loaded through the wrong
class, raising on every frame, with a broad exception handler reporting the
result as "no vehicles". Every test passed. It had never produced a detection.

This gate runs six checks per model and reports the first that fails.

    python tools/verify/validate_models.py
    python tools/verify/validate_models.py --strict     # fail on any FAILED
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.common.paths import display
from saakshya.models.validation import Activation, validate_all


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if any model fails, not only the ones "
                         "the pipeline depends on")
    ap.add_argument("--no-inference", action="store_true",
                    help="check loading only; do not run a forward pass")
    ap.add_argument("--json", type=Path,
                    default=ROOT / "var" / "reports" / "model_validation.json")
    args = ap.parse_args()

    #: Models the mandatory chain will not run without. A failure here is a
    #: release blocker; a failure in a candidate is a recorded finding.
    REQUIRED = {"anpr-onnx-cpu@1.0.0", "vehicle-rtdetrv2-r18@0.1.0"}

    print("SAAKSHYA model activation")
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')}\n")

    reports = validate_all(run_inference=not args.no_inference)
    width = max(len(k) for k in reports)

    active = failed = skipped = 0
    for key, rep in sorted(reports.items()):
        d = rep.to_dict()
        mark = {"ACTIVE": "ACTIVE ", "FAILED": "FAILED ",
                "SKIPPED": "SKIPPED"}[d["status"]]
        required = " *" if key in REQUIRED else "  "
        print(f"  {key:{width}}{required} {mark} {d.get('device') or '':4} "
              f"{(d.get('reason') or '')[:70]}")
        if rep.status is Activation.ACTIVE:
            active += 1
        elif rep.status is Activation.FAILED:
            failed += 1
        else:
            skipped += 1

    broken_required = [k for k in REQUIRED
                       if k in reports and not reports[k].ok
                       and reports[k].status is not Activation.SKIPPED]

    print()
    for key, rep in sorted(reports.items()):
        if rep.status is not Activation.FAILED:
            continue
        f = rep.first_failure()
        print(f"── {key} ──")
        print(f"   failed at {f.name if f else '?'}")
        for line in (f.detail if f else "").splitlines()[:4]:
            print(f"   {line[:150]}")
        print()

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "required": sorted(REQUIRED),
        "active": active, "failed": failed, "skipped": skipped,
        "required_broken": broken_required,
        "models": {k: r.to_dict() for k, r in reports.items()},
    }, indent=2))

    print(f"{active} active · {failed} failed · {skipped} skipped")
    if broken_required:
        print(f"\nBLOCKER: the pipeline depends on {broken_required} and "
              "they are not ACTIVE.")
        return 1
    if failed:
        print("\nThe failures above are registry candidates, not pipeline "
              "dependencies. Each blocker is recorded in the registry entry's "
              "notes rather than the model being quietly removed.")
    print(f"written: {display(args.json, ROOT)}")
    return 1 if (args.strict and failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
