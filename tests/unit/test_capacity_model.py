"""The statewide capacity model still supports the claim built on it.

docs/STATEWIDE_ARCHITECTURE.md and HLD §21 claim that, as analysed cameras grow
to 80,000, only inference compute is bought in proportion, and every other
camera-driven resource keeps its headroom. The claim is only as good as the
arithmetic in tools/sizing/capacity_model.py, so this runs the model on its
committed inputs (var/reports, reports/measure_compression.json) and pins the
conclusions rather than the digits.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def model():
    spec = importlib.util.spec_from_file_location(
        "capacity_model", ROOT / "tools/sizing/capacity_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # computes R; writes nothing
    return module


def test_only_compute_is_bought_in_proportion_to_analysed_cameras(model) -> None:
    small = model.provision(model.C * 0.1)
    full = model.provision(model.C)
    grows = {item for item in full if full[item] != small[item]}
    assert grows == set(model.COMPUTE_ITEMS), (
        f"non-compute items change with analysed cameras: {grows - set(model.COMPUTE_ITEMS)}")
    for item in model.COMPUTE_ITEMS:
        assert full[item] >= 5 * small[item], f"{item} is not sized to demand"


def test_camera_driven_throughput_keeps_5x_headroom_at_80000(model) -> None:
    rows = [r for r in model.R["rows"]
            if r["driver"] == "cameras" and r["kind"] == "throughput" and not r["alternative"]]
    assert len(rows) >= 10, "the binding-constraint table lost its throughput rows"
    thin = {r["resource"]: r["headroom"] for r in rows if r["headroom"] < 5}
    assert not thin, f"camera-driven throughput below 5x headroom: {thin}"


def test_rejected_alternatives_would_bind(model) -> None:
    alternatives = {r["resource"]: r["headroom"] for r in model.R["rows"] if r["alternative"]}
    uncompressed = [h for name, h in alternatives.items() if "uncompressed" in name]
    all_on_kafka = [h for name, h in alternatives.items() if "all observations" in name]
    assert uncompressed and all(h < 1.2 for h in uncompressed), alternatives
    assert all_on_kafka and all(h < 1.2 for h in all_on_kafka), alternatives


def test_storage_is_the_first_non_compute_resource_to_bind(model) -> None:
    storage = [r["headroom"] for r in model.R["rows"]
               if r["driver"] == "cameras" and r["kind"] == "storage"]
    assert storage and min(storage) >= 1.5


def test_every_input_carries_a_label(model) -> None:
    labels = {"MEASURED", "VERIFIED", "ASSUMED", "DESIGNED"}
    assert model.I, "the model has no inputs"
    for name, spec in model.I.items():
        parts = spec["label"].split("/")
        assert parts and all(model.LABELS.get(p) in labels for p in parts), (name, spec["label"])
        assert spec["source"] or spec["label"] == "D", f"{name} has no stated source"


def test_measured_inputs_are_read_from_the_committed_reports(model) -> None:
    bandwidth = json.loads((ROOT / "var/reports/bandwidth.json").read_text())
    compression = json.loads((ROOT / "reports/measure_compression.json").read_text())
    assert model.OBS_WIRE_B == bandwidth["observation_bytes_each"]
    assert model.OBS_Z_B == compression["batches"]["100"]["zlib6_bytes_per_row"]


def test_committed_output_matches_the_model(model) -> None:
    """reports/capacity_model.json is what the documents quote; it must not drift."""
    committed = json.loads((ROOT / "reports/capacity_model.json").read_text())
    fresh = json.loads(json.dumps(model.R, default=list))
    for key in ("compute", "wan_cell", "storage", "rates", "sweep", "cost_planning", "hostile"):
        assert committed[key] == fresh[key], f"reports/capacity_model.json is stale at {key!r}"
