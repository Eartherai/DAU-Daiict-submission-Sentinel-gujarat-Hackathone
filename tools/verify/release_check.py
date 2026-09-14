#!/usr/bin/env python3
"""The release gate. Everything, in order, from a clean state.

Reports rather than stops at the first failure: knowing that three gates fail is
more useful than knowing the first one does, and a partial run invites the habit
of fixing one thing and re-running the whole suite to find the next.

Each gate is labelled BLOCKING or ADVISORY. A blocking gate failing means this
is not a release candidate. An advisory gate failing is recorded and reported,
because some of them (the live sandbox, the two-hour soak) need infrastructure
that is not always present, and a check that silently skips is worse than one
that says it skipped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def display(path, base=None):
    """Shorten a path for display, never raising. See saakshya.common.paths."""
    p = Path(path)
    if base is None:
        return str(p)
    try:
        return str(p.resolve().relative_to(Path(base).resolve()))
    except (ValueError, OSError):
        return str(p)

PY = str(ROOT / ".venv" / "bin" / "python")

BLOCKING, ADVISORY = "BLOCKING", "ADVISORY"


class Gate:
    def __init__(self, name: str, cmd: list[str], severity: str = BLOCKING,
                 *, why: str = "", timeout: float = 1800.0) -> None:
        self.name, self.cmd, self.severity, self.why = name, cmd, severity, why
        self.timeout = timeout
        self.ok: bool | None = None
        self.seconds = 0.0
        self.tail = ""

    def run(self) -> None:
        t0 = time.perf_counter()
        try:
            r = subprocess.run(self.cmd, cwd=ROOT, capture_output=True,
                               text=True, timeout=self.timeout, check=False)
            self.ok = r.returncode == 0
            out = (r.stdout or "") + (r.stderr or "")
            self.tail = "\n".join(out.strip().splitlines()[-12:])
        except subprocess.TimeoutExpired:
            self.ok = False
            self.tail = f"timed out after {self.timeout:.0f}s"
        except FileNotFoundError as exc:
            self.ok = False
            self.tail = str(exc)
        self.seconds = time.perf_counter() - t0


def gates(skip_slow: bool) -> list[Gate]:
    g = [
        Gate("lint", [PY, "-m", "ruff", "check", "src", "tools", "tests"],
             why="unused imports and dead code hide real defects"),
        Gate("typecheck", [PY, "-m", "mypy", "src/saakshya"],
             why="a type error here is a latent crash; src/ is clean and stays clean"),
        Gate("model activation", [PY, "tools/verify/validate_models.py"],
             why="a registry entry is a claim, not evidence — this project "
                 "shipped a detector that had never produced a detection"),
        Gate("secret scan", [PY, "tools/verify/secret_scan.py"],
             why="no credential may enter the repository or its history"),
        Gate("licence policy", [PY, "tools/verify/licence_check.py"],
             why="a non-permissive dependency cannot ship to a government"),
        Gate("unit tests", [PY, "-m", "pytest", "tests/unit", "-q"]),
        Gate("security tests", [PY, "-m", "pytest", "tests/security", "-q"],
             why="authentication, authorisation, injection, traversal, leakage"),
        Gate("integration tests", [PY, "-m", "pytest", "tests/integration", "-q"]),
        Gate("ML regression",
             [PY, "-m", "pytest", "tests/evaluation", "-q"], ADVISORY,
             why="advisory: requires the rendered corpus"),
        Gate("end-to-end", [PY, "-m", "pytest", "tests/e2e", "-q"],
             why="the mandatory chain, and the offline demonstration"),
        Gate("query plans", [PY, "tools/perf/query_plans.py"], ADVISORY,
             why="every index must be justified by a plan"),
        Gate("api latency", [PY, "tools/perf/api_latency.py",
                             "--iterations", "30"], ADVISORY,
             why="records p50/p95/p99 for the release note"),
        Gate("clean install", [PY, "tools/verify/clean_rebuild.py"],
             why="catches machine-local dependencies — the class of failure "
                 "that first appears on the evaluator's laptop"),
    ]
    if not skip_slow:
        g.append(Gate("ANPR evaluation",
                      [PY, "tests/evaluation/run_anpr_eval.py", "--fps", "4"],
                      ADVISORY, why="advisory: requires the rendered corpus",
                      timeout=2400))
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-slow", action="store_true")
    ap.add_argument("--json", type=Path,
                    default=ROOT / "var" / "reports" / "release_check.json")
    args = ap.parse_args()

    print("SAAKSHYA release check")
    print(f"{datetime.now(UTC).isoformat(timespec='seconds')}  "
          f"python={sys.version.split()[0]}  cwd={ROOT.name}\n")

    checks = gates(args.skip_slow)
    width = max(len(g.name) for g in checks)
    for g in checks:
        print(f"  {g.name:{width}} … ", end="", flush=True)
        g.run()
        mark = "PASS" if g.ok else ("FAIL" if g.severity == BLOCKING else "WARN")
        print(f"{mark:4}  {g.seconds:6.1f}s")

    blocking = [g for g in checks if g.severity == BLOCKING and not g.ok]
    advisory = [g for g in checks if g.severity == ADVISORY and not g.ok]

    print()
    for g in blocking + advisory:
        print(f"── {g.name} ({g.severity}) ──")
        if g.why:
            print(f"   {g.why}")
        for line in g.tail.splitlines():
            print(f"   {line}")
        print()

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "gates": [{"name": g.name, "severity": g.severity, "ok": g.ok,
                   "seconds": round(g.seconds, 1), "tail": g.tail}
                  for g in checks],
        "blocking_failures": [g.name for g in blocking],
        "advisory_failures": [g.name for g in advisory],
        "release_candidate": not blocking,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2))

    total = sum(g.seconds for g in checks)
    print(f"{len(checks) - len(blocking) - len(advisory)}/{len(checks)} gates passed "
          f"in {total:.0f}s")
    if blocking:
        print(f"\nNOT A RELEASE CANDIDATE — blocking: {', '.join(g.name for g in blocking)}")
    else:
        print("\nRELEASE CANDIDATE: all blocking gates pass"
              + (f" ({len(advisory)} advisory warning(s))" if advisory else ""))
    print(f"written: {display(args.json, ROOT)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
