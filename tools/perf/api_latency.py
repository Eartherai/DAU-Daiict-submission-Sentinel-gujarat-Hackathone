#!/usr/bin/env python3
"""Measure API latency per endpoint: p50, p95, p99.

In-process against the real application, so the numbers exclude network and
include everything else — routing, authentication, authorisation, the service
layer and the database. That is the honest boundary for "how fast is the
system", because network latency belongs to the deployment and the rest belongs
to us.

Every number this prints is MEASURED on the store it was pointed at, and the
output states the row counts so a figure is never quoted without the scale it
was taken at.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient

from saakshya.api.app import create_app
from saakshya.api.deps import AppState
from saakshya.common.paths import display
from saakshya.security import Role, TokenService


def percentiles(samples: list[float]) -> dict[str, float]:
    s = sorted(samples)

    def p(q: float) -> float:
        k = max(0, min(len(s) - 1, round(q / 100 * len(s) + 0.5) - 1))
        return round(s[k] * 1000, 2)

    return {"n": len(s), "p50_ms": p(50), "p95_ms": p(95), "p99_ms": p(99),
            "max_ms": round(s[-1] * 1000, 2),
            "mean_ms": round(statistics.fmean(s) * 1000, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("SAAKSHYA_DB",
                                                   "sqlite:///var/demo.db"))
    ap.add_argument("--iterations", type=int, default=60)
    ap.add_argument("--json", type=Path,
                    default=ROOT / "var" / "reports" / "api_latency.json")
    args = ap.parse_args()

    state = AppState(args.db, evidence_root=ROOT / "var" / "demo_evidence")
    ts = TokenService(state.store)
    ts.upsert_user("perf.harness", Role.SUPERVISOR, display_name="perf harness")
    token = ts.mint("perf.harness", label="perf")
    client = TestClient(create_app(state))

    headers = {"Authorization": f"Bearer {token}",
               "X-Case-Id": "PERF-1",
               "X-Purpose": "latency measurement harness"}

    plates = [p for p in state.store.distinct_plates() if p]
    plate = plates[0] if plates else "GJ01AA0000"
    cams = [c["camera_id"] for c in state.store.list_cameras()]
    cam = cams[0] if cams else "NONE"
    obs = state.store.search_plate(plate)
    obs_id = obs[0].observation_id if obs else "OB-none"
    seen = obs[0].t_norm.isoformat() if obs else datetime.now(UTC).isoformat()

    endpoints = [
        ("GET  /overview", "GET", "/overview"),
        ("GET  /search (plate)", "GET", f"/search?plate={plate}"),
        ("GET  /search (attributes)", "GET", "/search?colour=white&limit=200"),
        ("GET  /trajectory/{plate}", "GET", f"/trajectory/{plate}"),
        ("GET  /gis/cameras", "GET", "/gis/cameras"),
        ("GET  /gis/health", "GET", "/gis/health"),
        ("GET  /gis/capability", "GET", "/gis/capability"),
        ("GET  /gis/coverage", "GET", "/gis/coverage"),
        ("GET  /gis/trajectory/{plate}", "GET", f"/gis/trajectory/{plate}"),
        ("GET  /gis/alerts", "GET", "/gis/alerts"),
        ("GET  /cameras/{id}", "GET", f"/cameras/{cam}"),
        ("GET  /cameras/{id}/next", "GET",
         f"/cameras/{cam}/next?seen_at={quote(seen)}"),
        ("GET  /observations/{id}", "GET", f"/observations/{obs_id}"),
        ("GET  /watchlist", "GET", "/watchlist"),
        ("GET  /alerts", "GET", "/alerts"),
        ("GET  /audit", "GET", "/audit?limit=200"),
        ("GET  /evidence/chain/verify", "GET", "/evidence/chain/verify"),
        ("GET  /targets/{plate}/observations", "GET",
         f"/targets/{plate}/observations"),
    ]

    print(f"database   : {args.db}")
    counts = state.store.stats()
    print(f"scale      : {counts['cameras']} cameras, "
          f"{counts['observations']} observations, "
          f"{counts['audit_entries']} audit entries, "
          f"{counts['evidence']} evidence records")
    print(f"iterations : {args.iterations} per endpoint (in-process; excludes network)\n")

    results = {}
    width = max(len(n) for n, _, _ in endpoints)
    print(f"{'endpoint':{width}}  {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}  status")
    print("-" * (width + 48))
    for name, method, path in endpoints:
        # One warm-up: the first call pays for lazy imports and connection setup,
        # and reporting that as p99 would be misleading.
        client.request(method, path, headers=headers)
        samples, status = [], 0
        for _ in range(args.iterations):
            t0 = time.perf_counter()
            r = client.request(method, path, headers=headers)
            samples.append(time.perf_counter() - t0)
            status = r.status_code
        p = percentiles(samples)
        p["status"] = status
        results[name] = p
        print(f"{name:{width}}  {p['p50_ms']:8.2f} {p['p95_ms']:8.2f} "
              f"{p['p99_ms']:8.2f} {p['max_ms']:8.2f}  {status}")

    slowest = sorted(results.items(), key=lambda kv: -kv[1]["p95_ms"])[:5]
    print("\nslowest five by p95:")
    for name, p in slowest:
        print(f"  {p['p95_ms']:8.2f} ms  {name}")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({
        "database": args.db,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "iterations": args.iterations,
        "scale": counts,
        "measurement": "in-process TestClient; excludes network latency",
        "results": results,
    }, indent=2))
    print(f"\nwritten: {display(args.json, ROOT)}")
    bad = [n for n, p in results.items() if p["status"] >= 400]
    if bad:
        print(f"\nNOTE: {len(bad)} endpoint(s) returned an error status and their "
              f"timings measure the error path: {', '.join(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
