#!/usr/bin/env python3
"""Designated-vehicle API rehearsal. Token stays on disk; never printed."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/final/live/designated_vehicle.json"
TOKEN_FILE = Path("/tmp/saakshya-demo-token.raw")
PLATE = "GJ01TA0001"


def refuse(blob: str) -> None:
    if "AIzaSy" in blob or "skv_" in blob:
        raise SystemExit("refusing secret-shaped token in demo API artifact")
    key = os.environ.get("GOOGLE_MAPS_API_KEY") or ""
    if key and key in blob:
        raise SystemExit("refusing maps key in demo API artifact")


def call(path: str, token: str) -> dict:
    req = Request(
        "http://127.0.0.1:8080" + path,
        headers={
            "Authorization": "Bearer " + token,
            "X-Case-Id": "FIR-214/2026",
            "X-Purpose": "final live production designated vehicle rehearsal",
        },
    )
    try:
        with urlopen(req, timeout=20) as res:
            body = json.loads(res.read().decode())
            return {"http": res.status, "ok": True, "keys": sorted(body)[:24],
                    "summary": _summarise(path, body)}
    except HTTPError as exc:
        return {"http": exc.code, "ok": False, "error": str(exc.reason)}
    except URLError as exc:
        return {"http": 0, "ok": False, "error": type(exc.reason).__name__}


def _summarise(path: str, body: dict) -> dict:
    if "/search" in path:
        sight = body.get("sighting") or {}
        cands = body.get("candidates") or []
        return {
            "result_count": body.get("result_count"),
            "has_sighting": bool(sight),
            "candidates": len(cands) if isinstance(cands, list) else None,
        }
    if "/follow" in path:
        route = body.get("route") or {}
        timeline = body.get("timeline") or []
        return {
            "timeline_n": len(timeline) if isinstance(timeline, list) else None,
            "route_keys": sorted(route)[:12] if isinstance(route, dict) else None,
            "route_confidence": body.get("route_confidence"),
            "contradictions": len(body.get("contradictions") or []),
        }
    if path.endswith("/watchlist") or "/watchlist?" in path:
        rows = body.get("entries") or body.get("watchlist") or []
        return {"n": len(rows) if isinstance(rows, list) else body.get("count")}
    if path.startswith("/alerts"):
        rows = body.get("alerts") or []
        return {"n": len(rows) if isinstance(rows, list) else body.get("count")}
    if "/follow" in path:
        hops = body.get("hops") or body.get("sightings") or body.get("cameras") or []
        return {"n": len(hops) if isinstance(hops, list) else None,
                "first": body.get("first_seen"), "last": body.get("last_seen")}
    if "/trajectory" in path:
        hyps = body.get("hypotheses") or body.get("routes") or []
        return {"n": len(hyps) if isinstance(hyps, list) else None}
    if path == "/audit?limit=8":
        rows = body.get("entries") or []
        return {"n": len(rows)}
    if path == "/system/health":
        return {"overall": body.get("overall"),
                "components": [c.get("component") for c in body.get("components") or []]}
    if path == "/command/summary":
        kpis = body.get("kpis") or {}
        return {
            "onboarded": body.get("onboarded") or body.get("cameras"),
            "rank_rows": len(body.get("rank_equivalence") or []),
            "cameras_online": (kpis.get("cameras_online") or {}).get("display"),
            "cameras_degraded": (kpis.get("cameras_degraded") or {}).get("display"),
        }
    if path == "/config":
        live = body.get("live") or {}
        gmap = (body.get("map") or {}).get("google") or {}
        return {
            "whep": live.get("whep"),
            "proxy": live.get("proxy"),
            "government_feed": live.get("government_feed"),
            "own_feed": live.get("own_feed"),
            "maps_enabled": gmap.get("enabled"),
            "maps_key_published": gmap.get("key") not in (None, "", False),
        }
    return {"n_keys": len(body)}


def main() -> int:
    token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.is_file() else ""
    if not token:
        print("no demo token")
        return 2
    plate = PLATE
    paths = [
        "/config",
        "/command/summary",
        "/system/health",
        "/watchlist",
        f"/search?plate={plate}",
        "/alerts?status=OPEN",
        f"/follow/{plate}",
        f"/trajectory/{plate}",
        "/audit?limit=8",
        "/command/systems",
        "/gis/extent",
    ]
    rows = []
    for path in paths:
        row = {"path": path, **call(path, token)}
        rows.append(row)
        print(path, row.get("http"), "ok" if row.get("ok") else row.get("error"))
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "plate": plate,
        "label": "MEASURED",
        "calls": rows,
    }
    text = json.dumps(payload, indent=2)
    refuse(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
