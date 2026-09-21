"""The bounded metadata-only collection supervisor.

Everything here runs without a grid. The supervisor's whole job is *scheduling*
— which cameras are open, how many at once, for how long, and what is allowed to
reach disk — so the properties worth testing are exactly the ones a network run
would obscure rather than demonstrate. The decode path is `run_stage`'s and is
covered where it lives; here it is replaced by a recorder that remembers what it
was asked to open.

The load bound is the point of the tool, so it is asserted from three angles:
the refusal that rejects an out-of-range request, the plan that never emits an
over-size batch, and the run that never holds more sessions than it promised.
"""
from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from saakshya.live import GridConfig, LiveCamera
from tools.live.collect import (
    MAX_BATCH,
    MIN_DWELL_MINUTES,
    BoundsError,
    CollectionRun,
    build_report,
    check_batch_size,
    check_dwell,
    collect,
    evidence_footprint,
    fit_batch_size,
    main,
    preflight,
    public_exposure_refusal,
    rotation_plan,
)
from tools.live.ingest import StageResult

MODULE = Path(__file__).resolve().parents[2] / "tools" / "live" / "collect.py"

LOOPBACK = "rtsp://127.0.0.1:8554/stream/{id}"
GOVERNMENT = "rtsp://103.250.160.189:8554/stream/{id}"


def ids(n: int) -> list[str]:
    return [f"cam{i:02d}" for i in range(1, n + 1)]


def cameras(n: int, template: str = LOOPBACK) -> list[LiveCamera]:
    return [LiveCamera(camera_id=c, rtsp_url=template.format(id=c))
            for c in ids(n)]


class Recorder:
    """A stand-in for `run_stage` that records what it was handed.

    It also asserts it is never re-entered: the load bound depends on batches
    being sequential, and a supervisor that started the next batch before the
    previous one's workers had joined would hold twice the sessions while every
    batch still looked the right size.
    """

    def __init__(self, *, observations: int = 3, frames: int = 100,
                 advance: float = 0.0, clock: "Clock | None" = None) -> None:
        self.batches: list[list[str]] = []
        self.minutes: list[float] = []
        self.inside = False
        self.observations = observations
        self.frames = frames
        self.advance = advance
        self.clock = clock

    def __call__(self, cams, tiers, store, cfg, *, minutes):
        assert not self.inside, "batches must not overlap"
        self.inside = True
        try:
            self.batches.append([c.camera_id for c in cams])
            self.minutes.append(minutes)
            if self.clock is not None:
                self.clock.tick(self.advance or minutes * 60)
            res = StageResult(cameras=len(cams), minutes=minutes)
            res.observations = self.observations * len(cams)
            res.stats = [
                {"camera_id": c.camera_id, "frames": self.frames,
                 "frames_analysed": self.frames // 10,
                 "observations": self.observations, "reconnects": 0,
                 "state": "STOPPED", "last_error": None}
                for c in cams]
            return res
        finally:
            self.inside = False


class Clock:
    """A clock the test moves by hand, so a two-hour rotation costs no seconds."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


# --------------------------------------------------------------------------- #
# Bounds.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("size", [1, 2, 3, 4, 5])
def test_batch_size_within_bounds_is_accepted(size):
    assert check_batch_size(size) == size


@pytest.mark.parametrize("size", [0, -1, 6, 30])
def test_batch_size_outside_bounds_is_refused_not_clamped(size):
    """Refused, with the ceiling named. A silent clamp would leave an operator
    believing they were running thirty cameras at once."""
    with pytest.raises(BoundsError) as exc:
        check_batch_size(size)
    assert str(MAX_BATCH) in str(exc.value)
    assert "own copy of the stream" in str(exc.value)


def test_dwell_below_the_measured_floor_is_refused():
    with pytest.raises(BoundsError) as exc:
        check_dwell(0.1)
    assert "9.5 s" in str(exc.value)
    assert check_dwell(MIN_DWELL_MINUTES) == MIN_DWELL_MINUTES


def test_fit_batch_size_keeps_the_tier_promise():
    """Five T2 cameras ask 15 analysed fps; a 12 fps host can serve four."""
    size, why = fit_batch_size(5, {c: "T2" for c in ids(30)}, 12.0)
    assert size == 4
    assert "reduced from 5 to 4" in why

    # Cheap cameras do not need the reduction.
    size, why = fit_batch_size(5, {c: "T0" for c in ids(30)}, 12.0)
    assert size == 5
    assert "fits" in why

    # The worst tier in the roster governs, because which batch collects the
    # expensive cameras depends on the rotation offset.
    mixed = {c: "T0" for c in ids(30)} | {"cam07": "T3"}
    size, _ = fit_batch_size(5, mixed, 12.0)
    assert size == 2


def test_fit_batch_size_never_returns_zero():
    size, _ = fit_batch_size(5, {c: "T3" for c in ids(30)}, 1.0)
    assert size == 1


# --------------------------------------------------------------------------- #
# The rotation plan.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("roster", [1, 3, 7, 30])
@pytest.mark.parametrize("size", [1, 2, 3, 4, 5])
def test_a_cycle_covers_every_camera_exactly_once(roster, size):
    plan = rotation_plan(ids(roster), size)
    flat = [c for batch in plan for c in batch]
    assert sorted(flat) == sorted(ids(roster))
    assert len(flat) == len(set(flat))


@pytest.mark.parametrize("roster", [1, 3, 7, 30])
@pytest.mark.parametrize("size", [1, 2, 3, 4, 5])
def test_no_batch_ever_exceeds_the_requested_size_or_the_ceiling(roster, size):
    for cycle in range(4):
        for batch in rotation_plan(ids(roster), size, cycle=cycle):
            assert 1 <= len(batch) <= size <= MAX_BATCH


def test_each_cycle_starts_somewhere_else():
    """Otherwise the first registered camera collects every partial cycle's
    attention and the last one none — a bias in the dataset, not a detail."""
    firsts = {rotation_plan(ids(30), 5, cycle=c)[0][0] for c in range(6)}
    assert len(firsts) == 6


def test_every_camera_leads_a_cycle_eventually():
    leaders = {rotation_plan(ids(30), 1, cycle=c)[0][0] for c in range(30)}
    assert leaders == set(ids(30))


def test_rotation_plan_refuses_an_over_size_batch():
    with pytest.raises(BoundsError):
        rotation_plan(ids(30), 6)


def test_empty_roster_plans_nothing():
    assert rotation_plan([], 5) == []


# --------------------------------------------------------------------------- #
# Public exposure.
# --------------------------------------------------------------------------- #

def test_no_refusal_when_nothing_public_was_asked_for():
    assert public_exposure_refusal() is None
    assert public_exposure_refusal(public=False, tunnel=None) is None


@pytest.mark.parametrize("kwargs", [
    {"public": True},
    {"tunnel": "https://nnnn-nn-nn.ngrok-free.app"},
    {"tunnel": "https://example.invalid/relay"},
])
def test_public_and_tunnel_modes_are_declined_with_the_source_rule(kwargs):
    refusal = public_exposure_refusal(**kwargs)
    assert refusal is not None
    assert refusal.startswith("REFUSED")
    # The reason is the source's own rule, quoted, not a preference.
    assert "Consume only" in refusal
    assert "ngrok" in refusal
    assert "re-publishes an authenticated government feed" in refusal


def test_the_cli_exposes_the_flags_only_to_refuse_them(tmp_path, monkeypatch):
    """A refusal an operator can discover beats a missing feature they work
    around with a second terminal."""
    db = f"sqlite:///{tmp_path / 'live.db'}"
    monkeypatch.chdir(tmp_path)
    code = main(["--db", db, "--tunnel", "https://x.ngrok-free.app",
                 "--dry-run", "--profile", str(tmp_path / "none.json"),
                 "--out", str(tmp_path / "r.json")])
    assert code == 2
    assert not (tmp_path / "r.json").exists()


# --------------------------------------------------------------------------- #
# Preflight.
# --------------------------------------------------------------------------- #

def clean_preflight(**over):
    kwargs = {"db_url": "sqlite:///var/live.db", "batch_size": 5,
              "dwell_minutes": 2.0, "duration_minutes": 30.0,
              "continuous": False, "cameras": cameras(5),
              "credential_present": True}
    kwargs.update(over)
    return preflight(**kwargs)


def test_a_sound_request_has_no_problems():
    assert clean_preflight() == []


@pytest.mark.parametrize("protected", ["sqlite:///var/demo.db",
                                       "sqlite:///var/saakshya.db"])
def test_preflight_keeps_live_capture_out_of_demo_and_evaluation_stores(protected):
    problems = clean_preflight(db_url=protected)
    assert any("Provenance is never mixed" in p for p in problems)


def test_preflight_refuses_an_authenticating_grid_with_no_credential():
    problems = clean_preflight(cameras=cameras(3, GOVERNMENT),
                               credential_present=False)
    assert any("SENTINEL_GRID_EMAIL" in p for p in problems)
    assert any("never read from a file" in p for p in problems)


def test_loopback_needs_no_credential():
    assert clean_preflight(cameras=cameras(3, LOOPBACK),
                           credential_present=False) == []


def test_preflight_requires_a_duration_or_continuous():
    assert any("--duration-minutes" in p
               for p in clean_preflight(duration_minutes=0))
    assert clean_preflight(duration_minutes=0, continuous=True) == []


def test_preflight_reports_every_problem_at_once():
    problems = clean_preflight(db_url="sqlite:///var/demo.db", batch_size=12,
                               dwell_minutes=0.01, cameras=[])
    assert len(problems) >= 4


# --------------------------------------------------------------------------- #
# The run.
# --------------------------------------------------------------------------- #

def run_collection(*, roster=30, batch_size=5, dwell=2.0,
                   duration=60.0, **over):
    clock = Clock()
    rec = Recorder(clock=clock)
    kwargs = {"batch_size": batch_size, "dwell_minutes": dwell,
              "settle_s": 0.0, "duration_minutes": duration,
              "runner": rec, "clock": clock,
              "sleep": clock.tick}
    kwargs.update(over)
    run = collect(cameras(roster), {}, None, GridConfig(), **kwargs)
    return run, rec, clock


def test_the_estate_is_never_opened_all_at_once():
    run, rec, _ = run_collection(roster=30, batch_size=5, duration=300.0)
    assert rec.batches, "the run opened nothing at all"
    assert max(len(b) for b in rec.batches) <= 5
    assert run.max_concurrent_cameras <= MAX_BATCH
    # Thirty cameras were covered, but never simultaneously.
    assert run.coverage()["cameras_visited"] == 30


def test_a_completed_cycle_visits_every_camera_once():
    run, rec, _ = run_collection(roster=30, batch_size=5, dwell=1.0,
                                 max_cycles=1, duration=10_000.0)
    assert run.cycles_completed == 1
    visits = run.coverage()["visits_per_camera"]
    assert set(visits) == set(ids(30))
    assert set(visits.values()) == {1}


def test_repeated_cycles_keep_coverage_even():
    run, _, _ = run_collection(roster=30, batch_size=5, dwell=1.0,
                               max_cycles=4, duration=10_000.0)
    cov = run.coverage()
    assert run.cycles_completed == 4
    assert cov["least_visited"] == cov["most_visited"] == 4


def test_a_connected_camera_that_delivered_nothing_is_not_counted_as_streamed():
    """A worker reaches `STREAMING` the moment its RTSP session opens, before a
    single frame has been decoded. If that connection then stalls for the whole
    dwell, the camera was never denied — it just never streamed anything. The
    console the operator watches mid-run counts by that connection state, so it
    can report `5/5` for a batch where the final per-camera tally has only two
    cameras with any frames at all. `coverage()` and each batch's own
    `cameras_streamed` must both go by frames delivered, not by that state, and
    must agree with each other."""
    clock = Clock()
    # cam09, cam24, cam27, cam28 and cam30 connect (`STREAMING`) but never
    # decode a frame — the exact shape of a real run where the last batch's
    # console line read `streaming=5/5 frames=485` while only cam26 and cam29
    # (of cam26-cam30) had actually produced any of it.
    stalled = {"cam09", "cam24", "cam27", "cam28", "cam30"}

    class PartialRecorder(Recorder):
        def __call__(self, cams, tiers, store, cfg, *, minutes):
            res = super().__call__(cams, tiers, store, cfg, minutes=minutes)
            for s in res.stats:
                if s["camera_id"] in stalled:
                    s["frames"] = 0
                    s["state"] = "STREAMING"
            return res

    run = collect(cameras(30), {}, None, GridConfig(), batch_size=5,
                  dwell_minutes=2.0, settle_s=0.0, duration_minutes=10_000.0,
                  max_cycles=1, runner=PartialRecorder(clock=clock, frames=97),
                  clock=clock, sleep=clock.tick)

    last = run.batches[-1]
    assert last.camera_ids == ["cam26", "cam27", "cam28", "cam29", "cam30"]
    # The batch delivered frames (97 * 2 = 194), so a reader glancing only at
    # the aggregate would assume the whole batch worked.
    assert last.frames_delivered == 194
    # But only two of the five cameras in it actually produced any of that.
    assert last.cameras_streamed == 2
    assert last.to_dict()["cameras_streamed"] == 2

    cov = run.coverage()
    assert cov["cameras_visited"] == 30
    # 5 of 30 cameras across the run connected and delivered nothing; the
    # reliable count excludes them rather than crediting the connection.
    assert cov["cameras_that_streamed"] == 25
    # The run-level figure is exactly the sum of each batch's own reliable
    # count — the two numbers cannot drift apart because both are computed by
    # the same frames-based rule.
    assert cov["cameras_that_streamed"] == sum(
        b.cameras_streamed for b in run.batches)


def test_a_bounded_run_stops_at_the_requested_duration():
    run, rec, clock = run_collection(roster=30, batch_size=5, dwell=2.0,
                                     duration=10.0)
    # Five batches of two minutes is the ten minutes asked for, and no more.
    assert len(rec.batches) == 5
    assert clock.now <= 1_000.0 + 10 * 60 + 1e-6
    assert "duration" in run.stopped_because


def test_the_tail_of_a_run_is_not_a_connection_that_collects_nothing():
    """Ten minutes and a bit, at a two-minute dwell, leaves 24 seconds. A final
    batch would be mostly the 9.5 s connect, so the run ends and says why."""
    run, rec, _ = run_collection(roster=30, batch_size=5, dwell=2.0,
                                 duration=10.4)
    assert all(m >= MIN_DWELL_MINUTES for m in rec.minutes)
    assert len(rec.batches) == 5
    assert "dwell floor" in run.stopped_because


def test_a_run_with_no_room_left_ends_instead_of_spinning():
    """The failure this guards against opens no camera and moves no clock, so
    it does not look like a busy loop — it looks like a hang. `should_stop` is
    consulted once per pass, which makes the spin countable."""
    clock = Clock()
    passes = {"n": 0}

    def should_stop():
        passes["n"] += 1
        assert passes["n"] < 50, ("the supervisor is going round without "
                                  "opening a camera or advancing the clock")
        return False

    run = collect(cameras(30), {}, None, GridConfig(), batch_size=5,
                  dwell_minutes=2.0, settle_s=0.0, duration_minutes=10.4,
                  runner=Recorder(clock=clock), clock=clock, sleep=clock.tick,
                  should_stop=should_stop)
    assert run.stopped_because.startswith("duration reached")


def test_a_partial_final_batch_is_shortened_rather_than_overrunning():
    run, rec, clock = run_collection(roster=30, batch_size=5, dwell=2.0,
                                     duration=5.0)
    assert rec.minutes == [2.0, 2.0, 1.0]
    assert clock.now == pytest.approx(1_000.0 + 5 * 60)


def test_continuous_mode_runs_until_it_is_interrupted():
    clock = Clock()
    rec = Recorder(clock=clock)
    stop = {"now": False}

    def should_stop():
        # Three batches in, the operator presses Ctrl-C.
        if len(rec.batches) >= 3:
            stop["now"] = True
        return stop["now"]

    run = collect(cameras(30), {}, None, GridConfig(), batch_size=5,
                  dwell_minutes=2.0, settle_s=0.0, continuous=True,
                  runner=rec, clock=clock, sleep=clock.tick,
                  should_stop=should_stop)
    assert len(rec.batches) == 3
    assert run.stopped_because == "interrupted"
    assert run.cycles_completed == 0


def test_continuous_mode_keeps_rotating_past_a_full_cycle():
    clock = Clock()
    rec = Recorder(clock=clock)
    run = collect(cameras(10), {}, None, GridConfig(), batch_size=5,
                  dwell_minutes=1.0, settle_s=0.0, continuous=True,
                  max_cycles=3, runner=rec, clock=clock, sleep=clock.tick,
                  should_stop=lambda: False)
    assert len(rec.batches) == 6
    assert run.cycles_completed == 3
    assert "max cycles" in run.stopped_because


def test_settle_time_is_spent_between_batches_not_inside_them():
    clock = Clock()
    rec = Recorder(clock=clock)
    slept: list[float] = []

    def sleeper(s):
        slept.append(s)
        clock.tick(s)

    collect(cameras(4), {}, None, GridConfig(), batch_size=2,
            dwell_minutes=1.0, settle_s=15.0, duration_minutes=1_000.0,
            max_cycles=1, runner=rec, clock=clock, sleep=sleeper)
    assert slept == [15.0, 15.0]


def test_a_report_is_written_after_every_batch():
    """A collection interrupted after six hours must still leave provenance."""
    seen: list[int] = []
    clock = Clock()
    rec = Recorder(clock=clock)
    collect(cameras(10), {}, None, GridConfig(), batch_size=5,
            dwell_minutes=1.0, settle_s=0.0, duration_minutes=1_000.0,
            max_cycles=1, runner=rec, clock=clock, sleep=clock.tick,
            on_batch=lambda run: seen.append(len(run.batches)))
    assert seen == [1, 2]


def test_an_empty_roster_is_not_a_run():
    run = collect([], {}, None, GridConfig(), batch_size=5,
                  dwell_minutes=1.0, duration_minutes=10.0,
                  runner=Recorder(), clock=Clock(), sleep=lambda _: None)
    assert run.batches == []
    assert run.stopped_because == "no cameras in the roster"


# --------------------------------------------------------------------------- #
# Provenance.
# --------------------------------------------------------------------------- #

def a_report(**over):
    run, _, _ = run_collection(roster=10, batch_size=5, dwell=1.0,
                               max_cycles=1, duration=10_000.0)
    kwargs = dict(
        run=run, cameras=cameras(10), roster_source={"source": "registry"},
        tiers={c: "T1" for c in ids(10)}, cfg=GridConfig(),
        db_url="sqlite:///var/live.db", batch_size=5, batch_size_requested=5,
        batch_reason="fits", dwell_minutes=1.0, settle_s=10.0,
        duration_minutes=60.0, continuous=False, max_cycles=None,
        fps_budget=12.0,
        dataset_before={"observations": 10, "distinct_plates": 2, "alerts": 0,
                        "observations_with_plate": 4,
                        "raw_ocr_read_records": 6},
        dataset_after={"observations": 60, "distinct_plates": 9, "alerts": 1,
                       "observations_with_plate": 20,
                       "raw_ocr_read_records": 31},
        evidence={"root": "var/live_evidence/rolling", "captures": 1,
                  "frames": 12, "bytes": 240_000, "present": True})
    kwargs.update(over)
    return build_report(**kwargs)


def test_the_report_states_the_bound_that_was_actually_held():
    report = a_report()
    bounds = report["bounds"]
    assert bounds["batch_size_ceiling"] == MAX_BATCH
    assert bounds["max_concurrent_rtsp_sessions"] <= MAX_BATCH
    assert bounds["ceiling_respected"] is True


def test_the_report_is_metadata_only_and_names_what_may_reach_disk():
    retention = a_report()["retention"]
    assert retention["raw_footage_downloaded"] is False
    assert retention["recorder_present"] is False
    kinds = {a["kind"] for a in retention["permitted_artefacts"]}
    assert kinds == {"observations", "plate_reads", "alerts", "camera_health",
                     "alert_evidence", "preview_still"}
    # The two artefacts that are imagery are declared as bounded, and the
    # footprint is measured rather than asserted to be empty.
    for artefact in retention["permitted_artefacts"]:
        if artefact["media"]:
            assert artefact["bounded"] is True
    assert retention["evidence_footprint"]["frames"] == 12


def test_the_report_shows_the_dataset_growing():
    growth = a_report()["dataset"]["growth"]
    assert growth["observations"] == 50
    assert growth["distinct_plates"] == 7
    assert growth["alerts"] == 1


def test_the_report_records_a_refused_exposure_rather_than_omitting_it():
    exposure = a_report(tunnel_requested="https://x.ngrok-free.app")[
        "public_exposure"]
    assert exposure["requested"] is True
    assert exposure["granted"] is False
    assert exposure["tunnel"] is None
    assert "REFUSED" in exposure["reason"]
    assert exposure["source_rules"]


def test_the_report_carries_no_credential_and_no_authority():
    """`redact` is applied on every exit. A report is an exit — it gets read,
    attached to a ticket and pasted into a chat."""
    run, _, _ = run_collection(roster=4, batch_size=2, dwell=1.0,
                               max_cycles=1, duration=10_000.0)
    # A worker error that slipped an authority through unredacted.
    run.batches[0].per_camera[0]["last_error"] = (
        "ConnectionError: rtsp://user@example.org:SECRET-PASS-WORD@host/s/cam01")
    report = a_report(run=run)
    blob = json.dumps(report)
    assert "SECRET-PASS-WORD" not in blob
    assert "<redacted>@" in blob


def test_redaction_handles_an_unescaped_email_in_the_authority():
    """The username on this grid may itself be an email address (`a@b.com`),
    so a naive "redact up to the first @" would leave the domain and the
    password exposed. `redact` lives in `saakshya.live.credentials` and this
    supervisor uses it as-is rather than writing a second redaction of its
    own — this only asserts the report actually calls it."""
    run, _, _ = run_collection(roster=2, batch_size=2, dwell=1.0,
                               max_cycles=1, duration=10_000.0)
    run.batches[0].per_camera[0]["last_error"] = (
        "ConnectionError: rtsp://ops@sentinel.gov.in:XXXX-XXXX-XXXX@"
        "103.250.160.189:8554/stream/cam01")
    report = a_report(run=run)
    blob = json.dumps(report)
    assert "XXXX-XXXX-XXXX" not in blob
    assert "ops@sentinel.gov.in" not in blob
    assert "<redacted>@103.250.160.189:8554/stream/cam01" in blob


def test_redaction_happens_as_the_run_records_it_not_only_at_the_end():
    clock = Clock()

    class Leaky(Recorder):
        def __call__(self, cams, tiers, store, cfg, *, minutes):
            res = super().__call__(cams, tiers, store, cfg, minutes=minutes)
            res.stats[0]["last_error"] = "rtsp://a:b@host:8554/stream/cam01"
            return res

    run = collect(cameras(2), {}, None, GridConfig(), batch_size=2,
                  dwell_minutes=1.0, settle_s=0.0, duration_minutes=1_000.0,
                  max_cycles=1, runner=Leaky(clock=clock), clock=clock,
                  sleep=clock.tick)
    assert run.batches[0].per_camera[0]["last_error"] == (
        "rtsp://<redacted>@host:8554/stream/cam01")


def test_evidence_footprint_measures_the_disk_rather_than_trusting_the_run(
        tmp_path):
    assert evidence_footprint(tmp_path / "absent") == {
        "root": str(tmp_path / "absent"), "captures": 0, "frames": 0,
        "bytes": 0, "present": False}

    root = tmp_path / "rolling"
    for obs in ("OBS-1", "OBS-2"):
        d = root / obs
        d.mkdir(parents=True)
        for i in range(3):
            (d / f"{i:03d}_pts0.000.jpg").write_bytes(b"x" * 100)
    # A capture that held no frames writes no directory content and must not
    # be counted as retained imagery.
    (root / "OBS-3").mkdir()

    found = evidence_footprint(root)
    assert found["captures"] == 2
    assert found["frames"] == 6
    assert found["bytes"] == 600
    assert found["present"] is True


# --------------------------------------------------------------------------- #
# The tool as an operator meets it.
# --------------------------------------------------------------------------- #

@pytest.fixture
def onboarded(tmp_path):
    """A live store with an onboarded estate on loopback, and nothing else."""
    from saakshya.store import Store

    url = f"sqlite:///{tmp_path / 'live.db'}"
    store = Store(url)
    store.create_all()
    for cam in ids(12):
        store.upsert_camera({"camera_id": cam,
                             "rtsp_url": LOOPBACK.format(id=cam),
                             "enabled": True, "tier": "UNASSIGNED"})
    return url


def test_dry_run_shows_the_plan_and_opens_nothing(onboarded, tmp_path,
                                                  monkeypatch, capsys):
    import tools.live.collect as collect_mod

    def refuse(*a, **kw):
        raise AssertionError("a dry run must not open a stream")

    monkeypatch.setattr(collect_mod, "run_stage", refuse)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "provenance.json"
    code = main(["--db", onboarded, "--dry-run", "--duration-minutes", "60",
                 "--profile", str(tmp_path / "absent.json"),
                 "--out", str(out)])
    assert code == 0

    report = json.loads(out.read_text())
    assert report["executed"] is False
    assert report["provenance"] == "GOVERNMENT_LIVE"
    assert report["roster"]["cameras"] == 12
    assert report["batches"] == []
    # The plan is the operator's evidence that the estate gets covered without
    # being opened at once.
    plan = report["plan_preview"]
    assert sorted(c for b in plan for c in b) == sorted(ids(12))
    assert all(len(b) <= MAX_BATCH for b in plan)
    assert "no stream opened" in capsys.readouterr().out


def test_a_full_run_covers_the_estate_in_bounded_batches(onboarded, tmp_path,
                                                         monkeypatch):
    import tools.live.collect as collect_mod

    rec = Recorder()
    monkeypatch.setattr(collect_mod, "run_stage", rec)
    monkeypatch.chdir(tmp_path)
    handler = signal.getsignal(signal.SIGINT)
    out = tmp_path / "provenance.json"
    try:
        code = main(["--db", onboarded, "--batch-size", "3",
                     "--dwell-minutes", "0.5", "--settle-seconds", "0",
                     "--duration-minutes", "600", "--max-cycles", "2",
                     "--profile", str(tmp_path / "absent.json"),
                     "--out", str(out)])
    finally:
        signal.signal(signal.SIGINT, handler)
    assert code == 0

    assert [len(b) for b in rec.batches] == [3] * 8
    report = json.loads(out.read_text())
    assert report["executed"] is True
    assert report["bounds"]["max_concurrent_rtsp_sessions"] == 3
    assert report["bounds"]["ceiling_respected"] is True
    assert report["coverage"]["least_visited"] == 2
    assert report["coverage"]["most_visited"] == 2
    assert report["duration"]["cycles_completed"] == 2
    assert report["totals"]["observations"] == 8 * 3 * 3
    assert report["dataset"]["growth"]["observations"] == 0  # nothing written
    assert report["public_exposure"]["granted"] is False


def test_console_reports_frames_delivered_not_connection_state(
        onboarded, tmp_path, monkeypatch, capsys):
    """The batch console line and the closing summary must both grade a camera
    by frames actually decoded, not by `STREAMING` state — the state a worker
    reaches the instant its RTSP session opens, before decoding anything.
    Otherwise an operator reads `streamed=3/3` for a batch that produced
    nothing and only learns the truth later, from the JSON."""
    import tools.live.collect as collect_mod

    class StalledRecorder(Recorder):
        def __call__(self, cams, tiers, store, cfg, *, minutes):
            res = super().__call__(cams, tiers, store, cfg, minutes=minutes)
            for s in res.stats:
                s["frames"] = 0
                s["state"] = "STREAMING"
            return res

    monkeypatch.setattr(collect_mod, "run_stage", StalledRecorder())
    monkeypatch.chdir(tmp_path)
    handler = signal.getsignal(signal.SIGINT)
    out = tmp_path / "provenance.json"
    try:
        code = main(["--db", onboarded, "--batch-size", "3",
                     "--dwell-minutes", "0.5", "--settle-seconds", "0",
                     "--duration-minutes", "600", "--max-cycles", "1",
                     "--profile", str(tmp_path / "absent.json"),
                     "--out", str(out)])
    finally:
        signal.signal(signal.SIGINT, handler)
    assert code == 0

    text = capsys.readouterr().out
    assert "streamed=0/3" in text
    assert "streamed=3/3" not in text
    assert "coverage   : 12/12 cameras visited, 0 delivered a frame" in text

    report = json.loads(out.read_text())
    assert report["coverage"]["cameras_that_streamed"] == 0
    assert all(b["cameras_streamed"] == 0 for b in report["batches"])


def test_the_report_survives_an_interrupted_run(onboarded, tmp_path,
                                                monkeypatch):
    """Written after every batch, so six hours of collection are not lost to a
    Ctrl-C at hour six."""
    import tools.live.collect as collect_mod

    out = tmp_path / "provenance.json"
    seen: list[int] = []

    def runner(cams, tiers, store, cfg, *, minutes):
        seen.append(len(cams))
        if len(seen) == 2:
            # The report from batch 1 is already on disk at this point.
            assert json.loads(out.read_text())["totals"]["batches"] == 1
        return StageResult(cameras=len(cams), minutes=minutes)

    monkeypatch.setattr(collect_mod, "run_stage", runner)
    monkeypatch.chdir(tmp_path)
    handler = signal.getsignal(signal.SIGINT)
    try:
        main(["--db", onboarded, "--batch-size", "4", "--dwell-minutes", "0.5",
              "--settle-seconds", "0", "--duration-minutes", "600",
              "--max-cycles", "1", "--profile", str(tmp_path / "absent.json"),
              "--out", str(out)])
    finally:
        signal.signal(signal.SIGINT, handler)
    assert json.loads(out.read_text())["totals"]["batches"] == 3


def test_collection_refuses_an_estate_it_has_no_credential_for(tmp_path,
                                                               monkeypatch,
                                                               capsys):
    from saakshya.store import Store

    url = f"sqlite:///{tmp_path / 'live.db'}"
    store = Store(url)
    store.create_all()
    for cam in ids(3):
        store.upsert_camera({"camera_id": cam,
                             "rtsp_url": GOVERNMENT.format(id=cam),
                             "enabled": True, "tier": "UNASSIGNED"})
    monkeypatch.delenv("SENTINEL_GRID_EMAIL", raising=False)
    monkeypatch.delenv("SENTINEL_GRID_PASSWORD", raising=False)
    monkeypatch.chdir(tmp_path)

    code = main(["--db", url, "--dry-run", "--duration-minutes", "10",
                 "--profile", str(tmp_path / "absent.json"),
                 "--out", str(tmp_path / "r.json")])
    assert code == 2
    assert "SENTINEL_GRID_EMAIL" in capsys.readouterr().err


def test_an_empty_registry_is_refused_rather_than_run(tmp_path, monkeypatch,
                                                      capsys):
    from saakshya.store import Store

    url = f"sqlite:///{tmp_path / 'live.db'}"
    Store(url).create_all()
    monkeypatch.chdir(tmp_path)
    code = main(["--db", url, "--dry-run", "--duration-minutes", "10",
                 "--profile", str(tmp_path / "absent.json"),
                 "--out", str(tmp_path / "r.json")])
    assert code == 2
    assert "not a run" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# What the supervisor is not allowed to contain.
# --------------------------------------------------------------------------- #

def test_the_supervisor_reuses_the_ingest_decoder_rather_than_copying_it():
    source = MODULE.read_text()
    assert "from tools.live.ingest import" in source
    for duplicated in ("container.decode", "class LiveWorker",
                       "frame.to_ndarray", "skip_frame", "time_base",
                       "CameraPipeline"):
        assert duplicated not in source, (
            f"{duplicated!r} is `tools/live/ingest.py`'s behaviour; a second "
            f"copy is a second set of bugs to keep in step with the guide")


def test_the_supervisor_has_no_recorder_in_it():
    """The load-bearing claim of the tool. Asserted against the source, because
    a comment promising metadata-only is not a control."""
    source = MODULE.read_text()
    for forbidden in ("av.open", "add_stream", ".mux(", "open_output",
                      "urlretrieve", "requests.get", "httpx.get",
                      "httpx.stream", "subprocess", "ffmpeg"):
        assert forbidden not in source, (
            f"{forbidden!r} would put a media writer or fetcher in a "
            f"metadata-only path")


def test_the_supervisor_holds_no_credential_and_no_camera_id():
    source = MODULE.read_text()
    assert "SENTINEL_GRID_PASSWORD" in source      # named, for the operator
    # ...but only ever as the name of an environment variable to be set.
    assert "os.environ" not in source
    assert "getenv" not in source
    assert "cam01" not in source, (
        "camera ids come from the catalogue or the registry, never from code")


def test_the_supervisor_does_not_reimplement_url_redaction():
    """Redaction of a stream URL is `saakshya.live.credentials.redact`'s job —
    including the case where the grid's own username is an unescaped email
    address and so itself contains `@`. This tool must call that helper, not
    grow a second regex that could disagree with it."""
    source = MODULE.read_text()
    assert "from saakshya.live.credentials import" in source
    assert "redact" in source
    # No local pattern reaching for an authority or an `@`-delimited username.
    assert "re.compile" not in source
    lines = source.splitlines()
    assert "import re" not in lines
