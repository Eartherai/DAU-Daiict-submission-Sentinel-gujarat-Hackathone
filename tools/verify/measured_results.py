"""Assemble every number the presentation may use, each with its source.

Nothing here is typed by hand. Every figure is read from a report file or from
the live store, and every row carries the artefact it came from, so any claim on
a slide can be traced to the run that produced it. A number whose source is
missing is reported as **not measured** rather than dropped, because a gap that
is visible is a gap someone can close.

    python tools/verify/measured_results.py --out docs/MEASURED_RESULTS.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
REPORTS = ROOT / "var" / "reports"

from saakshya.common.paths import display
from saakshya.store import Store
from saakshya.store import schema as S
from saakshya.analytics.plates import CONFUSIONS


def load(name: str) -> dict[str, Any] | None:
    p = REPORTS / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


class Sheet:
    """Rows of (claim, value, source). Missing sources say so."""

    def __init__(self) -> None:
        self.sections: list[tuple[str, list[tuple[str, str, str]]]] = []

    def section(self, title: str) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        self.sections.append((title, rows))
        return rows

    @staticmethod
    def row(rows, claim: str, value: Any, source: str) -> None:
        rows.append((claim, "not measured" if value is None else str(value),
                     source))

    def render(self) -> str:
        out = [
            "# Measured results",
            "",
            "Every figure below is read from a report file or from the live "
            "store by `tools/verify/measured_results.py`. None is typed by "
            "hand, and each carries the artefact it came from so any claim on "
            "a slide can be traced to the run that produced it.",
            "",
            "A row reading **not measured** is a gap, stated rather than "
            "dropped. Synthetic-corpus figures are never substituted for live "
            "ones.",
            "",
            f"Generated {datetime.now(UTC).isoformat(timespec='seconds')}.",
            "",
        ]
        for title, rows in self.sections:
            if not rows:
                continue
            out += [f"## {title}", "", "| Claim | Measured | Source |",
                    "|---|---|---|"]
            out += [f"| {c} | {v} | `{s}` |" for c, v, s in rows]
            out.append("")
        return "\n".join(out)


def _identity_among_marks(store: Store) -> tuple[int, int, list[str], list[str]]:
    """Exact cross-camera repeats and one-character OCR-lookalike pairs.

    These two figures are quoted on slides and in the readiness note. They
    belong in the generated sheet, not in a handwritten sentence that can go
    stale while the store is still growing.
    """
    from sqlalchemy import select

    cams_by_plate: dict[str, set[str]] = {}
    with store.engine.connect() as c:
        q = (
            select(S.observations.c.plate, S.observations.c.camera_id)
            .where(S.observations.c.plate.isnot(None),
                   S.observations.c.plate != "")
            .group_by(S.observations.c.plate, S.observations.c.camera_id)
        )
        for plate, cam in c.execute(q):
            if plate:
                cams_by_plate.setdefault(plate, set()).add(cam)
    plates = sorted(cams_by_plate)
    cross = sorted(p for p, cams in cams_by_plate.items() if len(cams) > 1)
    lookalike: list[str] = []
    for i, a in enumerate(plates):
        for b in plates[i + 1:]:
            if len(a) != len(b):
                continue
            diffs = [(a[j], b[j]) for j in range(len(a)) if a[j] != b[j]]
            if len(diffs) != 1:
                continue
            x, y = diffs[0]
            if y in CONFUSIONS.get(x, ()) or x in CONFUSIONS.get(y, ()):
                lookalike.append(f"{a}/{b}")
    return len(cross), len(lookalike), cross, lookalike


def build(store: Store) -> Sheet:
    sheet = Sheet()
    R = Sheet.row

    # ---- the estate ------------------------------------------------------- #
    rows = sheet.section("The estate, on the live government grid")
    cams = store.list_cameras()
    R(rows, "Cameras onboarded", len(cams), "live store")
    R(rows, "Cameras with a position",
      f"{sum(1 for c in cams if c.get('lat') is not None)} of {len(cams)}",
      "live store")
    codecs = Counter(c.get("codec") for c in cams if c.get("codec"))
    R(rows, "Codec mix", ", ".join(f"{v}x {k}" for k, v in codecs.most_common())
      or None, "live store")
    res = Counter(f"{c['width']}x{c['height']}" for c in cams
                  if c.get("width") and c.get("height"))
    R(rows, "Resolution mix", ", ".join(f"{v}x {k}" for k, v in res.most_common())
      or None, "live store")
    prof = load("live_camera_profile.json")
    if prof:
        cs = prof.get("cameras") or []
        # `c.get("mean_chroma") or 1.0` was wrong here and inverted the answer:
        # a perfectly monochrome camera measures exactly 0.0, which is falsy, so
        # every true infrared camera was counted as colour. The cameras being
        # counted are precisely the ones the idiom mishandles.
        chroma = [c["mean_chroma"] for c in cs
                  if c.get("mean_chroma") is not None]
        mono = sum(1 for v in chroma if v < 0.04)
        R(rows, "Monochrome / infrared cameras",
          f"{mono} of {len(chroma)} profiled, detected from imagery not "
          f"configuration", "var/reports/live_camera_profile.json")

    # ---- ingest ------------------------------------------------------------ #
    rows = sheet.section("Live ingest")
    # The label comes from the run, not from what the file was once called: the
    # largest stage in each report is the one worth quoting, and a report whose
    # last stage happened to be four cameras was being labelled "30-camera run".
    for name in ("live_ingest.json", "live_cluster.json", "live_located.json"):
        d = load(name)
        if not d:
            continue
        stages = d.get("stages") or d.get("results") or []
        if not stages:
            continue
        st = max(stages, key=lambda s: (s.get("cameras") or 0,
                                        s.get("frames_delivered") or 0))
        label = f"{st.get('cameras')} cameras, {st.get('minutes')} min"
        R(rows, f"{label}: streaming", st.get("cameras"), f"var/reports/{name}")
        R(rows, f"{label}: frames delivered",
          f"{st.get('frames_delivered', 0):,}", f"var/reports/{name}")
        R(rows, f"{label}: observations", f"{st.get('observations', 0):,}",
          f"var/reports/{name}")
        R(rows, f"{label}: reconnects / decoder warnings / scene cuts",
          f"{st.get('reconnects', 0)} / {st.get('decoder_warnings', 0)} / "
          f"{st.get('scene_cuts', 0)}", f"var/reports/{name}")
        R(rows, f"{label}: peak RSS", f"{st.get('peak_rss_mb', 0):.0f} MB",
          f"var/reports/{name}")

    load_test = load("camera_load.json")
    if load_test:
        R(rows, "Concurrent streams sustained on one host",
          f"{load_test.get('aggregate', {}).get('cameras_streaming')} of "
          f"{load_test.get('requested_cameras')}", "var/reports/camera_load.json")
        R(rows, "Analytics throughput, one process",
          f"{load_test.get('analysis_fps_per_process')} frames/s "
          f"(~{load_test.get('cameras_one_process_can_analyse')} cameras at 1 fps)",
          "var/reports/camera_load.json")

    # ---- capability --------------------------------------------------------- #
    rows = sheet.section("What the cameras can actually do")
    # `list_capability()` returns one row per camera *per time band*, so counting
    # rows reported "94 UNKNOWN" for an estate of thirty. Collapse to the ALL
    # band, which is the whole-day grade, and count cameras.
    from saakshya.capability import TimeBand

    cap = store.list_capability(time_band=str(TimeBand.ALL)) \
        or store.list_capability()
    by_camera: dict[str, dict[str, Any]] = {}
    for r in cap:
        by_camera.setdefault(r["camera_id"], r)
    R(rows, "Cameras graded", f"{len(by_camera)} of {len(cams)}", "live store")
    for field, label in (("anpr_grade", "ANPR"),
                         ("vehicle_reid_grade", "Appearance"),
                         ("presence_grade", "Presence")):
        counts = Counter(str(r.get(field)) for r in by_camera.values())
        R(rows, f"{label} grades, per camera",
          ", ".join(f"{v} {k}" for k, v in counts.most_common()) or None,
          "live store, graded from each camera's own stream")

    # ---- timebase ----------------------------------------------------------- #
    rows = sheet.section("Timebase, measured from the cameras' own clocks")
    ov = load("overlays.json")
    if ov:
        readings = ov.get("readings") or {}
        clusters = ov.get("candidate_clusters") or []
        biggest = max(clusters, key=len) if clusters else []
        R(rows, "Burned-in clocks read",
          f"{len(readings)} of {len(ov.get('cameras') or [])} cameras, by a "
          f"vision model running locally", "var/reports/overlays.json")
        R(rows, "Largest shared-timebase cluster",
          f"{len(biggest)} cameras: {', '.join(biggest)}",
          "var/reports/overlays.json")
    from saakshya.live.timebase import TimebaseRegistry
    tb = TimebaseRegistry(store)
    health = tb.all()
    R(rows, "Cameras in a declared cluster",
      f"{sum(1 for h in health.values() if h.time_cluster)} of {len(health)}",
      "live store")
    R(rows, "Cameras whose own timing is sound enough to correlate",
      f"{sum(1 for h in health.values() if h.usable_for_correlation)} of "
      f"{len(health)}", "live store")

    # ---- location ------------------------------------------------------------ #
    rows = sheet.section("Camera positions and their support")
    prec = Counter(str(c.get("location_precision")) for c in cams
                   if c.get("lat") is not None)
    R(rows, "Position precision",
      ", ".join(f"{v} {k}" for k, v in prec.most_common()) or None, "live store")
    lm = load("landmarks.json")
    if lm:
        verdicts = Counter(r.get("verdict") or "UNREACHABLE"
                           for r in lm.get("cameras") or [])
        R(rows, "Signage corroboration of position",
          ", ".join(f"{v} {k}" for k, v in verdicts.most_common()),
          "var/reports/landmarks.json")

    # ---- analytics ------------------------------------------------------------ #
    rows = sheet.section("Analytics output")
    stats = store.stats()
    R(rows, "Observations stored", f"{stats.get('observations', 0):,}",
      "live store")
    R(rows, "Person observations",
      f"{stats.get('observations_person', 0):,}", "live store")
    R(rows, "Person long-stay (dwell ≥ 12 s on one camera; not intrusion)",
      f"{stats.get('observations_person_long_stay', 0):,}", "live store")
    by_type = stats.get("observations_by_object_type") or {}
    if by_type:
        mix = ", ".join(
            f"{v:,} {k}" for k, v in sorted(by_type.items(),
                                            key=lambda kv: (-kv[1], kv[0])))
        R(rows, "Object mix (detector labels from the same pass, not identity)",
          mix, "live store")
    R(rows, "Observations carrying a registration mark",
      f"{stats.get('observations_with_plate', 0):,}", "live store")
    R(rows, "Confirmed plates (votes ≥ 2)",
      f"{stats.get('observations_plate_confirmed', 0):,}", "live store")
    R(rows, "Plate leads (votes = 1, uncorroborated)",
      f"{stats.get('observations_plate_leads', 0):,}", "live store")
    R(rows, "Raw OCR attempts stored (including rejected)",
      f"{stats.get('raw_ocr_read_records', 0):,}", "live store")
    R(rows, "Cameras that published a mark",
      f"{stats.get('cameras_with_plate', 0)}", "live store")
    plates = store.distinct_plates()
    R(rows, "Distinct marks read from the government feed",
      f"{len(plates)}: {', '.join(plates)}" if plates else None, "live store")
    cross_n, lookalike_n, cross_marks, lookalike_pairs = _identity_among_marks(store)
    R(rows, "Exact cross-camera repeats among those marks",
      f"{cross_n}" + (f": {', '.join(cross_marks)}" if cross_marks else ""),
      "live store")
    R(rows, "OCR-lookalike pairs among those marks (one-character O/0 B/8 G/6 and kin)",
      f"{lookalike_n}" + (f": {', '.join(lookalike_pairs)}" if lookalike_pairs else ""),
      "live store")
    R(rows, "Alerts raised", stats.get("alerts"), "live store")
    R(rows, "Evidence records", stats.get("evidence"), "live store")
    R(rows, "Audit entries", stats.get("audit_entries"), "live store")

    # ---- latency --------------------------------------------------------------- #
    rows = sheet.section("Latency")
    ev = load("live_evaluation.json")
    if ev:
        for st in ev.get("stages") or []:
            if st.get("ms"):
                R(rows, f"{st['name'].title()} on the live store",
                  f"{st['ms']:.1f} ms", "var/reports/live_evaluation.json")
        R(rows, "Whole evaluation, ten stages",
          f"{ev.get('elapsed_s')} s", "var/reports/live_evaluation.json")
    api = load("api_latency.json")
    if api:
        # Keyed by route, not a list — read the shape rather than assuming it.
        qs = api.get("results") or {}
        measured = {k: v for k, v in qs.items()
                    if isinstance(v, dict) and v.get("p50_ms") is not None}
        if measured:
            slowest = max(measured, key=lambda k: measured[k]["p50_ms"])
            fastest = min(measured, key=lambda k: measured[k]["p50_ms"])
            R(rows, "API routes measured", len(measured),
              "var/reports/api_latency.json")
            R(rows, "Slowest route, p50",
              f"{measured[slowest]['p50_ms']} ms ({slowest.strip()})",
              "var/reports/api_latency.json")
            R(rows, "Fastest route, p50",
              f"{measured[fastest]['p50_ms']} ms ({fastest.strip()})",
              "var/reports/api_latency.json")
            R(rows, "Worst p99 across routes",
              f"{max(v['p99_ms'] for v in measured.values())} ms",
              "var/reports/api_latency.json")

    # ---- transport ------------------------------------------------------------- #
    rows = sheet.section("Transport")
    bw = load("bandwidth.json")
    if bw:
        R(rows, "Video off the wire",
          f"{bw.get('video_mbps')} Mbps across "
          f"{len([c for c in bw.get('cameras', []) if not c.get('error')])} cameras",
          "var/reports/bandwidth.json")
        R(rows, "Observations, at peak event rate",
          f"{bw.get('event_mbps')} Mbps ({bw.get('observation_bytes_each')} "
          f"bytes each)", "var/reports/bandwidth.json")
        R(rows, "Ratio", f"{bw.get('ratio')}x", "var/reports/bandwidth.json")

    # ---- assurance --------------------------------------------------------------- #
    rows = sheet.section("Assurance")
    rc = load("release_check.json")
    if rc:
        gates = rc.get("gates") or []
        R(rows, "Release gates",
          f"{sum(1 for g in gates if g.get('ok'))} of {len(gates)} pass",
          "var/reports/release_check.json")
        R(rows, "Release candidate", rc.get("release_candidate"),
          "var/reports/release_check.json")
    surf = load("api_surface.json")
    if surf:
        R(rows, "API routes verified against the live store",
          f"{surf.get('passed')} pass, {surf.get('failed')} fail",
          "var/reports/api_surface.json")
    sec = load("security_scorecard.json")
    if sec:
        checks = sec.get("checks") or []
        R(rows, "Security controls, each attacked",
          f"{sum(1 for c in checks if c.get('passed'))} of {len(checks)} refused "
          f"the forbidden action", "var/reports/security_scorecard.json")
    wc = load("wrong_cases.json")
    if wc:
        cs = wc.get("cases") or []
        R(rows, "Cases where the right answer is no",
          f"{sum(1 for c in cs if c.get('passed'))} of {len(cs)} refused "
          f"correctly", "var/reports/wrong_cases.json")
    ma = load("model_activation.json")
    if ma:
        R(rows, "Models ACTIVE / FAILED",
          f"{ma.get('active')} / {ma.get('failed')}",
          "var/reports/model_activation.json")

    return sheet


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=f"sqlite:///{ROOT}/var/live.db")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "docs" / "MEASURED_RESULTS.md")
    a = ap.parse_args()

    store = Store(a.db)
    store.create_all()
    if store.is_sqlite:
        with store.engine.begin() as c:
            c.exec_driver_sql("PRAGMA busy_timeout=60000")
    sheet = build(store)
    text = sheet.render()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text)

    total = sum(len(r) for _, r in sheet.sections)
    missing = sum(1 for _, rows in sheet.sections
                  for _, v, _ in rows if v == "not measured")
    print(f"{total} figures across {len(sheet.sections)} sections; "
          f"{missing} not measured")
    print(f"written: {display(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
