"""The cost model produces figures, not a free variable.

Step 6 asks for estimated implementation and operational costs. The section
previously terminated in `inference_nodes = 2,500 / (11.4 x S)` with S marked
UNKNOWN, so it never yielded a number — correct about its own ignorance and
useless to anyone sizing a deployment.

It also sized on 11.4 frames/s, a single detection-only process with nothing
else running, while the live worker doing the whole pipeline sustains about
5.6 aggregate. Sizing a statewide estate on the best case is the kind of
number that collapses in the first question about it.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

HLD = (Path(__file__).resolve().parents[2] / "docs/HLD.md").read_text(encoding="utf-8")
SECTION = HLD[HLD.index("## 17. Indicative cost model"):
              HLD.index("## 18. Cybersecurity architecture")]


def test_both_throughput_measurements_are_stated() -> None:
    """One figure would hide that the two differ by a factor of two."""
    assert "11.4" in SECTION
    assert "5.6" in SECTION
    assert "tools/perf/camera_load.py" in SECTION
    assert "local camera queues" in SECTION


def test_it_sizes_on_the_conservative_measurement() -> None:
    model = SECTION[SECTION.index("### 17.2"):SECTION.index("### 17.3")]
    assert "process_throughput_fps      = 5.6" in model, (
        "the model still sizes on the best-case component benchmark")


def test_the_frame_drop_is_reported() -> None:
    """96.5% of delivered frames were dropped; that is the sizing signal."""
    assert "96.5" in SECTION
    assert "dropped" in SECTION


def test_the_sensitivity_table_arithmetic_is_right() -> None:
    """A table of invented numbers is worse than no table."""
    rows = re.findall(
        r"^\| (\d+)(?: \(CPU only\))? \| ([\d,]+) \| ([\d,]+) \| ([\d,]+) \|$",
        SECTION, re.M)
    assert len(rows) >= 5, f"expected the solved table, found {len(rows)} rows"
    n = lambda s: int(s.replace(",", ""))
    for s, per_district, statewide, best_case_statewide in rows:
        S = int(s)
        assert n(per_district) == math.ceil(2500 / (5.6 * S)), f"S={S} per-district"
        assert n(statewide) == n(per_district) * 33, f"S={S} statewide"
        # Column four is statewide too, so the two totals are comparable. The
        # first draft of this test read it as per-district, which is exactly
        # how a reviewer would have misread the original header.
        assert n(best_case_statewide) == math.ceil(2500 / (11.4 * S)) * 33, (
            f"S={S} best-case statewide")


def test_the_benchmark_to_determine_s_is_specified() -> None:
    """An unknown with no way to resolve it is just an unknown."""
    bench = SECTION[SECTION.index("### 17.4"):SECTION.index("### 17.5")]
    for needed in ("same model weights", "ratio", "contention"):
        assert needed in bench, f"the benchmark procedure omits {needed!r}"


def test_it_does_not_quote_an_unmeasured_speedup_as_fact() -> None:
    """S depends on accelerator, batch size and precision. It is not a lookup."""
    assert "not a literature value" in SECTION
    assert "UNKNOWN" in SECTION, "the honest status of S was dropped"


def test_the_avoided_costs_keep_their_measured_provenance() -> None:
    avoided = SECTION[SECTION.index("### 17.5"):]
    # Read the figures out of the generated report rather than restating them,
    # so a re-run of the load test cannot leave the HLD quoting last week's
    # numbers. That drift is precisely what evaluation area 7 scores.
    report = (Path(__file__).resolve().parents[2]
              / "reports/SCALE_80K_LOAD_TEST.md").read_text(encoding="utf-8")
    rate = re.search(r"\(([\d,]+)/s\)", report).group(1)
    gaps = re.search(r"gap analysis \(all 80,000\) \| \*\*([\d.]+) ms", report)
    assert rate in avoided, (
        f"the HLD quotes an onboarding rate the load test no longer reports "
        f"({rate}/s)")
    assert gaps and gaps.group(1).rstrip("0").rstrip(".") in avoided.replace(",", ""), (
        "the HLD quotes a gap-analysis time the load test no longer reports")
    size = re.search(r"\| Database size \| ([\d.]+) MB \|", report)
    assert size, "the load report must state its measured database size"
    assert f"{size.group(1)} MB" in avoided, (
        "the HLD quotes a database size the load report no longer reports")
    assert "MEASURED" in avoided
