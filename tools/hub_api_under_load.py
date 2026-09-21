#!/usr/bin/env python3
"""Measure critical APIs while the 30-camera hub is ingesting. No secrets."""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("SAAKSHYA_BASE", "http://127.0.0.1:8080")
TOKEN = Path("/tmp/saakshya-demo-token.raw")
PATHS = [
    "/healthz",
    "/readyz",
    "/system/health",
    "/audit?limit=20",
    "/search?plate=GJ01TA0001",
    "/alerts?limit=20",
    "/command/summary",
]


def _req(path: str) -> tuple[int, float, int]:
    headers = {}
    if TOKEN.is_file() and path not in {"/healthz", "/readyz"}:
        headers["Authorization"] = f"Bearer {TOKEN.read_text().strip()}"
        headers["X-Case-Id"] = "FIR-214/2026"
        headers["X-Purpose"] = "api under hub load"
    req = urllib.request.Request(BASE + path, headers=headers)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read()
            return r.status, (time.perf_counter() - t0) * 1000, len(body)
    except urllib.error.HTTPError as exc:
        return exc.code, (time.perf_counter() - t0) * 1000, 0


def main() -> int:
    rows = {}
    for path in PATHS:
        samples = []
        code = None
        for _ in range(5):
            code, ms, _n = _req(path)
            samples.append(ms)
        rows[path] = {
            "http": code,
            "p50_ms": round(statistics.median(samples), 1),
            "p95_ms": round(sorted(samples)[max(0, int(0.95 * (len(samples) - 1)))], 1),
            "max_ms": round(max(samples), 1),
            "ok": code in {200, 204},
            "label": "MEASURED_REAL",
        }
        print(f"{path:28} {code} p50={rows[path]['p50_ms']}ms p95={rows[path]['p95_ms']}ms",
              flush=True)
    out = ROOT / "reports/final_live_qa/api_under_hub_load.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2) + "\n")
    print("wrote", out)
    return 0 if all(r["ok"] for r in rows.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
