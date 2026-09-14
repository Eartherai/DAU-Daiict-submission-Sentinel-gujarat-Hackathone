#!/usr/bin/env python3
"""Install into a fresh, isolated environment and prove the package works there.

This is the gate that catches machine-local dependencies — the package someone
installed globally two weeks ago, the stale editable install, the import that
only resolves because the working directory happens to be the repository root.
That class of problem appears for the first time on the evaluator's laptop,
which is the worst possible place to discover it.

Deliberately **non-destructive**: it builds into a temporary directory rather
than deleting the working `.venv`. Same evidence, and it can be run at any time
without taking the development environment down with it — a check that costs a
rebuild to run is a check that gets skipped.

    python tools/verify/clean_rebuild.py
    python tools/verify/clean_rebuild.py --keep     # leave the venv for inspection
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
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


#: Imported in a subprocess with the repository *not* on the path, so an import
#: that only works from the source tree fails here rather than in the field.
IMPORT_CHECKS = [
    "saakshya",
    "saakshya.api.app",
    "saakshya.analytics.pipeline",
    "saakshya.capability",
    "saakshya.copilot",
    "saakshya.edge",
    "saakshya.evidence",
    "saakshya.gis",
    "saakshya.ingest.stream",
    "saakshya.intelligence",
    "saakshya.investigation",
    "saakshya.obs",
    "saakshya.security",
    "saakshya.store",
    "saakshya.watchlist",
]


def run(cmd: list[str], cwd: Path, timeout: float = 900.0) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, check=False)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode == 0, "\n".join(out.splitlines()[-15:])
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:.0f}s"
    except FileNotFoundError as exc:
        return False, str(exc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="do not delete the temporary environment")
    ap.add_argument("--json", type=Path,
                    default=ROOT / "var" / "reports" / "clean_rebuild.json")
    args = ap.parse_args()

    if shutil.which("uv") is None:
        print("uv is not on PATH; install it before running this gate",
              file=sys.stderr)
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="saakshya-rebuild-"))
    venv = tmp / ".venv"
    py = venv / "bin" / "python"
    steps: list[dict] = []
    t_start = time.perf_counter()

    print("SAAKSHYA clean rebuild")
    print(f"target : {tmp}")
    print(f"source : {ROOT}\n")

    def step(name: str, cmd: list[str], cwd: Path = ROOT,
             timeout: float = 900.0) -> bool:
        print(f"  {name:34} … ", end="", flush=True)
        t0 = time.perf_counter()
        ok, tail = run(cmd, cwd, timeout)
        dt = time.perf_counter() - t0
        print(f"{'PASS' if ok else 'FAIL'}  {dt:6.1f}s")
        steps.append({"step": name, "ok": ok, "seconds": round(dt, 1),
                      "tail": tail})
        return ok

    ok = step("create an empty environment",
              ["uv", "venv", "--python", "3.12", str(venv)], cwd=tmp)

    # Installed non-editable and from a different working directory: an editable
    # install would keep the source tree on the path and hide exactly the
    # problem this gate exists to find.
    if ok:
        ok = step("install the package (non-editable)",
                  ["uv", "pip", "install", "--python", str(py), str(ROOT)],
                  cwd=tmp)

    if ok:
        code = "; ".join(f"import {m}" for m in IMPORT_CHECKS)
        ok = step(f"import {len(IMPORT_CHECKS)} modules from outside the tree",
                  [str(py), "-c", code], cwd=tmp)

    if ok:
        # The chain has to work on a machine that has never seen the repository.
        probe = (
            "from saakshya.store import Store; "
            "from saakshya.api.app import create_app; "
            "from saakshya.api.deps import AppState; "
            "s = Store('sqlite:///rebuild.db'); s.create_all(); "
            "app = create_app(AppState('sqlite:///rebuild.db')); "
            "print('routes', len(app.routes))")
        ok = step("build the application from a clean store",
                  [str(py), "-c", probe], cwd=tmp)

    if ok:
        ok = step("install the test extras",
                  ["uv", "pip", "install", "--python", str(py), "pytest"],
                  cwd=tmp)

    if ok:
        # Unit tests only: the integration and E2E suites need the rendered
        # corpus, which is a data dependency rather than an install one.
        step("unit tests against the installed package",
             [str(py), "-m", "pytest", str(ROOT / "tests" / "unit"), "-q",
              "-p", "no:cacheprovider"], cwd=ROOT, timeout=600)

    total = time.perf_counter() - t_start
    failed = [s for s in steps if not s["ok"]]

    print()
    for s in failed:
        print(f"── {s['step']} ──")
        for line in s["tail"].splitlines():
            print(f"   {line}")
        print()

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "environment": str(tmp),
        "seconds": round(total, 1),
        "steps": steps,
        "clean_install_works": not failed,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2))

    if args.keep:
        print(f"environment kept at {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{len(steps) - len(failed)}/{len(steps)} steps passed in {total:.0f}s")
    print("CLEAN INSTALL: " + ("WORKS" if not failed else "BROKEN"))
    print(f"written: {display(args.json, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
