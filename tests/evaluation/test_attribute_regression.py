"""ML regression: attribute accuracy on the LOCAL SYNTHETIC CORPUS.

Guards a defect that was live for three iterations and was invisible to every
unit test: colour was being sampled from the wrong frame and every observation
reported "black". Unit tests passed throughout, because each component was
correct in isolation — the fault was in *which frame* the correct component was
handed.

That is exactly the class of bug an ML regression test exists to catch, so the
thresholds below are deliberately set just under currently-measured performance:
low enough not to be flaky, high enough that reintroducing the defect fails.

These numbers are LOCAL SYNTHETIC CORPUS only. They are not field accuracy and
must never be quoted as such.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av
import pytest

from saakshya.analytics.attributes import colour_agreement
from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig
from saakshya.ingest.frame import Frame

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "var" / "media"
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not (MEDIA / "C-014.mp4").exists(),
    reason="corpus not rendered; run `make media`")

#: Cameras whose optics support a colour reading at all. C-021 carries blur and
#: sensor noise by construction and is excluded from the exact-colour threshold;
#: it is still checked for not fabricating a *contradictory* colour.
CLEAN_CAMERAS = ["C-014", "C-052", "C-061"]
DEGRADED_CAMERAS = ["C-021", "C-033"]


def _decode(cam: str, fps: float = 4.0):
    c = av.open(str(MEDIA / f"{cam}.mp4"))
    s = next(x for x in c.streams if x.type == "video")
    tb = float(s.time_base)
    step, nxt = 1.0 / fps, 0.0
    for f in c.decode(s):
        if f.pts is None:
            continue
        t = float(f.pts) * tb
        if t + 1e-6 < nxt:
            continue
        nxt = t + step
        img = f.to_ndarray(format="bgr24")
        yield Frame(camera_id=cam, segment_id="S1", pts_s=t,
                    t_norm=T0 + timedelta(seconds=t),
                    t_ingest=T0 + timedelta(seconds=t), image=img,
                    width=img.shape[1], height=img.shape[0], codec="h264")
    c.close()


def _run(cam: str):
    p = CameraPipeline(cam, PipelineConfig())
    obs = []
    for fr in _decode(cam):
        obs.extend(p.process(fr))
    obs.extend(p.flush())
    return obs


@pytest.fixture(scope="module")
def truth() -> dict[str, str]:
    gt = json.loads((ROOT / "tests/evaluation/ground_truth.json").read_text())
    return {o["plate"]: o["colour"] for o in gt["observations"]}


@pytest.fixture(scope="module")
def observed() -> dict[str, list]:
    return {cam: _run(cam) for cam in CLEAN_CAMERAS + DEGRADED_CAMERAS}


def test_colour_is_not_uniformly_one_value(observed):
    """The defect signature. Every observation reporting the same colour means
    the sampler is reading background, not vehicles."""
    colours = [o.colour for obs in observed.values() for o in obs if o.colour]
    assert len(colours) >= 5, f"too few coloured observations to judge: {colours}"
    assert len(set(colours)) >= 3, (
        f"colour collapsed to {set(colours)} — attributes are being sampled from "
        f"the wrong region")


def test_colour_accuracy_on_optically_clean_cameras(truth, observed):
    hits = total = 0
    misses = []
    for cam in CLEAN_CAMERAS:
        for o in observed[cam]:
            if not o.plate or o.plate not in truth or not o.colour:
                continue
            total += 1
            if o.colour == truth[o.plate]:
                hits += 1
            else:
                misses.append(f"{cam}/{o.plate}: got {o.colour}, want {truth[o.plate]}")
    assert total >= 4, f"only {total} scorable observations"
    acc = hits / total
    assert acc >= 0.80, f"colour accuracy {acc:.0%} ({hits}/{total}); misses: {misses}"


def test_degraded_camera_reports_a_compatible_colour_not_a_contradictory_one(
        truth, observed):
    """A dark camera reading white as grey is acceptable and is scored as a
    partial match. Reading white as red would poison retrieval."""
    for cam in DEGRADED_CAMERAS:
        for o in observed[cam]:
            if not o.plate or o.plate not in truth or not o.colour:
                continue
            agree = colour_agreement(truth[o.plate], o.colour)
            assert agree > 0.0, (
                f"{cam}/{o.plate}: reported {o.colour} for a "
                f"{truth[o.plate]} vehicle — an incompatible colour, not a "
                f"tolerable degradation")


def test_size_class_is_not_uniformly_one_value(observed):
    types = [o.object_type for obs in observed.values() for o in obs
             if o.object_type and o.object_type != "unknown"]
    assert types, "no size classes produced"
    assert len(set(types)) >= 2, (
        f"size class collapsed to {set(types)} — geometry is being read from the "
        f"wrong box")


def test_no_observation_claims_a_colour_without_a_vehicle_region(observed):
    """Attributes must come from a body region. A tiny box means we do not know."""
    for cam, obs in observed.items():
        for o in obs:
            if o.colour is None or not o.bbox:
                continue
            w = o.bbox[2] - o.bbox[0]
            h = o.bbox[3] - o.bbox[1]
            assert w >= 20 and h >= 15, (
                f"{cam}: colour {o.colour} asserted from a {w:.0f}x{h:.0f} box")
