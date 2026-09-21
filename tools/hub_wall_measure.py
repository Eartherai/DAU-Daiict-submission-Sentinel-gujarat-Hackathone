#!/usr/bin/env python3
"""Measure local-hub wall: upstream sessions vs browser LIVE. No secrets."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

BASE = os.environ.get("SAAKSHYA_BASE", "http://127.0.0.1:8080")
TOKEN = Path("/tmp/saakshya-demo-token.raw")


def _get(path: str) -> dict:
    req = urllib.request.Request(
        BASE + path,
        headers={"Authorization": f"Bearer {TOKEN.read_text().strip()}",
                 "X-Case-Id": "FIR-214/2026",
                 "X-Purpose": "media hub measurement"},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)


def main() -> int:
    t0 = time.monotonic()
    healthz = urllib.request.urlopen(BASE + "/healthz", timeout=3).status
    print(f"healthz {healthz}", flush=True)
    last = {}
    for i in range(40):
        try:
            last = _get("/media/hub")
        except Exception as exc:
            print(f"hub wait {i}: {type(exc).__name__}", flush=True)
            time.sleep(2)
            continue
        n = last.get("upstream_sessions") or 0
        live = last.get("browser_live") or 0
        gov_live = last.get("government_live")
        conn = last.get("source_connected") or 0
        print(f"t={time.monotonic()-t0:.0f}s upstream={n} connected={conn} "
              f"live={live} gov_live={gov_live}",
              flush=True)
        if n >= 30 and i >= 12:
            break
        time.sleep(2)
    out = ROOT / "reports/final_live_qa/hub_wall.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(last, indent=2)
    assert "AIza" not in blob
    out.write_text(blob + "\n")
    print("wrote", out)
    try:
        sys_h = _get("/system/health")
        print("system", sys_h.get("overall"),
              [c["component"] + "=" + c["state"] for c in sys_h.get("components") or []])
    except Exception as exc:
        print("system health", type(exc).__name__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
