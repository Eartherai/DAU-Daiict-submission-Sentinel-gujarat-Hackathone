#!/usr/bin/env python3
"""Full verification gate — the local stand-in for CI.

Runs every gate, reports each one, and **fails if any required gate fails**. A
gate that cannot run (missing tool, sandbox down) is reported as SKIPPED with the
reason, never silently as a pass: a green board that quietly dropped three checks
is worse than a red one.

    python tools/verify/run_verify.py            # required gates only
    python tools/verify/run_verify.py --full     # + integration, benchmarks

Writes var/reports/verify.json for the release checklist to consume.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "bin" / "python")


@dataclass
class GateResult:
    name: str
    status: str            # PASS | FAIL | SKIPPED
    required: bool
    seconds: float
    detail: str = ""


def run(name: str, cmd: list[str], *, required: bool = True,
        timeout: int = 900, skip_if: str | None = None) -> GateResult:
    if skip_if:
        return GateResult(name, "SKIPPED", required, 0.0, skip_if)
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return GateResult(name, "FAIL", required, time.perf_counter() - t0,
                          f"timed out after {timeout}s")
    dt = time.perf_counter() - t0
    if p.returncode == 0:
        tail = (p.stdout.strip().splitlines() or [""])[-1][:120]
        return GateResult(name, "PASS", required, dt, tail)
    err = (p.stdout + p.stderr).strip().splitlines()
    return GateResult(name, "FAIL", required, dt,
                      " | ".join(x[:110] for x in err[-3:]))


def sandbox_up() -> bool:
    try:
        import httpx

        r = httpx.get("http://127.0.0.1:9997/v3/paths/list", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true",
                    help="include integration and benchmark gates")
    args = ap.parse_args()

    corpus = (ROOT / "var" / "media" / "C-014.mp4").exists()
    live = sandbox_up()

    gates: list[GateResult] = [
        run("lint (ruff)", [PY, "-m", "ruff", "check", "src", "tools", "tests"]),
        run("unit tests", [PY, "-m", "pytest", "tests/unit", "-q"]),
        run("secret scan", [PY, "tools/verify/secret_scan.py"]),
        run("dependency audit", [PY, "-m", "pip_audit", "--progress-spinner", "off",
                                 "--skip-editable"], required=False, timeout=300),
        run("licence policy", [PY, "tools/verify/licence_check.py"]),
    ]

    if args.full:
        gates += [
            run("integration tests", [PY, "-m", "pytest", "tests/integration", "-q"],
                timeout=1800,
                skip_if=None if corpus else "corpus not rendered (make media)"),
            run("stream contract", [PY, "tools/sandbox/smoke.py", "12"],
                required=False, timeout=180,
                skip_if=None if live else "sandbox not running (make sandbox)"),
        ]

    # -- report ------------------------------------------------------------ #
    print()
    print(f"{'GATE':<24}{'STATUS':<10}{'REQ':<6}{'TIME':>8}  DETAIL")
    print("-" * 96)
    for g in gates:
        req = "yes" if g.required else "no"
        print(f"{g.name:<24}{g.status:<10}{req:<6}{g.seconds:>7.1f}s  {g.detail[:44]}")

    failed = [g for g in gates if g.status == "FAIL" and g.required]
    soft = [g for g in gates if g.status == "FAIL" and not g.required]
    skipped = [g for g in gates if g.status == "SKIPPED"]

    out = ROOT / "var" / "reports" / "verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "full": args.full,
        "gates": [asdict(g) for g in gates],
        "required_failures": [g.name for g in failed],
        "advisory_failures": [g.name for g in soft],
        "skipped": [{"gate": g.name, "reason": g.detail} for g in skipped],
        "verdict": "FAIL" if failed else "PASS",
    }, indent=2))

    print()
    if skipped:
        print("SKIPPED (not counted as passes):")
        for g in skipped:
            print(f"  - {g.name}: {g.detail}")
    if soft:
        print(f"ADVISORY failures (non-blocking): {[g.name for g in soft]}")
    if failed:
        print(f"\nVERIFY: FAIL — {[g.name for g in failed]}")
        return 1
    print("\nVERIFY: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
