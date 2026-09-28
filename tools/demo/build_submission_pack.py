#!/usr/bin/env python3
"""Assemble the folder that goes to the portal, from the current artifacts.

The pack used to be built by hand with `cp`, and it drifted the first time a
report was regenerated: the deck was hardlinked and updated itself, while the
markdown beside it still carried the previous run's numbers. A submission whose
own folder disagrees with itself is exactly what evaluation area 7 — "the
completeness, accessibility and consistency of all required documents" — is
looking for.

Everything is hardlinked where the filesystem allows, so a regenerated report
cannot leave a stale copy behind, and the pack costs no extra disk. Files are
numbered in the order the portal asks for them.

    python tools/demo/build_submission_pack.py

It refuses rather than shipping a gap: a missing required artifact is named and
the exit status is non-zero, because a pack that is quietly missing the
government-feed report is worse than no pack.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: (published name, source, required). Order is the portal's order.
ITEMS: list[tuple[str, str, bool]] = [
    ("00_SUBMISSION_INDEX.md", "docs/FINAL_SUBMISSION.md", True),
    ("00_CHECKLIST.md", "docs/SUBMISSION_CHECKLIST.md", True),
    ("01_SAAKSHYA_deck.pptx", "var/demo/SAAKSHYA_deck.pptx", True),
    ("01_SAAKSHYA_deck.pdf", "var/demo/SAAKSHYA_deck.pdf", True),
    ("02_HLD.md", "docs/HLD.md", True),
    ("02_HLD_diagrams.pdf", "var/demo/diagrams/HLD_diagrams.pdf", False),
    ("02_SECURITY.md", "docs/SECURITY.md", False),
    ("02_STATEWIDE_ARCHITECTURE.md", "docs/STATEWIDE_ARCHITECTURE.md", True),
    ("03_own_feed.mp4", "var/demo/own_feed.mp4", True),
    ("04_government_feed.mp4", "var/demo/government_feed.mp4", True),
    ("04_government_feed_1080p.mp4", "var/demo/government_feed_1080.mp4", False),
    ("04_government_feed_anpr_report.csv",
     "var/demo/government_feed_anpr_report.csv", True),
    ("05_MODEL1_GAP_ANALYSIS.md", "reports/MODEL1_GAP_ANALYSIS.md", True),
    ("05_REGISTRY_API.md", "reports/REGISTRY_API.md", True),
    ("05_sample_camera_metadata.csv", "reports/sample_camera_metadata.csv", True),
    ("05_SCALE_80K_LOAD_TEST.md", "reports/SCALE_80K_LOAD_TEST.md", True),
    ("05_ADAPTERS.md", "docs/ADAPTERS.md", True),
    ("05_FEDERATED_ANALYTICS_REPORT.md", "reports/FEDERATED_ANALYTICS_REPORT.md", True),
    # The test case's expected output is "the complete route traversed by the
    # designated vehicle, with a timestamped and location-wise movement
    # history". This is that, as the platform prints it, for the designated
    # vehicle the government film traces.
    ("06_designated_vehicle_trace_report.html", "var/demo/designated_vehicle_trace.html", False),
    ("06_own_feed_trace_report.html", "var/demo/own_feed_trace.html", False),
]


def _probe(mp4: Path) -> str:
    if not shutil.which("ffprobe"):
        return ""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(mp4)],
        capture_output=True, text=True).stdout.split()
    if len(out) < 3:
        return ""
    w, h, dur = out[0], out[1], float(out[2])
    return f"{int(dur)//60}m{int(dur) % 60:02d}s · {w}x{h}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="var/demo/SUBMIT")
    a = ap.parse_args()

    dest = ROOT / a.out
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.iterdir():
        if stale.is_file():
            stale.unlink()

    missing: list[str] = []
    total = 0
    print(f"building {dest.relative_to(ROOT)}\n")
    for name, rel, required in ITEMS:
        src = ROOT / rel
        if not src.exists():
            if required:
                missing.append(f"{name}  <- {rel}")
            else:
                print(f"  --  {name:38} (optional, absent)")
            continue
        target = dest / name
        try:
            os.link(src, target)
            how = "link"
        except OSError:
            shutil.copy2(src, target)
            how = "copy"
        size = target.stat().st_size
        total += size
        extra = _probe(target) if name.endswith(".mp4") else ""
        print(f"  {how}  {name:38} {size/1048576:7.1f} MB  {extra}")

    print(f"\n{total/1048576:.1f} MB total")
    if missing:
        print("\nREFUSED — required artifacts are missing:")
        for m in missing:
            print(f"  {m}")
        print("\nA pack quietly missing one of these is worse than no pack.")
        return 1
    print("complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
