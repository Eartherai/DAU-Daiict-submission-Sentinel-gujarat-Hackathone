"""Scene-cut detector must fire on cuts and not on traffic."""
import numpy as np

from saakshya.ingest.discontinuity import SceneCutDetector


def _noisy(rng, base):
    return np.clip(base + rng.integers(0, 6, base.shape), 0, 255).astype(np.uint8)


def test_static_scene_with_noise_produces_no_cuts():
    rng = np.random.default_rng(0)
    base = rng.integers(40, 60, (480, 640, 3), dtype=np.uint8)
    d = SceneCutDetector("T")
    for _ in range(40):
        d.update(_noisy(rng, base))
    assert d.cuts == 0


def test_vehicle_entering_is_not_a_cut():
    rng = np.random.default_rng(1)
    base = rng.integers(40, 60, (480, 640, 3), dtype=np.uint8)
    d = SceneCutDetector("T")
    for _ in range(30):
        d.update(_noisy(rng, base))
    veh = base.copy()
    veh[300:400, 200:420] = 235          # a large vehicle, ~14% of frame
    assert d.update(veh) is False
    assert d.last_fraction < 0.4


def test_scene_cut_fires_once():
    rng = np.random.default_rng(2)
    a = rng.integers(30, 60, (480, 640, 3), dtype=np.uint8)
    b = rng.integers(150, 200, (480, 640, 3), dtype=np.uint8)
    d = SceneCutDetector("T")
    for _ in range(30):
        d.update(_noisy(rng, a))
    assert d.update(b) is True
    # Refractory: the next frame of the new scene must not re-fire.
    assert d.update(_noisy(rng, b)) is False
    assert d.cuts == 1


def test_noisy_camera_does_not_permanently_look_like_it_is_cutting():
    rng = np.random.default_rng(3)
    base = rng.integers(20, 40, (480, 640, 3), dtype=np.uint8)
    d = SceneCutDetector("T")
    for _ in range(80):
        heavy = np.clip(base + rng.normal(0, 14, base.shape), 0, 255).astype(np.uint8)
        d.update(heavy)
    assert d.cuts == 0, "heavy sensor noise must not be read as scene cuts"
