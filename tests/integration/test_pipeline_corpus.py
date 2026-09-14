"""End-to-end: corpus clips -> pipeline -> observations -> store -> plate search.

This is the first half of the mandatory chain, exercised against real decoded
video rather than mocks.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av
import pytest

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig, persist_pipeline
from saakshya.ingest.frame import Frame
from saakshya.store import SearchFilter, Store

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "var" / "media"
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not (MEDIA / "C-014.mp4").exists(),
    reason="corpus not rendered; run `make media`")


#: Seconds of each clip the integration suite ingests.
#:
#: The corpus is 240 s. Integration tests assert pipeline *behaviour* — distinct
#: vehicles preserved, no fabricated plate, quality separating good cameras from
#: degraded ones — and 90 s contains every scripted vehicle the assertions refer
#: to. The full corpus is still ingested end to end by tests/e2e, which is where
#: coverage of the whole thing belongs.
#:
#: This bound exists because it was measured: at 240 s with a function-scoped
#: fixture the suite re-ingested the corpus once per test and ran for ~50
#: minutes, which is long enough that people stop running it.
CORPUS_SECONDS = 90.0


def decode(clip: str, fps: float = 4.0, segment: str = "SEG1",
           max_seconds: float = CORPUS_SECONDS):
    """Sample by PTS, never by frame index."""
    c = av.open(str(MEDIA / clip))
    s = next(x for x in c.streams if x.type == "video")
    tb = float(s.time_base)
    step, nxt = 1.0 / fps, 0.0
    for f in c.decode(s):
        if f.pts is None:
            continue
        t = float(f.pts) * tb
        if t > max_seconds:
            break
        if t + 1e-6 < nxt:
            continue
        nxt = t + step
        img = f.to_ndarray(format="bgr24")
        yield Frame(camera_id=clip[:5], segment_id=segment, pts_s=t,
                    t_norm=T0 + timedelta(seconds=t), t_ingest=T0 + timedelta(seconds=t),
                    image=img, width=img.shape[1], height=img.shape[0], codec="h264")
    c.close()


def run_camera(cam: str, store: Store, fps: float = 4.0, **kw) -> list:
    p = CameraPipeline(cam, PipelineConfig(), **kw)
    out = []
    for fr in decode(f"{cam}.mp4", fps):
        out.extend(p.process(fr))
    out.extend(p.flush())
    persist_pipeline(store, out, p)
    return out


#: Camera metadata for the ingest below. District and department are carried
#: because observations denormalise them at write time.
CAMERA_META = {
    "C-014": ("Ahmedabad", "Home (Traffic)"),
    "C-021": ("Ahmedabad", "GSRTC"),
    "C-033": ("Gandhinagar", "Panchayat"),
    "C-047": ("Gandhinagar", "Municipal"),
    "C-052": ("Ahmedabad", "Health"),
    "C-061": ("Ahmedabad", "Home (Police)"),
}


@pytest.fixture(scope="module")
def corpus() -> dict:
    """Ingest every camera exactly once; every test reads the same world.

    Previously each test ran the pipeline for the cameras it needed, so C-014
    was decoded three times and C-033 three times. Decoding is the expensive
    part and none of that repetition bought coverage.
    """
    store = _registry()
    by_camera: dict[str, list] = {}
    for cam, (district, department) in CAMERA_META.items():
        if not (MEDIA / f"{cam}.mp4").exists():
            continue
        by_camera[cam] = run_camera(cam, store, district=district,
                                    department=department)
    return {"store": store, "obs": by_camera}


def _registry() -> Store:
    s = Store("sqlite:///:memory:")
    s.create_all()
    cat = json.loads((MEDIA / "catalogue.json").read_text())
    for c in cat["cameras"]:
        s.upsert_camera({"camera_id": c["id"], "name": c["name"],
                         "department": c["department"], "district": c["district"],
                         "lat": c["location"]["lat"], "lon": c["location"]["lon"]})
    return s


def test_multi_vehicle_camera_preserves_distinct_vehicles(corpus):
    """THE regression this pipeline exists to fix.

    C-014 carries several distinct vehicles. Per-camera plate voting collapsed
    them to one published plate. Per-track voting must keep them separate.
    """
    obs = corpus["obs"]["C-014"]
    plates = {o.plate for o in obs if o.plate}
    assert len(obs) >= 2, f"expected multiple observations, got {len(obs)}"
    assert len(plates) >= 2, (
        f"multi-vehicle collapse regressed: only {plates} recovered from C-014")


def test_target_is_findable_by_plate_across_cameras(corpus):
    """The mandatory query: plate in, observations out, across cameras."""
    hits = corpus["store"].search_plate("GJ05AB1234")
    cams = {o.camera_id for o in hits}
    assert len(cams) >= 2, f"target found on only {cams}; cross-camera search failed"
    # Results must be in normalised-time order — the timeline depends on it.
    ts = [o.t_norm for o in hits]
    assert ts == sorted(ts)


def test_degraded_camera_emits_observations_without_asserting_a_plate(corpus):
    """C-033 must still produce observations — appearance is what makes the
    unreadable-plate case recoverable. It must not invent a plate."""
    obs = corpus["obs"]["C-033"]
    assert obs, "degraded camera produced no observations at all"
    asserted = [o for o in obs if o.plate]
    assert not asserted, f"C-033 fabricated plates: {[o.plate for o in asserted]}"
    assert any(o.observation_quality is not None for o in obs)


def test_observation_quality_separates_good_from_degraded_cameras(corpus):
    good = corpus["obs"]["C-014"]
    bad = corpus["obs"]["C-033"]
    gq = [o.observation_quality for o in good if o.observation_quality is not None]
    bq = [o.observation_quality for o in bad if o.observation_quality is not None]
    assert gq and bq
    assert sum(gq) / len(gq) > sum(bq) / len(bq), (
        "quality metric fails to separate a clean camera from a degraded one")


def test_no_false_plate_on_any_camera(corpus):
    """Across the whole corpus, every published plate must be a real one."""
    store = corpus["store"]
    truth = json.loads((ROOT / "tests/evaluation/ground_truth.json").read_text())
    real = {o["plate"] for o in truth["observations"]}
    published = {o.plate for o in store.search(SearchFilter(limit=5000)) if o.plate}
    assert published <= real, f"fabricated plates: {published - real}"
