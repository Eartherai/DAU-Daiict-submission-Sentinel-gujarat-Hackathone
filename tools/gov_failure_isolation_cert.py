#!/usr/bin/env python3
"""Camera failure isolation: kill one publisher; peer cameras must keep publishing.

Uses the managed MediaMTX path. Credentials remain environment-only.
Does not claim government upstream is broken — only that our process isolates faults.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from saakshya.live.credentials import configured  # noqa: E402


def child_env() -> dict[str, str]:
    keep = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR",
        "VIRTUAL_ENV", "PYTHONPATH", "PYTHONUNBUFFERED",
        "SENTINEL_GRID_EMAIL", "SENTINEL_GRID_PASSWORD",
    }
    return {k: v for k, v in os.environ.items() if k in keep}


def api(path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:9997{path}", timeout=3) as r:
        return json.load(r)


def path_ready(cam: str) -> dict:
    try:
        d = api(f"/v3/paths/get/stream/gov-{cam}")
        return {
            "ready": bool(d.get("ready")),
            "bytes": int(d.get("bytesReceived") or 0),
            "online": bool(d.get("online") or d.get("ready")),
        }
    except Exception as exc:
        return {"ready": False, "bytes": 0, "online": False, "error": str(exc)}


def write_config(cams: list[str]) -> Path:
    lines = [
        "# generated — no credentials",
        "logLevel: warn",
        "rtspAddress: :8554",
        "rtspTransports: [tcp]",
        "webrtcAddress: :8889",
        "webrtcAllowOrigins: [\"*\"]",
        "api: yes",
        "apiAddress: 127.0.0.1:9997",
        "paths:",
    ]
    for cam in cams:
        lines.append(f"  stream/gov-{cam}:")
    dst = ROOT / "var/mediamtx_gov_isolation.yml"
    dst.write_text("\n".join(lines) + "\n")
    return dst


def main() -> int:
    if not configured():
        print("credentials not configured", file=sys.stderr)
        return 2

    # Healthy peers + one intentional victim (cam05 historically weakest under load)
    peers = ["cam01", "cam02"]
    victim = "cam05"
    cams = peers + [victim]
    out_dir = ROOT / "var/reports/phase8c/gov"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).isoformat()

    subprocess.run(["pkill", "-f", "var/bin/mediamtx"], check=False)
    time.sleep(0.5)
    cfg = write_config(cams)
    log = open(ROOT / "var/logs/mediamtx_gov_isolation.log", "ab")
    mtx = subprocess.Popen(
        [str(ROOT / "var/bin/mediamtx"), str(cfg)],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(40):
        time.sleep(0.25)
        try:
            api("/v3/paths/list")
            break
        except Exception:
            if mtx.poll() is not None:
                print("MediaMTX failed", file=sys.stderr)
                return 3

    pubs: dict[str, subprocess.Popen] = {}
    stages: list[dict] = []
    try:
        for cam in cams:
            pubs[cam] = subprocess.Popen(
                [sys.executable, str(ROOT / "tools/gov_whep_relay.py"), cam,
                 "--seconds", "90", "--publish-only"],
                cwd=str(ROOT), env=child_env(),
            )

        # Wait for all ready
        pending = set(cams)
        for i in range(45):
            time.sleep(1)
            for cam in list(pending):
                st = path_ready(cam)
                if st["ready"] and st["bytes"] > 15000:
                    pending.discard(cam)
            if not pending:
                break
        before = {cam: path_ready(cam) for cam in cams}
        stages.append({
            "stage": "baseline_ready",
            "status": "PASS" if not pending else "FAIL",
            "detail": {"pending": sorted(pending), "before": before},
        })
        if pending:
            raise RuntimeError(f"not ready: {sorted(pending)}")

        # Kill victim publisher hard
        victim_proc = pubs[victim]
        victim_proc.send_signal(signal.SIGKILL)
        try:
            victim_proc.wait(timeout=5)
        except Exception:
            pass
        time.sleep(3)
        after_kill = {cam: path_ready(cam) for cam in cams}

        # Peers must still be ready / growing bytes
        time.sleep(5)
        after_wait = {cam: path_ready(cam) for cam in cams}
        peer_ok = all(
            after_wait[c]["ready"] and after_wait[c]["bytes"] >= before[c]["bytes"]
            for c in peers
        )
        victim_degraded = (
            not after_wait[victim]["ready"]
            or after_wait[victim]["bytes"] == before[victim]["bytes"]
            or pubs[victim].poll() is not None
        )
        stages.append({
            "stage": "victim_killed",
            "status": "PASS" if victim_degraded else "AMBER",
            "detail": {
                "victim": victim,
                "after_kill": after_kill,
                "after_wait": after_wait,
                "victim_exit": pubs[victim].poll(),
            },
        })
        stages.append({
            "stage": "peers_continue",
            "status": "PASS" if peer_ok else "FAIL",
            "detail": {"peers": peers, "after_wait": {c: after_wait[c] for c in peers}},
        })

        # Process-wide: MediaMTX still up; other relays alive
        mtx_alive = mtx.poll() is None
        peers_alive = all(pubs[c].poll() is None for c in peers)
        stages.append({
            "stage": "process_alive",
            "status": "PASS" if mtx_alive and peers_alive else "FAIL",
            "detail": {
                "mediamtx_exit": mtx.poll(),
                "peer_exits": {c: pubs[c].poll() for c in peers},
            },
        })

        # Secret-ish argv check on remaining processes
        leak = False
        for c in peers:
            try:
                cmdline = Path(f"/proc/{pubs[c].pid}/cmdline").read_bytes().decode(
                    "utf-8", "ignore") if sys.platform.startswith("linux") else ""
            except Exception:
                cmdline = ""
            # macOS: use ps
            if not cmdline:
                ps = subprocess.run(
                    ["ps", "-p", str(pubs[c].pid), "-o", "command="],
                    capture_output=True, text=True,
                )
                cmdline = ps.stdout
            if "@103." in cmdline or "SENTINEL_GRID_PASSWORD" in cmdline:
                leak = True
        stages.append({
            "stage": "no_credential_argv",
            "status": "PASS" if not leak else "FAIL",
            "detail": "peer publisher argv inspected; credentials must not appear",
        })

        # Stale LIVE: victim path must not be advertised ready after kill once drained
        # (MediaMTX may keep last path briefly — AMBER if still ready with flat bytes)
        stale = after_wait[victim]["ready"] and after_wait[victim]["bytes"] == before[victim]["bytes"]
        stages.append({
            "stage": "no_stale_live_claim",
            "status": "AMBER" if stale else "PASS",
            "detail": (
                "victim still ready with flat bytes — UI must show degraded/waiting, "
                "not LIVE"
                if stale else "victim not ready or bytes stopped advancing"
            ),
        })

    finally:
        for p in pubs.values():
            if p.poll() is None:
                p.terminate()
        try:
            mtx.terminate()
        except Exception:
            pass

    fails = sum(1 for s in stages if s["status"] == "FAIL")
    ambers = sum(1 for s in stages if s["status"] == "AMBER")
    passes = sum(1 for s in stages if s["status"] == "PASS")
    payload = {
        "timestamp_utc": ts,
        "command": "python tools/gov_failure_isolation_cert.py",
        "cameras": cams,
        "victim": victim,
        "peers": peers,
        "stages": stages,
        "summary": {"PASS": passes, "AMBER": ambers, "FAIL": fails},
        "overall": "FAIL" if fails else ("AMBER" if ambers else "PASS"),
    }
    (out_dir / "failure_isolation.json").write_text(json.dumps(payload, indent=2) + "\n")

    md = [
        "# Government camera failure isolation",
        "",
        f"Timestamp UTC: `{ts}`",
        "",
        f"Victim: **{victim}** · Peers: {', '.join(peers)}",
        "",
        f"Overall: **{payload['overall']}** "
        f"(PASS={passes}, AMBER={ambers}, FAIL={fails})",
        "",
        "| Stage | Status | Detail |",
        "|---|---|---|",
    ]
    for s in stages:
        detail = json.dumps(s["detail"], default=str)[:180].replace("|", "/")
        md.append(f"| {s['stage']} | **{s['status']}** | `{detail}` |")
    md.extend([
        "",
        "Artifact: `var/reports/phase8c/gov/failure_isolation.json`",
        "",
    ])
    (ROOT / "reports/GOV_FAILURE_ISOLATION_CERTIFICATION.md").write_text(
        "\n".join(md) + "\n")
    print(json.dumps(payload["summary"]), "overall", payload["overall"])
    return 0 if fails == 0 else 4


if __name__ == "__main__":
    raise SystemExit(main())
