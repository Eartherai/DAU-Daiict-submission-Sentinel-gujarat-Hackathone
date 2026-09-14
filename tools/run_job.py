"""Run a command under a resource lease, or refuse to start it.

Every heavy job in this repo goes through here so that admission is decided in
one place and visible in one place. Classification is the caller's, because only
the caller knows whether a run is a live government capture or a benchmark:

    python tools/run_job.py --class A --name live-30cam -- \
        python tools/live/ingest.py --minutes 0 ...

A refusal is immediate and explains itself. The failure this replaces was a
live capture killed silently twenty minutes in, having produced nothing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.runtime.scheduler import (
    DEFAULT_WORKING_SET_MB,
    JobClass,
    ResourceBusy,
    Scheduler,
    describe,
)

_ALIASES = {"A": JobClass.A_LIVE, "B": JobClass.B_INTERACTIVE,
            "C": JobClass.C_BENCHMARK, "D": JobClass.D_VERIFY}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--class", dest="klass", required=False,
                    choices=[*_ALIASES, *[str(c) for c in JobClass]])
    ap.add_argument("--name", default="job")
    ap.add_argument("--memory-mb", type=int, default=None,
                    help="override the class's estimated working set")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="seconds to queue behind a job this may not join")
    ap.add_argument("--status", action="store_true",
                    help="print what holds the machine and exit")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    a = ap.parse_args()

    if a.status:
        print(json.dumps(describe(), indent=2))
        return 0
    if not a.klass:
        ap.error("--class is required unless --status is given")

    cmd = [c for c in a.command if c != "--"]
    if not cmd:
        ap.error("no command given after --")

    job_class = _ALIASES.get(a.klass) or JobClass(a.klass)
    need = a.memory_mb or DEFAULT_WORKING_SET_MB[job_class]
    sched = Scheduler()
    try:
        with sched.lease(job_class, a.name, working_set_mb=need,
                         wait_s=a.wait):
            print(f"[{job_class}] {a.name} — ~{need} MB, "
                  f"{sched.committed_mb()} of {sched.budget_mb()} MB committed",
                  flush=True)
            return subprocess.call(cmd)
    except ResourceBusy as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        print("\nRunning now:", file=sys.stderr)
        for job in describe()["jobs"]:
            print(f"  {job['job_class']:<14} {job['name']:<24} "
                  f"pid {job['pid']:<8} ~{job['working_set_mb']} MB",
                  file=sys.stderr)
        print("\nA live government run is never refused. Anything else waits "
              "for it, or is run with --wait.", file=sys.stderr)
        return 75                              # EX_TEMPFAIL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
