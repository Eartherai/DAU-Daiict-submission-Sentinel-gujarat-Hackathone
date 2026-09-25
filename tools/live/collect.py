#!/usr/bin/env python3
"""Bounded, metadata-only collection across the registered government estate.

`tools/live/ingest.py` opens the cameras you give it and holds them for as long
as you ask. That is the right shape for a measured run and the wrong shape for
*collection* — building, over hours or days, a searchable metadata record of an
estate this deployment has onboarded. Collection has three constraints the
ingest tool does not enforce, and this supervisor exists to enforce them:

**Never all thirty at once.** The integrator guide is explicit that every
connected client gets its own copy of the stream, and this repository's own
measurements (`docs/SENTINEL_SANDBOX.md`) put the practical ceiling far below
the estate size. So the supervisor holds a small batch — five by default, and
never more than five — and rotates it across the roster. Coverage comes from
time, not from concurrency.

**Nothing but metadata leaves the grid.** There is no recorder here, no muxer,
no byte-range fetch and no file download. What reaches disk is what the platform
already writes: observations, watchlist alerts, stream health, the bounded
alert-evidence window (`saakshya.evidence.rolling` — a handful of JPEG frames
around a sighting that actually fired), and the single overwritten preview still
per camera that the live wall reads instead of opening a second session. The
provenance report states that inventory and *measures* the evidence footprint
rather than asserting it is empty.

**No decoding logic lives here.** Every frame this supervisor is responsible for
is decoded by `LiveWorker` and consumed by `run_stage`, imported from
`tools/live/ingest.py`. RTSP over TCP, PTS-driven timing, backoff-with-jitter
reconnect, tier-aware sampling, corruption sampling and health persistence are
that module's behaviour and are not reimplemented, wrapped or altered. A second
copy of a decode loop is a second set of bugs and a second thing to keep in step
with the guide.

Credentials are read from the process environment by
`saakshya.live.credentials`, at the socket, and nowhere else. This tool holds
none, accepts none on the command line, and refuses to start against an
authenticating grid when the environment is empty rather than opening sessions
that will each 401 twenty seconds later.

    # a two-hour bounded collection over the onboarded estate
    python tools/live/collect.py --duration-minutes 120

    # rotate until interrupted, three cameras at a time
    python tools/live/collect.py --continuous --batch-size 3

    # show the rotation plan and the bounds without touching the grid
    python tools/live/collect.py --dry-run --duration-minutes 60
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from saakshya.live import GridConfig, LiveCamera
from saakshya.live.credentials import configured as credential_configured
from saakshya.live.credentials import needs_grid_credential, redact
from saakshya.store import Store
from saakshya.store.provenance import redacted, refuses_live_writes, store_name

# The decode path, the consumer loop, the health writer and the tier table all
# come from the ingest tool. Importing them is the point: this supervisor
# schedules that code, it does not replace any part of it.
from tools.live.ingest import (
    DEFAULT_FPS_BUDGET,
    PROVENANCE,
    TIER_FPS,
    StageResult,
    from_registry,
    load_cameras,
    run_stage,
    tier_for,
)

TOOL = "tools/live/collect.py"

#: The hard ceiling on simultaneous RTSP sessions, and it is not a default that
#: can be raised with a flag. `docs/SENTINEL_SANDBOX.md` records the guide's
#: instruction to pace load and open only the cameras being processed; the
#: snapshot service already caps itself at four concurrent captures. Five is the
#: most this supervisor will hold, so a collection run can never become the
#: thirty-client burst the guide warns against.
MAX_BATCH = 5
MIN_BATCH = 1
DEFAULT_BATCH = 5

#: A batch shorter than this is mostly connect cost. cam21 was measured taking
#: 9.5 s to open and delivering its first decoded frames at 14 s (4 Sep 2026),
#: so a twenty-second dwell spends a connection on the organiser's grid and
#: collects nothing.
MIN_DWELL_MINUTES = 0.5
DEFAULT_DWELL_MINUTES = 2.0

#: Quiet time between batches. The previous batch's sessions have just been torn
#: down; starting the next one in the same instant turns a paced rotation back
#: into a burst.
DEFAULT_SETTLE_S = 10.0

DEFAULT_REPORT = ROOT / "var" / "reports" / "live_collection.json"

#: `run_stage` constructs its rolling evidence under this path, relative to the
#: working directory. Kept as a parameter so the footprint can be measured
#: elsewhere in a test, but the default must track the ingest tool.
EVIDENCE_ROOT = Path("var/live_evidence/rolling")
PREVIEW_ROOT = Path("var/live_evidence/preview")

#: Everything this tool may cause to be written, and nothing else. The list is
#: reported verbatim so a reader is not asked to take "metadata only" on trust.
RETAINED_ARTEFACTS: tuple[dict[str, Any], ...] = (
    {"kind": "observations", "store": "sqlite table `observations`",
     "content": "vehicle metadata: plate, colour, type, bbox, quality, PTS",
     "media": False},
    {"kind": "plate_reads", "store": "sqlite table `plate_reads`",
     "content": "raw OCR attempts, including the ones rejected",
     "media": False},
    {"kind": "alerts", "store": "sqlite table `alerts`",
     "content": "watchlist matches raised during the run", "media": False},
    {"kind": "camera_health", "store": "sqlite table `camera_health`",
     "content": "connects, reconnects, frames, decoder and PTS health",
     "media": False},
    {"kind": "alert_evidence", "store": str(EVIDENCE_ROOT),
     "content": "the existing bounded rolling window — a few JPEG frames "
                "either side of a sighting that raised an alert, and only "
                "then. Nothing is written for a camera that never triggers.",
     "media": True, "bounded": True},
    {"kind": "preview_still", "store": str(PREVIEW_ROOT),
     "content": "one JPEG per camera, overwritten in place, read by the live "
                "wall so it does not open a second session. Not accumulated, "
                "not evidence.",
     "media": True, "bounded": True},
)

#: Why a public or tunnelled exposure of this run is refused. Taken from the
#: source rules this repository already records, not invented here.
SOURCE_RULES = (
    "docs/SENTINEL_SANDBOX.md: \"DON'T publish to the gateway | Consume only. "
    "No control API calls\"",
    "docs/SENTINEL_SANDBOX.md: \"DON'T plan on obtaining copies of the "
    "footage\"",
    "docs/PRIVACY.md §3: stream URLs are withheld — investigators receive "
    "observations and evidence, never live video access",
    "docs/GOVERNMENT_DATA_ACCESS_CHECKLIST.md: access is granted to a "
    "registered account; no credential may be guessed, shared, reused or "
    "worked around",
)


class BoundsError(ValueError):
    """A requested bound this supervisor will not accept."""


# --------------------------------------------------------------------------- #
# Bounds and planning — pure, and the part worth testing without a grid.
# --------------------------------------------------------------------------- #

def check_batch_size(requested: int) -> int:
    """The batch size, or a refusal naming the ceiling.

    Deliberately not a clamp. An operator who asked for thirty concurrent
    cameras has the wrong model of what this tool does, and silently giving them
    five would leave that model intact.
    """
    if requested < MIN_BATCH or requested > MAX_BATCH:
        raise BoundsError(
            f"--batch-size {requested} is outside {MIN_BATCH}-{MAX_BATCH}. "
            f"Every connected client receives its own copy of the stream, so "
            f"concurrency is load on the organiser's grid; this supervisor "
            f"covers the estate by rotating a small batch over time, never by "
            f"opening more of it at once.")
    return requested


def check_dwell(minutes: float) -> float:
    """The per-batch dwell, or a refusal naming the measured floor."""
    if minutes < MIN_DWELL_MINUTES:
        raise BoundsError(
            f"--dwell-minutes {minutes} is below the {MIN_DWELL_MINUTES} "
            f"minute floor. A camera on this grid was measured taking 9.5 s to "
            f"open and 14 s to deliver its first decoded frames, so a shorter "
            f"dwell spends a connection on the grid and collects nothing.")
    return minutes


def fit_batch_size(requested: int, tiers: dict[str, str],
                   fps_budget: float) -> tuple[int, str]:
    """Shrink the batch until the analysed-fps promise can actually be kept.

    A tier is a promise: `ingest.py` says so, and the failure it describes —
    every camera silently receiving a fraction of its rate, and per-track plate
    voting never accumulating — is exactly what a supervisor rotating batches
    that are too large would produce, on every batch, for hours.

    The worst-case tier in the roster is used rather than the mean, because the
    batch that happens to collect the expensive cameras is the one that would
    break the promise, and which batch that is depends on the rotation offset.
    """
    size = check_batch_size(requested)
    if fps_budget <= 0 or not tiers:
        return size, "no fps budget applied"
    worst = max(TIER_FPS.get(t, 1.0) for t in tiers.values())
    if worst <= 0:
        return size, "no fps budget applied"
    affordable = max(1, int(fps_budget // worst))
    if affordable >= size:
        return size, (f"{size} cameras at the worst tier in the roster "
                      f"({worst:.1f} fps each) fits the {fps_budget:.1f} fps "
                      f"budget")
    return affordable, (
        f"reduced from {size} to {affordable}: the most expensive tier in the "
        f"roster asks {worst:.1f} analysed fps per camera and this host is "
        f"configured for {fps_budget:.1f}")


def rotation_plan(cameras: Sequence[str], batch_size: int, *,
                  cycle: int = 0) -> list[list[str]]:
    """One full pass over the roster, as batches of at most `batch_size`.

    Two properties matter and both are tested. Every camera appears exactly
    once per cycle, so a run that completes a cycle has covered the estate. And
    the pass *starts* at a different camera each cycle: a collection that always
    began at the first registered camera would give it every partial cycle's
    attention and the last camera none, which over a week is a systematic bias
    in the dataset rather than a scheduling detail.
    """
    size = check_batch_size(batch_size)
    roster = list(cameras)
    n = len(roster)
    if n == 0:
        return []
    offset = (cycle * size) % n
    ordered = roster[offset:] + roster[:offset]
    return [ordered[i:i + size] for i in range(0, n, size)]


def public_exposure_refusal(*, public: bool = False,
                            tunnel: str | None = None) -> str | None:
    """The refusal for exposing this collection publicly, or None.

    Asked for often, because a demonstration is easier to show over a public
    URL. It is refused, and the refusal is a function so the reason is the same
    everywhere and can be asserted in a test rather than remembered.
    """
    if not public and not tunnel:
        return None
    what = "a public listener" if public else f"a tunnel to {tunnel!r}"
    rules = "\n".join(f"  - {r}" for r in SOURCE_RULES)
    return (
        f"REFUSED: this supervisor will not run behind {what}.\n"
        f"Exposing a live collection over a public URL or a tunnel — ngrok or "
        f"any other — re-publishes an authenticated government feed to "
        f"unauthenticated viewers, and re-publication is the one thing the "
        f"access rules for this source forbid outright:\n{rules}\n"
        f"The access granted is to consume the feed under a registered "
        f"account. A tunnel extends that access to everyone holding the URL, "
        f"which is not access this deployment has been given and cannot grant "
        f"itself. Run the supervisor on the host that holds the credential and "
        f"read the results from the local workspace."
    )


def preflight(*, db_url: str, batch_size: int, dwell_minutes: float,
              duration_minutes: float, continuous: bool,
              cameras: Sequence[LiveCamera], public: bool = False,
              tunnel: str | None = None,
              credential_present: bool | None = None) -> list[str]:
    """Every reason this run must not start, collected rather than raised one
    at a time — an operator fixing three things wants to be told three things.
    """
    problems: list[str] = []

    refusal = public_exposure_refusal(public=public, tunnel=tunnel)
    if refusal:
        problems.append(refusal)

    if refuses_live_writes(db_url):
        problems.append(
            f"REFUSED: live observations must not be written into "
            f"{store_name(db_url)}, which holds demonstration or evaluation "
            f"state. Provenance is never mixed — use a store of your own.")

    for check in (lambda: check_batch_size(batch_size),
                  lambda: check_dwell(dwell_minutes)):
        try:
            check()
        except BoundsError as exc:
            problems.append(str(exc))

    if not continuous and duration_minutes <= 0:
        problems.append(
            "--duration-minutes must be positive, or pass --continuous to "
            "rotate until interrupted. A collection with no stated end and no "
            "continuous flag is an operator decision that was never made.")

    if not cameras:
        problems.append(
            "No camera in the registry carries an RTSP URL. Onboard the estate "
            "first (`make government-run`, or pass --allow-discovery); a "
            "collection run over an empty roster is not a run.")

    # The credential is environment-only by design. A grid that authenticates
    # and a process that holds nothing is twelve seconds of 401 per camera, for
    # as long as the rotation lasts.
    if credential_present is None:
        credential_present = credential_configured()
    needs = [c.camera_id for c in cameras
             if needs_grid_credential(c.rtsp_url or "")]
    if needs and not credential_present:
        problems.append(
            f"REFUSED: {len(needs)} camera(s) are on a grid that authenticates "
            f"the RTSP authority and no credential is configured. Set "
            f"SENTINEL_GRID_EMAIL and SENTINEL_GRID_PASSWORD in the process "
            f"environment. They are never read from a file, written to one, "
            f"accepted on the command line, or stored in the registry.")
    return problems


# --------------------------------------------------------------------------- #
# The rotation itself.
# --------------------------------------------------------------------------- #

def _streamed_camera_ids(stats: Sequence[dict[str, Any]]) -> set[str]:
    """Camera ids that delivered at least one decoded frame, per worker snapshot.

    The one place this is decided, so a batch's own console line and the run's
    cumulative `coverage()` can never drift apart. `LiveWorker` sets `state` to
    `STREAMING` the instant the RTSP session opens — before a single frame has
    been decoded — so grading a camera as "streamed" by state, the way the
    ingest tool's own periodic console ticker does, counts a camera that
    connected and then produced nothing for the whole dwell. `frames`, the
    decoder's own running count, is incremented only when a frame is actually
    decoded, and is the number this supervisor commits to everywhere it says a
    camera streamed.
    """
    return {s["camera_id"] for s in stats if (s.get("frames") or 0) > 0}


@dataclass
class BatchOutcome:
    index: int
    cycle: int
    camera_ids: list[str]
    started_at: str
    dwell_minutes: float
    elapsed_minutes: float = 0.0
    observations: int = 0
    watchlist_matches: int = 0
    alerts_raised: int = 0
    frames_delivered: int = 0
    frames_analysed: int = 0
    reconnects: int = 0
    write_failures: int = 0
    observations_unwritten: int = 0
    cameras_streamed: int = 0
    rolling: dict[str, Any] = field(default_factory=dict)
    per_camera: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "cycle": self.cycle,
                "cameras": len(self.camera_ids),
                "camera_ids": list(self.camera_ids),
                "started_at": self.started_at,
                "dwell_minutes": round(self.dwell_minutes, 3),
                "elapsed_minutes": round(self.elapsed_minutes, 3),
                "observations": self.observations,
                "watchlist_matches": self.watchlist_matches,
                "alerts_raised": self.alerts_raised,
                "frames_delivered": self.frames_delivered,
                "frames_analysed": self.frames_analysed,
                "reconnects": self.reconnects,
                "write_failures": self.write_failures,
                "observations_unwritten": self.observations_unwritten,
                "cameras_streamed": self.cameras_streamed,
                "rolling_evidence": self.rolling,
                # Redacted again on the way out. The stats were scrubbed when
                # they were recorded, and this is the second exit — a report is
                # read, attached to a ticket and pasted into a chat.
                "per_camera": [_scrub(s) for s in self.per_camera]}


@dataclass
class CollectionRun:
    batches: list[BatchOutcome] = field(default_factory=list)
    cycles_completed: int = 0
    started_at: str = ""
    finished_at: str = ""
    elapsed_minutes: float = 0.0
    stopped_because: str = ""

    @property
    def max_concurrent_cameras(self) -> int:
        """The high-water mark of simultaneous RTSP sessions this run held.

        `run_stage` opens exactly the cameras handed to it and joins every
        worker before returning, so the largest batch *is* the peak — there is
        no overlap between batches to account for.
        """
        return max((len(b.camera_ids) for b in self.batches), default=0)

    def coverage(self) -> dict[str, Any]:
        visits: dict[str, int] = {}
        for b in self.batches:
            for cid in b.camera_ids:
                visits[cid] = visits.get(cid, 0) + 1
        producing = {s["camera_id"] for b in self.batches for s in b.per_camera
                     if (s.get("observations") or 0) > 0}
        streamed: set[str] = set()
        for b in self.batches:
            streamed |= _streamed_camera_ids(b.per_camera)
        return {"cameras_visited": len(visits),
                "visits_per_camera": dict(sorted(visits.items())),
                "least_visited": min(visits.values()) if visits else 0,
                "most_visited": max(visits.values()) if visits else 0,
                "cameras_that_streamed": len(streamed),
                "cameras_that_produced_observations": len(producing)}

    def totals(self) -> dict[str, Any]:
        return {"batches": len(self.batches),
                "observations": sum(b.observations for b in self.batches),
                "watchlist_matches": sum(b.watchlist_matches
                                         for b in self.batches),
                "alerts_raised": sum(b.alerts_raised for b in self.batches),
                "frames_delivered": sum(b.frames_delivered
                                        for b in self.batches),
                "frames_analysed": sum(b.frames_analysed for b in self.batches),
                "reconnects": sum(b.reconnects for b in self.batches),
                "write_failures": sum(b.write_failures for b in self.batches),
                "observations_unwritten": sum(b.observations_unwritten
                                              for b in self.batches)}


Runner = Callable[..., StageResult]


def _scrub(stats: dict[str, Any]) -> dict[str, Any]:
    """Per-camera stats, with anything that can carry a URL redacted again.

    `LiveWorker` already redacts before storing an error. Doing it a second time
    on the way into a report that will be read, attached and pasted costs
    nothing; a redaction applied at one exit and not another is the same as no
    redaction at all. The redaction itself lives in `saakshya.live.credentials`
    — this supervisor never parses or masks a URL of its own.
    """
    out = dict(stats)
    for key, value in out.items():
        if isinstance(value, str):
            out[key] = redact(value)
    return out


def collect(cameras: Sequence[LiveCamera], tiers: dict[str, str],
            store: Store, cfg: GridConfig, *,
            batch_size: int = DEFAULT_BATCH,
            dwell_minutes: float = DEFAULT_DWELL_MINUTES,
            settle_s: float = DEFAULT_SETTLE_S,
            duration_minutes: float = 0.0,
            continuous: bool = False,
            max_cycles: int | None = None,
            runner: Runner | None = None,
            clock: Callable[[], float] = time.time,
            sleep: Callable[[float], None] = time.sleep,
            should_stop: Callable[[], bool] = lambda: False,
            on_batch: Callable[[CollectionRun], None] | None = None,
            ) -> CollectionRun:
    """Rotate `batch_size` cameras across the roster for the requested time.

    The whole scheduler is here and it is deliberately small: the interesting
    behaviour — decode, reconnect, tiering, watchlist evaluation, health — lives
    in `run_stage`, which this calls once per batch and never reaches into.

    `runner`, `clock` and `sleep` are injected so the rotation can be exercised
    against a fake grid. `runner` is resolved at call time rather than bound as
    a default, so a test that patches `run_stage` patches what actually runs.
    """
    size = check_batch_size(batch_size)
    dwell = check_dwell(dwell_minutes)
    run_batch = runner if runner is not None else run_stage
    by_id = {c.camera_id: c for c in cameras}
    roster = [c.camera_id for c in cameras]

    t_start = clock()
    deadline = float("inf") if continuous else t_start + duration_minutes * 60
    run = CollectionRun(started_at=datetime.now(UTC).isoformat())
    index = 0
    cycle = 0
    stopped = "duration reached"

    while True:
        if should_stop():
            stopped = "interrupted"
            break
        if max_cycles is not None and cycle >= max_cycles:
            stopped = f"max cycles reached ({max_cycles})"
            break
        if clock() >= deadline:
            break

        plan = rotation_plan(roster, size, cycle=cycle)
        if not plan:
            stopped = "no cameras in the roster"
            break

        cycle_complete = True
        # Why the inner loop needs to be able to end the *run*: a batch skipped
        # because the remaining time is below the dwell floor leaves a clock
        # that has not moved. Breaking only the cycle sends the outer loop
        # straight back to the same decision, forever, without ever opening a
        # camera or advancing time. That is a spin, not an early finish.
        finished = False
        for batch_ids in plan:
            if should_stop():
                stopped, cycle_complete, finished = "interrupted", False, True
                break
            remaining_s = deadline - clock()
            if remaining_s <= 0:
                cycle_complete, finished = False, True
                break
            # The tail of a bounded run. Opening a batch we cannot hold for the
            # measured floor spends connections on the grid and collects almost
            # nothing, so the run ends a little early and says so instead.
            minutes = dwell if continuous else min(dwell, remaining_s / 60.0)
            if minutes < MIN_DWELL_MINUTES:
                stopped = ("duration reached; the remaining time was below the "
                           f"{MIN_DWELL_MINUTES} minute dwell floor")
                cycle_complete, finished = False, True
                break

            batch = [by_id[cid] for cid in batch_ids if cid in by_id]
            outcome = BatchOutcome(
                index=index, cycle=cycle, camera_ids=list(batch_ids),
                started_at=datetime.now(UTC).isoformat(), dwell_minutes=minutes)
            t0 = clock()
            res = run_batch(batch, tiers, store, cfg, minutes=minutes)
            outcome.elapsed_minutes = (clock() - t0) / 60.0
            outcome.observations = res.observations
            outcome.watchlist_matches = res.watchlist_matches
            outcome.alerts_raised = res.alerts_raised
            outcome.write_failures = res.write_failures
            outcome.observations_unwritten = res.observations_unwritten
            outcome.rolling = dict(res.rolling or {})
            outcome.per_camera = [_scrub(s) for s in res.stats]
            outcome.cameras_streamed = len(
                _streamed_camera_ids(outcome.per_camera))
            outcome.frames_delivered = sum(s.get("frames") or 0
                                           for s in res.stats)
            outcome.frames_analysed = sum(s.get("frames_analysed") or 0
                                          for s in res.stats)
            outcome.reconnects = sum(s.get("reconnects") or 0
                                     for s in res.stats)
            run.batches.append(outcome)
            index += 1
            if on_batch is not None:
                on_batch(run)

            # Settle, but never past the deadline and never past a stop.
            if settle_s > 0 and not should_stop():
                room = (settle_s if continuous
                        else max(0.0, min(settle_s, deadline - clock())))
                if room > 0:
                    sleep(room)

        if cycle_complete:
            run.cycles_completed += 1
        cycle += 1
        if finished:
            break

    run.finished_at = datetime.now(UTC).isoformat()
    run.elapsed_minutes = (clock() - t_start) / 60.0
    run.stopped_because = stopped
    return run


# --------------------------------------------------------------------------- #
# Provenance.
# --------------------------------------------------------------------------- #

def evidence_footprint(root: Path = EVIDENCE_ROOT) -> dict[str, Any]:
    """What imagery actually exists on disk, measured rather than asserted.

    A report that claims "metadata only" and does not look is a claim, not a
    finding. The bounded alert window is real and does write JPEG frames; the
    honest statement is how many, for how many sightings, and how large — which
    is also the number that tells an operator when retention needs attention.
    """
    root = Path(root)
    if not root.is_dir():
        return {"root": str(root), "captures": 0, "frames": 0, "bytes": 0,
                "present": False}
    captures = 0
    frames = 0
    total = 0
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        held = [f for f in child.glob("*.jpg") if f.is_file()]
        if not held:
            continue
        captures += 1
        frames += len(held)
        total += sum(f.stat().st_size for f in held)
    return {"root": str(root), "captures": captures, "frames": frames,
            "bytes": total, "present": True}


def build_report(*, run: CollectionRun, cameras: Sequence[LiveCamera],
                 roster_source: dict[str, Any], tiers: dict[str, str],
                 cfg: GridConfig, db_url: str, batch_size: int,
                 batch_size_requested: int, batch_reason: str,
                 dwell_minutes: float, settle_s: float,
                 duration_minutes: float, continuous: bool,
                 max_cycles: int | None, fps_budget: float,
                 dataset_before: dict[str, Any],
                 dataset_after: dict[str, Any],
                 evidence: dict[str, Any],
                 public_requested: bool = False,
                 tunnel_requested: str | None = None,
                 executed: bool = True,
                 plan_preview: list[list[str]] | None = None,
                 ) -> dict[str, Any]:
    """The provenance record for one collection run.

    It answers the questions an auditor asks of a dataset built from a live
    government feed: where the cameras came from, how much of the grid was held
    open at once, for how long, what was written, what imagery exists, whether
    the feed was re-published anywhere, and how much the searchable record grew.
    """
    by_tier: dict[str, int] = {}
    for t in tiers.values():
        by_tier[t] = by_tier.get(t, 0) + 1
    grew = {k: (dataset_after.get(k, 0) - dataset_before.get(k, 0))
            for k in ("observations", "observations_with_plate",
                      "distinct_plates", "alerts", "raw_ocr_read_records")}
    return {
        "provenance": PROVENANCE,
        "tool": TOOL,
        "mode": "metadata-only bounded rotation",
        "generated_at": datetime.now(UTC).isoformat(),
        "executed": executed,
        # The report is written under var/reports, and a PostgreSQL URL
        # carries the password.
        "store": redacted(db_url),
        "roster": {
            "source": roster_source.get("source"),
            "caveat": roster_source.get("caveat"),
            "cameras": len(cameras),
            "camera_ids": [c.camera_id for c in cameras],
            "tiers": by_tier,
        },
        "bounds": {
            "batch_size_requested": batch_size_requested,
            "batch_size_effective": batch_size,
            "batch_size_reason": batch_reason,
            "batch_size_ceiling": MAX_BATCH,
            "max_concurrent_rtsp_sessions": run.max_concurrent_cameras,
            "ceiling_respected": run.max_concurrent_cameras <= MAX_BATCH,
            "dwell_minutes": dwell_minutes,
            "dwell_floor_minutes": MIN_DWELL_MINUTES,
            "settle_seconds": settle_s,
            "fps_budget": fps_budget,
            "max_cycles": max_cycles,
            "rationale": (
                "Every connected client receives its own copy of the stream. "
                "Coverage of the estate comes from rotating a small batch over "
                "time, never from opening more of the grid at once."),
        },
        "duration": {
            "requested_minutes": (None if continuous else duration_minutes),
            "continuous": continuous,
            "elapsed_minutes": round(run.elapsed_minutes, 2),
            "cycles_completed": run.cycles_completed,
            "stopped_because": run.stopped_because,
        },
        "transport": {
            "protocol": "RTSP",
            "rtsp_transport": "tcp",
            "timing": "presentation timestamps (PTS); arrival time is never "
                      "used for ordering",
            "reconnect": "exponential backoff with jitter, 2 s initial, 30 s "
                         "cap, per camera",
            "endpoint_template": redact(cfg.rtsp_template),
            "decode_owner": "tools/live/ingest.py (LiveWorker / run_stage); "
                            "this supervisor schedules it and decodes nothing",
        },
        "credentials": {
            "source": "process environment (SENTINEL_GRID_EMAIL / "
                      "SENTINEL_GRID_PASSWORD)",
            "configured": credential_configured(),
            "persisted_anywhere": False,
            "accepted_on_command_line": False,
            "injected": "at socket open, by saakshya.live.credentials."
                        "credentialed(); redact() is applied on every exit",
        },
        "retention": {
            "raw_footage_downloaded": False,
            "recorder_present": False,
            "permitted_artefacts": [dict(a) for a in RETAINED_ARTEFACTS],
            "evidence_footprint": evidence,
            "statement": (
                "No copy of the government footage is made. The grid is live "
                "and not seekable; there is no file download, no byte-range "
                "fetch and no muxer in this path. The only imagery that "
                "reaches disk is the pre-existing bounded alert window and the "
                "single overwritten preview still per camera."),
        },
        "public_exposure": {
            "requested": bool(public_requested or tunnel_requested),
            "granted": False,
            "tunnel": None,
            "reason": (public_exposure_refusal(public=public_requested,
                                               tunnel=tunnel_requested)
                       or "not requested; the supervisor exposes no listener "
                          "and opens no tunnel"),
            "source_rules": list(SOURCE_RULES),
        },
        "dataset": {
            "before": dataset_before,
            "after": dataset_after,
            "growth": grew,
        },
        "coverage": run.coverage(),
        "totals": run.totals(),
        "plan_preview": plan_preview or [],
        "batches": [b.to_dict() for b in run.batches],
    }


def write_report(path: Path, report: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Bounded, metadata-only collection across the registered "
                    "government estate.")
    ap.add_argument("--db", default="sqlite:///var/live.db",
                    help="live store; kept separate from synthetic and demo "
                         "state")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH,
                    help=f"cameras held open at once ({MIN_BATCH}-{MAX_BATCH}; "
                         f"default {DEFAULT_BATCH})")
    ap.add_argument("--dwell-minutes", type=float,
                    default=DEFAULT_DWELL_MINUTES,
                    help="how long each batch is held before the rotation "
                         "moves on")
    ap.add_argument("--settle-seconds", type=float, default=DEFAULT_SETTLE_S,
                    help="quiet time between batches")
    ap.add_argument("--duration-minutes", type=float, default=30.0,
                    help="total collection time; ignored with --continuous")
    ap.add_argument("--continuous", action="store_true",
                    help="rotate until interrupted (Ctrl-C). The current batch "
                         "finishes its dwell so sessions close cleanly.")
    ap.add_argument("--max-cycles", type=int, default=None,
                    help="stop after this many full passes over the roster")
    ap.add_argument("--cameras", type=int, default=None,
                    help="limit the roster to the first N registered cameras")
    ap.add_argument("--only", default=None,
                    help="comma-separated camera ids to collect from")
    ap.add_argument("--tier", default=None,
                    help="override the measured tier for every camera")
    ap.add_argument("--fps-budget", type=float, default=DEFAULT_FPS_BUDGET,
                    help="total analysed frames per second this host can serve")
    ap.add_argument("--allow-discovery", action="store_true",
                    help="fall back to the catalogue and probe when the "
                         "registry is empty. Off by default: collection runs "
                         "against the estate already onboarded.")
    ap.add_argument("--profile", type=Path,
                    default=ROOT / "var" / "reports"
                            / "live_camera_profile.json")
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT,
                    help="where the provenance report is written")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the rotation plan and the bounds, write the "
                         "provenance report, and open no stream")
    # Present so the refusal is explicit and documented rather than a missing
    # feature an operator works around with a second terminal.
    ap.add_argument("--public", action="store_true",
                    help="refused: re-publishing an authenticated government "
                         "feed is outside the access this deployment holds")
    ap.add_argument("--tunnel", default=None,
                    help="refused: no ngrok, no reverse tunnel, no public "
                         "listener — see the printed reason")
    return ap


def roster_for(store: Store, args: argparse.Namespace, cfg: GridConfig
               ) -> tuple[list[LiveCamera], dict[str, Any]]:
    """The cameras this run will rotate over, and where they came from.

    Registry first and, by default, registry only. Collection is defined over
    "the estate we have onboarded"; spending the first minutes of every run
    rediscovering thirty cameras we already hold is time the grid is not being
    watched, and it is a network call this tool does not need to make.
    """
    cams = from_registry(store)
    source: dict[str, Any] = {
        "source": "registry",
        "caveat": "the estate already onboarded; this run does not re-probe "
                  "the grid and cannot detect a changed estate"}
    if not cams and args.allow_discovery:
        cams, source = load_cameras(cfg, store, prefer_registry=False)
    if args.only:
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        cams = [c for c in cams if c.camera_id in wanted]
        source = {**source, "filter": f"--only {args.only}"}
    if args.cameras is not None:
        cams = cams[:max(0, args.cameras)]
        source = {**source, "limit": args.cameras}
    return cams, source


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = GridConfig.from_env()
    store = Store(args.db)
    store.create_all()
    cams, roster_source = roster_for(store, args, cfg)

    problems = preflight(
        db_url=args.db, batch_size=args.batch_size,
        dwell_minutes=args.dwell_minutes,
        duration_minutes=args.duration_minutes, continuous=args.continuous,
        cameras=cams, public=args.public, tunnel=args.tunnel)
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
            print("", file=sys.stderr)
        return 2

    profile = None
    if args.profile.is_file():
        data = json.loads(args.profile.read_text())
        profile = {c["camera_id"]: c for c in data.get("cameras", [])}
    tiers = {c.camera_id: (args.tier or tier_for(c.camera_id, profile))
             for c in cams}

    size, batch_reason = fit_batch_size(args.batch_size, tiers, args.fps_budget)
    roster_ids = [c.camera_id for c in cams]
    plan_preview = rotation_plan(roster_ids, size, cycle=0)

    print(f"provenance : {PROVENANCE}")
    print(f"roster     : {len(cams)} cameras ({roster_source['source']})")
    print(f"batch      : {size} at a time (ceiling {MAX_BATCH}) — "
          f"{batch_reason}")
    print(f"dwell      : {args.dwell_minutes:.2f} min, settle "
          f"{args.settle_seconds:.0f}s")
    print("duration   : " + ("continuous until interrupted" if args.continuous
                             else f"{args.duration_minutes:.0f} min"))
    print("retention  : metadata only — observations, alerts, health, and the "
          "existing bounded alert-evidence window")
    print(f"first cycle: {len(plan_preview)} batches — "
          + " | ".join(",".join(b) for b in plan_preview[:6])
          + (" | …" if len(plan_preview) > 6 else ""))

    dataset_before = store.stats()

    def report_now(run: CollectionRun, *, executed: bool = True
                   ) -> dict[str, Any]:
        return build_report(
            run=run, cameras=cams, roster_source=roster_source, tiers=tiers,
            cfg=cfg, db_url=args.db, batch_size=size,
            batch_size_requested=args.batch_size, batch_reason=batch_reason,
            dwell_minutes=args.dwell_minutes, settle_s=args.settle_seconds,
            duration_minutes=args.duration_minutes,
            continuous=args.continuous, max_cycles=args.max_cycles,
            fps_budget=args.fps_budget, dataset_before=dataset_before,
            dataset_after=store.stats(), evidence=evidence_footprint(),
            public_requested=args.public, tunnel_requested=args.tunnel,
            executed=executed, plan_preview=plan_preview)

    if args.dry_run:
        run = CollectionRun(started_at=datetime.now(UTC).isoformat(),
                            finished_at=datetime.now(UTC).isoformat(),
                            stopped_because="dry run; no stream was opened")
        path = write_report(args.out, report_now(run, executed=False))
        print(f"\ndry run    : no stream opened. Plan and bounds written to "
              f"{path}")
        return 0

    stopping = {"now": False}

    def _stop(*_: Any) -> None:
        if not stopping["now"]:
            print("\n    stopping after this batch — the open sessions are "
                  "closed cleanly rather than dropped", flush=True)
        stopping["now"] = True

    signal.signal(signal.SIGINT, _stop)

    def after_batch(run: CollectionRun) -> None:
        b = run.batches[-1]
        streamed = f"{b.cameras_streamed}/{len(b.camera_ids)}"
        print(f"    batch {b.index:>3} cycle {b.cycle:>2}  "
              f"{','.join(b.camera_ids):<40} "
              f"streamed={streamed:<5} "
              f"obs={b.observations:<6} alerts={b.alerts_raised:<3} "
              f"frames={b.frames_delivered:,}", flush=True)
        # Written after every batch: a collection that ran for six hours and
        # was then interrupted must still leave a provenance record behind.
        write_report(args.out, report_now(run))

    run = collect(cams, tiers, store, cfg, batch_size=size,
                  dwell_minutes=args.dwell_minutes,
                  settle_s=args.settle_seconds,
                  duration_minutes=args.duration_minutes,
                  continuous=args.continuous, max_cycles=args.max_cycles,
                  should_stop=lambda: stopping["now"], on_batch=after_batch)

    report = report_now(run)
    path = write_report(args.out, report)
    totals = report["totals"]
    cov = report["coverage"]
    growth = report["dataset"]["growth"]
    print(f"\nstopped    : {run.stopped_because}")
    print(f"batches    : {totals['batches']} over {run.cycles_completed} full "
          f"cycle(s), {run.elapsed_minutes:.1f} min")
    print(f"coverage   : {cov['cameras_visited']}/{len(cams)} cameras visited, "
          f"{cov['cameras_that_streamed']} delivered a frame, "
          f"{cov['cameras_that_produced_observations']} produced observations")
    print(f"peak open  : {run.max_concurrent_cameras} RTSP session(s) "
          f"(ceiling {MAX_BATCH})")
    print(f"dataset    : +{growth['observations']} observations, "
          f"+{growth['distinct_plates']} distinct plates, "
          f"+{growth['alerts']} alerts")
    ev = report["retention"]["evidence_footprint"]
    print(f"imagery    : {ev['captures']} bounded alert capture(s), "
          f"{ev['frames']} frame(s), {ev['bytes'] / 1e6:.1f} MB — no footage "
          f"copy was made")
    print(f"provenance : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
