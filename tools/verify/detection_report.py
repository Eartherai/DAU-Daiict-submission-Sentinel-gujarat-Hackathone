"""The output report the submission requires: what was detected, and when.

Q33 of the challenge FAQ asks for "an output report showing detected vehicles or
number plates with corresponding timestamps" alongside the government-feed
demonstration. This produces it from the live store, in CSV and Markdown.

It reports **vehicles** as well as plates deliberately. On this estate most
cameras are graded UNSUITABLE for ANPR — plate width at these mountings is
40-something pixels — so a report of plates alone would show a handful of rows
and imply the system saw almost nothing. It saw thousands of vehicles; what it
could not do on most cameras is read their registration marks, and the report
says which is which rather than letting a reader infer the wrong one.

The CSV is the full store unless ``--limit`` is set. A default of 20,000 used
to silently export a slice while the summary claimed that slice was the estate.

    python tools/verify/detection_report.py --db sqlite:///var/live.db \
        --out var/reports/detections
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import and_, func, select

from saakshya.capability import TimeBand
from saakshya.common.paths import display
from saakshya.store import Store
from saakshya.store import schema as S

COLUMNS = [
    "timestamp_utc", "camera_id", "camera_name", "district", "department",
    "latitude", "longitude", "object_type", "colour", "registration_mark",
    "plate_confidence", "plate_votes", "observation_quality", "time_band",
    "observation_id", "evidence_id", "models",
]


#: Luminance thresholds the capability grader uses to band an observation.
#: Kept here rather than imported so the report says plainly what it derived.
def _band(luma: float | None) -> str:
    if luma is None:
        return ""
    v = luma * 255.0 if luma <= 1.0 else luma
    return "NIGHT" if v < 40 else "LOW_LIGHT" if v < 90 else "DAY"


def _iso(us: int | None) -> str | None:
    if not us:
        return None
    return datetime.fromtimestamp(us / 1e6, tz=UTC).isoformat(timespec="milliseconds")


def _has_mark():
    return and_(S.observations.c.plate.isnot(None), S.observations.c.plate != "")


def _row(o: dict[str, Any], cam: dict[str, Any]) -> dict[str, Any]:
    models = o.get("model_versions")
    if isinstance(models, str):
        try:
            models = json.loads(models)
        except ValueError:
            models = {}
    return {
        "timestamp_utc": _iso(o.get("t_norm_us") or 0) or "",
        "camera_id": o["camera_id"],
        "camera_name": cam.get("name") or "",
        "district": cam.get("district") or "",
        "department": cam.get("department") or "",
        "latitude": cam.get("lat") if cam.get("lat") is not None else "",
        "longitude": cam.get("lon") if cam.get("lon") is not None else "",
        "object_type": o.get("object_type") or "",
        "colour": o.get("colour") or "",
        "registration_mark": o.get("plate") or "",
        "plate_confidence": (f"{o['plate_confidence']:.3f}"
                             if o.get("plate_confidence") is not None else ""),
        "plate_votes": o.get("plate_votes") or "",
        "observation_quality": (f"{o['observation_quality']:.3f}"
                                if o.get("observation_quality") is not None
                                else ""),
        # Derived, not stored: the grader bands by luminance and the
        # observation keeps the luminance. Emitting an always-empty column
        # would look like data the system failed to capture.
        "time_band": _band(o.get("mean_luma") if o.get("mean_luma") is not None
                           else o.get("luminance")),
        "observation_id": o["observation_id"],
        "evidence_id": o.get("evidence_ref") or "",
        "models": (models or {}).get("model", "") if isinstance(models, dict)
                  else "",
    }


def iter_rows(store: Store, *, plates_only: bool, limit: int
              ) -> Iterator[dict[str, Any]]:
    """Yield CSV rows. ``limit`` 0 means the whole store, newest first."""
    cams = {c["camera_id"]: c for c in store.list_cameras()}
    q = select(S.observations).order_by(S.observations.c.t_norm_us.desc())
    if plates_only:
        q = q.where(_has_mark())
    if limit > 0:
        q = q.limit(limit)
    with store.engine.connect() as c:
        result = c.execution_options(yield_per=500).execute(q)
        for r in result:
            yield _row(dict(r._mapping), cams.get(r.camera_id, {}))


def rows(store: Store, *, plates_only: bool, limit: int) -> list[dict[str, Any]]:
    return list(iter_rows(store, plates_only=plates_only, limit=limit))


def summarise(store: Store) -> dict[str, Any]:
    """Counts from the store, not from a truncated export.

    The CSV may be a sample. The summary is the estate. Mixing the two is how
    a 20,000-row default used to be quoted as the whole live store.
    """
    with store.engine.connect() as c:
        n = c.execute(select(func.count()).select_from(S.observations)).scalar_one()
        plated_n = c.execute(
            select(func.count()).select_from(S.observations).where(_has_mark())
        ).scalar_one()
        marks = [r[0] for r in c.execute(
            select(S.observations.c.plate).where(_has_mark())
            .distinct().order_by(S.observations.c.plate)) if r[0]]
        by_cam = [(cid, int(cnt)) for cid, cnt in c.execute(
            select(S.observations.c.camera_id, func.count())
            .group_by(S.observations.c.camera_id)
            .order_by(func.count().desc()))]
        by_type = [(t or "", int(cnt)) for t, cnt in c.execute(
            select(S.observations.c.object_type, func.count())
            .group_by(S.observations.c.object_type)
            .order_by(func.count().desc()))]
        first_us, last_us = c.execute(select(
            func.min(S.observations.c.t_norm_us),
            func.max(S.observations.c.t_norm_us))).one()

    # `list_capability()` is one row per camera per time band. The ALL band is
    # the whole-day grade; collapsing later bands overwrote UNSUITABLE with
    # NIGHT UNKNOWN and the report listed five cameras of twenty-eight.
    grades = {r["camera_id"]: str(r.get("anpr_grade"))
              for r in store.list_capability(time_band=str(TimeBand.ALL))}
    if not grades:
        grades = {r["camera_id"]: str(r.get("anpr_grade"))
                  for r in store.list_capability()}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "detections": int(n),
        "with_registration_mark": int(plated_n),
        "distinct_marks": marks,
        "cameras_contributing": len(by_cam),
        "by_camera": by_cam,
        "by_object_type": by_type,
        "anpr_unsuitable_cameras": sorted(
            cam for cam, g in grades.items() if g == "UNSUITABLE"),
        "first": _iso(first_us),
        "last": _iso(last_us),
    }


def mark_rows(store: Store) -> list[dict[str, Any]]:
    """One row per mark per camera. Looping reads of the same plate collapse."""
    cams = {c["camera_id"]: c for c in store.list_cameras()}
    q = (
        select(
            S.observations.c.plate,
            S.observations.c.camera_id,
            func.count().label("hits"),
            func.max(S.observations.c.t_norm_us).label("last_us"),
            func.max(S.observations.c.plate_votes).label("votes"),
            func.max(S.observations.c.plate_confidence).label("confidence"),
        )
        .where(_has_mark())
        .group_by(S.observations.c.plate, S.observations.c.camera_id)
        .order_by(S.observations.c.plate, S.observations.c.camera_id)
    )
    out = []
    with store.engine.connect() as c:
        for r in c.execute(q):
            cam = cams.get(r.camera_id, {})
            out.append({
                "registration_mark": r.plate,
                "camera_id": r.camera_id,
                "camera_name": cam.get("name") or "",
                "district": cam.get("district") or "",
                "hits": int(r.hits),
                "timestamp_utc": _iso(r.last_us) or "",
                "plate_votes": r.votes or "",
                "plate_confidence": (f"{r.confidence:.3f}"
                                     if r.confidence is not None else ""),
            })
    return out


def markdown(summary: dict[str, Any], marks: list[dict[str, Any]],
             sample: list[dict[str, Any]], sample_n: int) -> str:
    lines = [
        "# Detection output report",
        "",
        "Produced from the live Gujarat government feed by "
        "`tools/verify/detection_report.py`. Every row is an observation this "
        "system recorded; none is illustrative.",
        "",
        f"- **{summary['detections']:,} detections** across "
        f"**{summary['cameras_contributing']} cameras**",
        f"- **{summary['with_registration_mark']} carry a registration mark** "
        f"({len(summary['distinct_marks'])} distinct)",
        f"- Window: {summary['first']} to {summary['last']}",
    ]
    if summary.get("export_truncated"):
        lines.append(
            f"- CSV export is a sample of **{summary['exported']:,}** rows; "
            "the counts above are the full store.")
    if summary.get("csv_skipped"):
        lines.append(
            "- CSV was not rewritten this run; counts are SQL over the whole "
            "store. The dated CSV beside this file is an earlier snapshot.")
    lines += [
        "",
        "## What was detected",
        "",
    ]
    for t, n in summary["by_object_type"]:
        lines.append(f"- **{n:,}** {t or 'untyped'}")
    lines += [
        "",
        "People are counted separately from vehicles. They are never given a "
        "registration mark. Dwell is recorded; the word *intrusion* is not — "
        "that is a judgement about permission this system cannot make.",
        "",
        "## Why so few registration marks",
        "",
        "Most cameras on this estate are graded **UNSUITABLE** for plate "
        "reading, measured from their own streams rather than assumed: at these "
        "mountings a plate is around forty pixels wide. The system therefore "
        "reports thousands of *vehicles* and few *marks*, and grades each "
        "camera so an investigator knows before relying on it which question it "
        "can answer.",
        "",
        f"Cameras graded UNSUITABLE for ANPR: "
        f"{', '.join(summary['anpr_unsuitable_cameras']) or 'none'}.",
        "",
    ]
    if marks:
        lines += [
            "## Registration marks read",
            "",
            "One row per mark per camera. Repeated reads of the same plate on "
            "a looping camera are counted in **Hits**, not listed as a fleet.",
            "",
            "| Last seen (UTC) | Camera | Location | Mark | Hits | Votes | "
            "Confidence |",
            "|---|---|---|---|---|---|---|",
        ]
        for d in marks:
            lines.append(
                f"| {d['timestamp_utc']} | {d['camera_id']} "
                f"{d['camera_name']} | {d['district'] or '—'} | "
                f"**{d['registration_mark']}** | {d['hits']} | "
                f"{d['plate_votes'] or '—'} | {d['plate_confidence'] or '—'} |")
        lines.append("")

    lines += ["## Vehicles detected, by camera", "",
              "| Camera | Detections |", "|---|---|"]
    lines += [f"| {c} | {n:,} |" for c, n in summary["by_camera"][:20]]
    lines.append("")
    if summary["by_object_type"]:
        lines += ["## By object type", "", "| Type | Count |", "|---|---|"]
        lines += [f"| {t} | {n:,} |" for t, n in summary["by_object_type"]]
        lines.append("")

    shown = sample[:sample_n]
    csv_note = (
        "The full set is in an accompanying CSV from an earlier export; this "
        "run refreshed counts from SQL without rewriting it."
        if summary.get("csv_skipped") else
        "The full set is in the accompanying CSV.")
    lines += [f"## Sample of {len(shown)} detections", "",
              csv_note, "",
              "| Timestamp (UTC) | Camera | Type | Colour | Mark | Quality |",
              "|---|---|---|---|---|---|"]
    for d in shown:
        lines.append(
            f"| {d['timestamp_utc']} | {d['camera_id']} | "
            f"{d['object_type'] or '—'} | {d['colour'] or '—'} | "
            f"{d['registration_mark'] or '—'} | {d['observation_quality']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=f"sqlite:///{ROOT}/var/live.db")
    ap.add_argument("--out", type=Path, default=ROOT / "var" / "reports" / "detections")
    ap.add_argument("--limit", type=int, default=0,
                    help="Max CSV rows; 0 (default) writes every observation")
    ap.add_argument("--summary-only", action="store_true",
                    help="Refresh Markdown/JSON from SQL; leave the CSV alone")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--plates-only", action="store_true")
    a = ap.parse_args()

    store = Store(a.db)
    store.create_all()
    # A full-store scan must wait out ingest WAL writes rather than fail at 5 s.
    if store.is_sqlite:
        with store.engine.begin() as c:
            c.exec_driver_sql("PRAGMA busy_timeout=60000")
    summary = summarise(store)
    if summary["detections"] == 0:
        print("no observations in this store; run an ingest first",
              file=sys.stderr)
        return 1

    a.out.mkdir(parents=True, exist_ok=True)
    csv_path = a.out / "detections.csv"
    exported = 0
    sample_rows: list[dict[str, Any]] = []
    if a.summary_only:
        # Counts come from SQL over the whole store. Do not rewrite a 60 MB
        # CSV while live ingest is holding the same database.
        sample_rows = list(iter_rows(
            store, plates_only=a.plates_only, limit=max(a.sample, 1)))
        summary["exported"] = 0
        summary["export_truncated"] = False
        summary["csv_skipped"] = True
    else:
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for row in iter_rows(store, plates_only=a.plates_only, limit=a.limit):
                w.writerow(row)
                exported += 1
                if len(sample_rows) < a.sample:
                    sample_rows.append(row)
        summary["exported"] = exported
        summary["export_truncated"] = bool(a.limit) and exported < summary["detections"]
        summary["csv_skipped"] = False
    marks = mark_rows(store)

    (a.out / "detections.md").write_text(
        markdown(summary, marks, sample_rows, a.sample))
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"{summary['detections']:,} detections across "
          f"{summary['cameras_contributing']} cameras, "
          f"{summary['with_registration_mark']} with a registration mark "
          f"({len(summary['distinct_marks'])} distinct)")
    if summary["export_truncated"]:
        print(f"CSV is a sample of {exported:,} rows")
    if summary["distinct_marks"]:
        print(f"marks: {', '.join(summary['distinct_marks'])}")
    print(f"window: {summary['first']} to {summary['last']}")
    written = [a.out / "detections.md", a.out / "summary.json"]
    if not a.summary_only:
        written.insert(0, csv_path)
    for p in written:
        print(f"written: {display(p, ROOT)}")
    if a.summary_only:
        print("CSV left in place (--summary-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
