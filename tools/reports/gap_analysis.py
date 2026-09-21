#!/usr/bin/env python3
"""Emit the Model 1 gap-analysis report.

A named deliverable: "Sample gap-analysis report". It is generated from the
live registry rather than written, so it cannot drift from what the platform
actually holds, and re-running it after a department supplies its metadata
shows the gap closing.

    python tools/reports/gap_analysis.py --db sqlite:///var/live.db \
        --out reports/MODEL1_GAP_ANALYSIS.md

The report names absences. That is its purpose: the fields nobody has filled in
are the ones that block onboarding a department, and a registry that lists only
what it holds hides exactly those.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.gis.service import MapService  # noqa: E402
from saakshya.store.repository import Store  # noqa: E402


def _bar(pct: float, width: int = 28) -> str:
    filled = int(round(pct / 100.0 * width))
    return "█" * filled + "·" * (width - filled)


def render(gaps: dict, db_url: str) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    total = gaps["cameras"]
    out: list[str] = []
    w = out.append

    w("# Registry gap analysis")
    w("")
    w(f"Generated {now} from `{db_url}`. Counted across the whole registry in")
    w("SQL; nothing here is sampled or estimated.")
    w("")
    w("A gap is a field no department has supplied yet, not a field the")
    w("platform cannot hold — every column named below exists in the schema and")
    w("is accepted by `POST /registry/cameras/import`.")
    w("")

    w("## Estate")
    w("")
    w("| | |")
    w("|---|---:|")
    w(f"| Cameras onboarded | {total:,} |")
    w(f"| Capacity slots (no stream, not graded) | {gaps['capacity_slots']:,} |")
    w(f"| Cameras with no capability sample | {gaps['ungraded']['count']:,} |")
    w("")

    w("## Departments")
    w("")
    present = gaps.get("departments_present") or {}
    if present:
        w("| Department | Cameras |")
        w("|---|---:|")
        for dept, n in present.items():
            w(f"| {dept} | {n:,} |")
        w("")
    absent = gaps.get("departments_absent") or []
    if absent:
        w(f"**{len(absent)} expected department"
          f"{'' if len(absent) == 1 else 's'} with nothing onboarded:** "
          + ", ".join(absent) + ".")
        w("")
        w("These are coverage gaps, not errors. Each can be onboarded through")
        w("the registry import endpoints.")
    else:
        w("Every expected department has at least one camera onboarded.")
    w("")

    w("## Missing metadata")
    w("")
    rows = [g for g in gaps.get("field_gaps", []) if g["missing"]]
    if not rows:
        w("No registry field is unpopulated.")
    else:
        w("| Field | Missing | Of | Share | |")
        w("|---|---:|---:|---:|---|")
        for g in rows:
            w(f"| `{g['field']}` | {g['missing']:,} | {g['of']:,} | "
              f"{g['pct']}% | `{_bar(g['pct'])}` |")
        w("")
        w("### What each blocks")
        w("")
        blocks = {
            "vms": "which departmental VMS a feed must be integrated through",
            "storage_location": "whether footage sits in cloud or local storage",
            "retention_days": "how long footage survives, which bounds any "
                              "retrospective investigation",
            "vendor": "vendor-specific SDK or ONVIF profile selection",
            "camera_type": "fixed or PTZ, which changes what analytics apply",
            "coordinates": "placement on the GIS map and any spatial query",
            "department": "ownership, and therefore who to ask for access",
        }
        for g in rows:
            why = blocks.get(g["field"])
            if why:
                w(f"- **`{g['field']}`** — {why}.")
        w("")

    w("## Cameras with no capability sample")
    w("")
    n_ungraded = gaps["ungraded"]["count"]
    if n_ungraded:
        ids = ", ".join(f"`{c}`" for c in gaps["ungraded"]["cameras"])
        w(f"{n_ungraded:,} camera{'' if n_ungraded == 1 else 's'} "
          "have never been graded: " + ids)
        if n_ungraded > len(gaps["ungraded"]["cameras"]):
            w(f"…and {n_ungraded - len(gaps['ungraded']['cameras']):,} more.")
        w("")
        w("An ungraded camera is an absence of evidence about that camera, not")
        w("a poor grade. Run a capability sample to replace the unknown with a")
        w("measurement.")
    else:
        w("Every onboarded camera has a capability sample.")
    w("")

    w("---")
    w("")
    w(f"*{gaps['note']}*")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///var/live.db")
    ap.add_argument("--out", default="reports/MODEL1_GAP_ANALYSIS.md")
    a = ap.parse_args()

    store = Store(a.db)
    store.create_all()
    gaps = MapService(store).registry_gaps()
    text = render(gaps, a.db)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    absent = len(gaps.get("departments_absent") or [])
    missing = sum(1 for g in gaps.get("field_gaps", []) if g["missing"])
    print(f"wrote {out} — {gaps['cameras']:,} cameras, "
          f"{missing} field(s) with gaps, {absent} department(s) absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
