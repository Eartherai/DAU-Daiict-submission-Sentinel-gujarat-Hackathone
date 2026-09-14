"""Resource-aware admission control across processes.

A twenty-five minute live capture of the government grid was lost because a
vision-language benchmark, the release gate and a six-camera ingest were running
at once on a 24 GB machine. The ingest was killed without a traceback, produced
nothing, and the failure was invisible until the store was inspected. Nothing in
the system knew the three jobs existed at the same time.

They are separate *processes*, so an in-process semaphore cannot help. This is a
lease directory: each job writes a small file naming its class, its estimated
working set and its pid, and checks what else holds a lease before starting.

The rule that matters is priority, not fairness:

    CLASS_A  live government ingestion and inference — never yields
    CLASS_B  interactive investigation, the API serving an operator
    CLASS_C  model and VLM benchmarking
    CLASS_D  release tests and verification

A live evaluation run is the point of the system. CLASS C and D refuse to start
while CLASS A holds a lease, and every class refuses when the estimated working
set would exceed the memory budget. Refusal is immediate and explains itself:
a job that cannot run should say so in a second, not die in twenty minutes.

Leases are advisory and self-healing. A lease whose process is gone is reclaimed
on the next check, so a hard kill cannot wedge the system.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

log = logging.getLogger("saakshya.runtime.scheduler")

#: Fraction of physical memory the sum of running jobs may claim. The remainder
#: is not slack: the page cache serves the decoders, and macOS begins killing
#: processes well before physical exhaustion.
MEMORY_HEADROOM = 0.70

DEFAULT_LEASE_DIR = Path(os.environ.get(
    "SAAKSHYA_RUN_DIR", "var/run")) / "leases"


class JobClass(StrEnum):
    """Ordered by right to the machine, most privileged first."""

    A_LIVE = "A_LIVE"                 # live government ingestion / inference
    B_INTERACTIVE = "B_INTERACTIVE"   # API serving an operator
    C_BENCHMARK = "C_BENCHMARK"       # model and VLM benchmarking
    D_VERIFY = "D_VERIFY"             # release tests and verification


#: What each class is expected to hold resident. Measured, not guessed:
#: a six-camera T2 ingest peaked at 1.66 GB; the 4B VLM at fp16 needs ~9 GB;
#: the release gate runs pytest suites that peak near 2 GB.
DEFAULT_WORKING_SET_MB: dict[JobClass, int] = {
    JobClass.A_LIVE: 2600,
    JobClass.B_INTERACTIVE: 400,
    JobClass.C_BENCHMARK: 9000,
    JobClass.D_VERIFY: 2200,
}

#: Read as: BLOCKED_BY[the class trying to start] = classes whose presence
#: refuses that start. Written the other way round first — mapping A to the
#: classes it displaces — which inverted the whole rule and let a benchmark and
#: a release gate start beside a live capture, exactly the situation that lost
#: the twenty-five minute run. The direction is asserted below.
#:
#: A_LIVE is blocked by nothing: the live grid is never refused, and nothing
#: displaces it. B_INTERACTIVE is blocked by nothing either — an operator must
#: be able to use the workspace while the grid runs, and it is cheap.
BLOCKED_BY: dict[JobClass, frozenset[JobClass]] = {
    JobClass.A_LIVE: frozenset(),
    JobClass.B_INTERACTIVE: frozenset(),
    JobClass.C_BENCHMARK: frozenset({JobClass.A_LIVE, JobClass.C_BENCHMARK}),
    JobClass.D_VERIFY: frozenset({JobClass.A_LIVE, JobClass.C_BENCHMARK}),
}

#: The live grid is never refused on account of another job, and the heavy
#: classes always yield to it. Asserted rather than commented, because the
#: relation is easy to write backwards and reads plausibly either way.
assert BLOCKED_BY[JobClass.A_LIVE] == frozenset()
assert JobClass.A_LIVE in BLOCKED_BY[JobClass.C_BENCHMARK]
assert JobClass.A_LIVE in BLOCKED_BY[JobClass.D_VERIFY]


class ResourceBusy(RuntimeError):
    """Raised instead of starting a job the machine cannot afford."""


@dataclass(frozen=True)
class Lease:
    job_class: JobClass
    name: str
    pid: int
    working_set_mb: int
    started_at: float

    @property
    def alive(self) -> bool:
        """Whether the process holding this lease still exists.

        `kill(pid, 0)` signals nothing and raises if the process is gone, which
        is how a lease left behind by a hard kill is reclaimed rather than
        blocking the machine forever.
        """
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True                    # exists, owned by someone else
        return True

    def to_dict(self) -> dict[str, Any]:
        return {"job_class": str(self.job_class), "name": self.name,
                "pid": self.pid, "working_set_mb": self.working_set_mb,
                "started_at": self.started_at}


def total_memory_mb() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                   / (1 << 20))
    except (ValueError, OSError, AttributeError):   # pragma: no cover
        return 16384


class Scheduler:
    """Admission control over a lease directory shared by every process."""

    def __init__(self, lease_dir: Path | str = DEFAULT_LEASE_DIR,
                 memory_mb: int | None = None) -> None:
        self.dir = Path(lease_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.memory_mb = memory_mb or total_memory_mb()

    # -- reading ------------------------------------------------------------ #
    def active(self) -> list[Lease]:
        """Live leases, reclaiming any whose process has gone."""
        out: list[Lease] = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                d = json.loads(f.read_text())
                lease = Lease(JobClass(d["job_class"]), d["name"], int(d["pid"]),
                              int(d["working_set_mb"]), float(d["started_at"]))
            except (OSError, ValueError, KeyError):
                f.unlink(missing_ok=True)          # unreadable: not a claim
                continue
            if lease.alive:
                out.append(lease)
            else:
                log.info("reclaiming lease from dead pid %d (%s)",
                         lease.pid, lease.name)
                f.unlink(missing_ok=True)
        return out

    def committed_mb(self) -> int:
        return sum(x.working_set_mb for x in self.active())

    def budget_mb(self) -> int:
        return int(self.memory_mb * MEMORY_HEADROOM)

    # -- deciding ----------------------------------------------------------- #
    def why_blocked(self, job_class: JobClass, working_set_mb: int
                    ) -> str | None:
        """The reason this job may not start, or None if it may."""
        running = self.active()
        blockers = BLOCKED_BY[job_class]
        for lease in running:
            if lease.job_class in blockers:
                held = time.time() - lease.started_at
                return (f"{lease.job_class} job '{lease.name}' (pid {lease.pid}) "
                        f"has held the machine for {held / 60:.0f} min. "
                        f"{job_class} does not start alongside it.")
        committed = sum(x.working_set_mb for x in running)
        if committed + working_set_mb > self.budget_mb():
            names = ", ".join(f"{x.name} {x.working_set_mb}MB" for x in running)
            over = (f"estimated working set {committed + working_set_mb} MB "
                    f"exceeds the {self.budget_mb()} MB budget "
                    f"({self.memory_mb} MB total x {MEMORY_HEADROOM:.0%}). "
                    f"Running: {names or 'nothing'}.")
            if job_class is JobClass.A_LIVE:
                # The live grid is never refused — a government evaluation run
                # is the point of the system, and turning it away because a
                # benchmark is resident inverts the priority the whole class
                # scheme exists to express. It starts, loudly, naming what
                # should be stopped. Refusing here would be safer for this
                # process and wrong for the deployment.
                log.warning("LIVE RUN ADMITTED OVER BUDGET — %s "
                            "Stop the jobs above before relying on this run.",
                            over)
                return None
            return over
        return None

    # -- holding ------------------------------------------------------------ #
    @contextmanager
    def lease(self, job_class: JobClass, name: str, *,
              working_set_mb: int | None = None,
              wait_s: float = 0.0) -> Iterator[Lease]:
        """Hold a lease for the duration of a block, or refuse to start.

        `wait_s` lets a job queue behind one it must not run beside — useful for
        a verification run that can afford to wait for a live capture to finish,
        and never used by CLASS A, which does not wait for anything.
        """
        need = working_set_mb or DEFAULT_WORKING_SET_MB[job_class]
        deadline = time.monotonic() + wait_s
        while True:
            reason = self.why_blocked(job_class, need)
            if reason is None:
                break
            if time.monotonic() >= deadline:
                raise ResourceBusy(
                    f"{name} ({job_class}, ~{need} MB) did not start: {reason}")
            time.sleep(min(5.0, max(0.5, wait_s / 20)))

        lease = Lease(job_class, name, os.getpid(), need, time.time())
        path = self.dir / f"{job_class}-{os.getpid()}-{name}.json"
        path.write_text(json.dumps(lease.to_dict(), indent=2))
        log.info("lease acquired: %s %s (~%d MB); %d MB of %d MB committed",
                 job_class, name, need, self.committed_mb(), self.budget_mb())
        try:
            yield lease
        finally:
            path.unlink(missing_ok=True)
            log.info("lease released: %s %s", job_class, name)


def describe(lease_dir: Path | str = DEFAULT_LEASE_DIR) -> dict[str, Any]:
    """What is running, for the diagnostics surface."""
    s = Scheduler(lease_dir)
    running = s.active()
    return {
        "total_memory_mb": s.memory_mb,
        "budget_mb": s.budget_mb(),
        "committed_mb": sum(x.working_set_mb for x in running),
        "jobs": [x.to_dict() for x in running],
        "note": ("Advisory leases shared across processes. CLASS A (live "
                 "government ingestion) is never refused and is never "
                 "displaced; benchmarking and verification refuse to start "
                 "beside it."),
    }
