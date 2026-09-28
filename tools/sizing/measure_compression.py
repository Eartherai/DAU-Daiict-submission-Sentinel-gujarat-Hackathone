#!/usr/bin/env python3
"""Measure wire size and batch compressibility of real observation rows.

Read-only against the government store (opened with ``mode=ro``). Serialises
rows the way ``var/reports/bandwidth.json`` describes (every column, compact
JSON), then compresses batches with zlib and lzma (stdlib) to bound what a
batched, compressed metadata lane would carry. The planning figure in
``docs/STATEWIDE_ARCHITECTURE.md`` is ``batches.100.zlib6_bytes_per_row``.

    python tools/sizing/measure_compression.py [--db var/live.db] [--rows 20000]

Writes ``reports/measure_compression.json``. The store is gitignored; pass
``--db`` to point at another checkout's ``var/live.db``.
"""
from __future__ import annotations

import argparse
import json
import lzma
import sqlite3
import statistics
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/measure_compression.json"
# Last observation of the verified government snapshot (1,155,325 rows on
# cam01-cam30, 2 Sep 06:54 - 24 Sep 16:10 IST). Pinned so the store growing
# afterwards does not move the planning figure.
UNTIL_US = 1_790_246_409_848_994


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "var/live.db")
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--until-us", type=int, default=UNTIL_US,
                    help="newest t_norm_us to include (default: the verified snapshot)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    db = args.db.resolve()
    if not db.is_file():
        raise SystemExit(f"store not found: {db}")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM observations WHERE camera_id BETWEEN 'cam01' AND 'cam30' "
        "AND t_norm_us <= ? ORDER BY t_norm_us DESC LIMIT ?",
        (args.until_us, args.rows)).fetchall()
    c.close()
    docs = [json.dumps(dict(r), separators=(",", ":"), default=str).encode() for r in rows]
    sizes = [len(d) for d in docs]
    res = {"source": "var/live.db (government store, opened read-only)",
           "rows": len(docs), "until_t_norm_us": args.until_us,
           "order": "most recent by t_norm_us up to until_t_norm_us",
           "serialisation": "compact JSON of every observations column",
           "json_bytes_mean": round(statistics.mean(sizes), 1),
           "json_bytes_p95": sorted(sizes)[int(0.95 * len(sizes))],
           "batches": {}}
    for batch in (100, 1000, 5000):
        raw = comp_z = comp_x = 0
        t0 = time.perf_counter()
        for i in range(0, len(docs), batch):
            blob = b"\n".join(docs[i:i + batch])
            raw += len(blob)
            comp_z += len(zlib.compress(blob, 6))
        tz = time.perf_counter() - t0
        for i in range(0, len(docs), batch):
            comp_x += len(lzma.compress(b"\n".join(docs[i:i + batch]), preset=6))
        res["batches"][str(batch)] = {
            "raw_bytes": raw, "zlib6_bytes": comp_z, "lzma6_bytes": comp_x,
            "zlib6_ratio": round(raw / comp_z, 2), "lzma6_ratio": round(raw / comp_x, 2),
            "zlib6_bytes_per_row": round(comp_z / len(docs), 1),
            "lzma6_bytes_per_row": round(comp_x / len(docs), 1),
            "zlib6_rows_per_s_one_core": round(len(docs) / tz)}
    res["note"] = ("Measured on the development Mac; stdlib codecs only (zstd/Parquet not "
                   "measured). rows_per_s varies run to run; byte counts are deterministic "
                   "for a given store.")
    args.out.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
