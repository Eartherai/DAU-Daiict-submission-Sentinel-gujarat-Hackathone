"""Render 1.mp4 from the own-estate street clip with live SAAKSHYA detections.

The participant clip is 22 s of real street CCTV (same content as the 360p
export). We decode the 720p copy already in var/media so plates have enough
pixels, run the same CameraPipeline as the government grid, and encode 1080p.

    python tools/demo/render_own_street.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from saakshya.analytics.pipeline import PipelineConfig  # noqa: E402

from render_demo_video import (  # noqa: E402
    FfmpegWriter, RealtimePacer, card, hold_card, run_file, write_report,
)
from saakshya.common.paths import display  # noqa: E402

SRC_720 = ROOT / "var/media/OWN-STREET.mp4"
SRC_360 = Path.home() / ".Trash/test_video.mp4"
OUT = ROOT / "var/demo/own_street_overlay"


def main() -> int:
    src = SRC_720 if SRC_720.is_file() else SRC_360
    if not src.is_file():
        print(f"missing source {src}", file=sys.stderr)
        return 2
    cfg = PipelineConfig()
    cfg.validate_models = True
    cfg.enable_vehicle_detector = True
    cfg.enable_person_detector = True
    cfg.enable_motion = False
    cfg.vehicle_conf = 0.40
    cfg.person_conf = 0.55
    cfg.min_track_hits = 2
    cfg.anpr.enable_single_read_leads = False
    cfg.anpr.min_votes = 2
    cfg.anpr.min_confidence = 0.55

    cam = {
        "camera_id": "OWN-STREET",
        "name": "Own street camera",
        "district": "Ahmedabad",
        "department": "Own estate",
        "cluster": "own recording",
        "cluster_basis": "LOCAL",
        "provenance": "OWN RECORDING · NOT GOVERNMENT DATA",
    }
    out = OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = FfmpegWriter(out.with_suffix(".mp4"))
    rows = []
    print(f"source {display(src)} → {display(out)}.mp4")
    try:
        hold_card(writer, card(
            [("FOOTAGE", "Own-estate street CCTV. 22 seconds. Not the\n"
                          "government grid. Not the synthetic corpus."),
             ("WHAT YOU WILL SEE", "Vehicles, two-wheelers, persons on the\n"
                                   "road. A white chip only for a corroborated\n"
                                   "registration mark — not a single OCR guess."),
             ("SOLID BOX", "track confirmed"),
             ("DASHED BOX", "tentative — seen, not yet confirmed"),
             ("WHITE CHIP", "registration mark + confidence"),
             ("PLATFORM", "The same detector, tracker and ANPR the live\n"
                          "grid runs. There is no demonstration path.")],
            "Own-feed demonstration",
            "Street recording processed by SAAKSHYA end to end."), 3.0)
        pacer = RealtimePacer(writer)
        _, run = run_file(src, cam, 30.0, rows, pacer, cfg=cfg,
                          tidy=True, peek_plates=False)
        pacer.flush(0.4)
        on_screen = sorted({(r.plate or "").replace(" ", "") for r in rows if r.plate})
        run.plates = set(on_screen)
        print(f"  {run.frames} frames  {len(run.tracks)} tracks  "
              f"{len(run.plates)} marks  {run.analysis_fps:.1f} fps")
        plates = on_screen
        marks = (", ".join(plates[:6]) if plates
                 else "none — OCR did not corroborate a mark on-screen")
        hold_card(writer, card(
            [("CAMERA", "OWN-STREET · own estate · Ahmedabad"),
             ("FRAMES", f"{run.frames} analysed from the recording"),
             ("TRACKS FORMED", f"{len(run.tracks)} — identities, not unique objects"),
             ("MARKS ON SCREEN", f"{len(plates)} distinct — {marks}"),
             ("REPORT", "03_own_feed.csv — every box drawn, with timestamps")],
            "What this run measured",
            "Own recording · not government data"), 3.5)
    finally:
        writer.close()

    from datetime import UTC, datetime
    write_report(out, rows, [run], datetime.now(UTC),
                 "OWN-STREET recording — not government data", 30.0, writer.n)

    mp4 = out.with_suffix(".mp4")
    dests = [
        ROOT.parent / "1.mp4",
        ROOT / "var/demo/1.mp4",
        ROOT / "var/demo/PORTAL_PACK/03_own_feed.mp4",
    ]
    for d in dests:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mp4, d)
        print(f"copied {display(d)}")
    pack = ROOT / "var/demo/PORTAL_PACK"
    shutil.copy2(out.with_suffix(".csv"), pack / "03_own_feed.csv")
    shutil.copy2(out.with_suffix(".json"), pack / "03_own_feed.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
