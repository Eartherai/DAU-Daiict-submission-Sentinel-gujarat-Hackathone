"""End-to-end: the complete mandatory chain, with no LLM in the loop.

    ingest → observations → plate search → camera graph → trajectory
           → watchlist → alert → evidence → verification

This is the test the Gujarat Police evaluation actually exercises, so it runs
through ordinary production code with no demo branch, no target-specific
constant, and no camera-specific handling. The target plate is a parameter; the
same test passes with a different one.

It is written to fail loudly on a *silent collapse* — zero observations, an empty
route, a missing alert, unverifiable evidence — because "nothing went wrong" and
"nothing happened" look identical in a summary line, and an earlier harness in
this project reported PASS on exactly that.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import av
import pytest

from saakshya.analytics.pipeline import CameraPipeline, PipelineConfig, persist_pipeline
from saakshya.evidence import EvidenceService
from saakshya.ingest.frame import Frame
from saakshya.intelligence import CameraGraph, TrajectorySolver, VehicleSearch
from saakshya.store import Store
from saakshya.watchlist import (
    AlertEngine,
    Category,
    Priority,
    VehicleOfInterest,
    WatchlistService,
)

ROOT = Path(__file__).resolve().parents[2]
MEDIA = ROOT / "var" / "media"
T0 = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not (MEDIA / "C-014.mp4").exists(),
    reason="corpus not rendered; run `make media`")

#: Stagger cameras onto one timeline so a single vehicle's journey is coherent.
#: This is scenario *setup*, not system behaviour — the pipeline never sees it.
CAMERA_OFFSETS = {"C-014": 0, "C-021": 300, "C-033": 600, "C-047": 900,
                  "C-052": 0, "C-061": 0}


#: Seconds of each 240-second clip this suite ingests.
#:
#: The scripted target crosses the corridor within the first 40 seconds and the
#: generated commuter traffic starts at 4, so this window contains the whole
#: scenario plus enough repeated transitions for the graph to trust an edge.
#:
#: Bounded because it was measured: enabling the vehicle detector tripled the
#: per-frame cost and this suite went from five minutes to over twenty-five. A
#: suite that takes half an hour is a suite people stop running, and a gate
#: nobody runs protects nothing.
CORPUS_SECONDS = 120.0


def _decode(cam: str, offset: float, fps: float = 4.0,
            max_seconds: float = CORPUS_SECONDS):
    c = av.open(str(MEDIA / f"{cam}.mp4"))
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
        when = T0 + timedelta(seconds=t + offset)
        yield Frame(camera_id=cam, segment_id="SEG1", pts_s=t, t_norm=when,
                    t_ingest=when, image=img, width=img.shape[1],
                    height=img.shape[0], codec="h264")
    c.close()


@pytest.fixture(scope="module")
def system(tmp_path_factory):
    """Ingest the whole corpus once; every test reads the same world."""
    tmp = tmp_path_factory.mktemp("e2e")
    store = Store(f"sqlite:///{tmp / 'e2e.db'}")
    store.create_all()

    catalogue = json.loads((MEDIA / "catalogue.json").read_text())
    for c in catalogue["cameras"]:
        store.upsert_camera({
            "camera_id": c["id"], "name": c["name"],
            "department": c["department"], "district": c["district"],
            "lat": c["location"]["lat"], "lon": c["location"]["lon"],
            "codec": c["codec"], "width": c["properties"]["width"],
            "height": c["properties"]["height"],
            "declared_fps": c["properties"]["declared_fps"],
            "tier": "A",
        })

    frames_seen = 0
    for cam in sorted(c["id"] for c in catalogue["cameras"]):
        meta = next(c for c in catalogue["cameras"] if c["id"] == cam)
        p = CameraPipeline(cam, PipelineConfig(), district=meta["district"],
                           department=meta["department"],
                           lat=meta["location"]["lat"], lon=meta["location"]["lon"])
        obs = []
        for fr in _decode(cam, CAMERA_OFFSETS.get(cam, 0)):
            frames_seen += 1
            obs.extend(p.process(fr))
        obs.extend(p.flush())
        persist_pipeline(store, obs, p)

    graph = CameraGraph(store).load()
    graph.seed_from_gis()
    graph.learn_from_observations()

    return {
        "store": store, "graph": graph, "frames": frames_seen,
        "search": VehicleSearch(store, graph),
        "solver": TrajectorySolver(graph),
        "watchlist": WatchlistService(store),
        "alerts": AlertEngine(store),
        "evidence": EvidenceService(store, root=tmp / "evidence"),
    }


@pytest.fixture(scope="module")
def target(system) -> str:
    """Pick the target from the data, not from a constant.

    The evaluation supplies an arbitrary registration number on the day, so the
    test must not know one in advance. We take the plate observed on the most
    cameras — which is what an investigator would be given.
    """
    from collections import defaultdict

    from saakshya.store import SearchFilter
    cameras: dict[str, set[str]] = defaultdict(set)
    rows: dict[str, int] = defaultdict(int)
    for o in system["store"].search(SearchFilter(limit=10_000)):
        if o.plate:
            cameras[o.plate].add(o.camera_id)
            rows[o.plate] += 1
    assert cameras, "no plated observations at all — ingestion produced nothing"
    # Distinct cameras first, then observation count. Ranking by row count
    # instead picks a vehicle the tracker fragmented at one camera — four rows,
    # one place — which exercises none of the chain this test exists to cover.
    return max(cameras, key=lambda p: (len(cameras[p]), rows[p]))


# --------------------------------------------------------------------------- #
# The chain
# --------------------------------------------------------------------------- #
def test_01_ingestion_produced_observations(system):
    st = system["store"].stats()
    assert system["frames"] > 100, "almost no frames decoded"
    assert st["observations"] > 0, "SILENT COLLAPSE: zero observations"
    assert st["observations_with_plate"] > 0, "no plate was ever read"
    assert st["raw_ocr_read_records"] > 0, (
        "plated observations without forensic OCR rows — plate_reads was not written")
    assert st["cameras"] == 6


def test_02_camera_graph_bootstrapped_without_configuration(system):
    g = system["graph"].stats()
    assert g["edges_total"] > 0, "camera graph is empty"
    assert g["cameras"] == 6


def test_03_plate_search_returns_observations(system, target):
    r = system["search"].search_plate(target, actor="officer.e2e",
                                      case_id="FIR-E2E-001",
                                      purpose="end-to-end verification")
    assert r.candidates, f"SILENT COLLAPSE: no observations for {target}"
    assert all(c.status == "CONFIRMED_BY_PLATE" for c in r.candidates)
    times = [c.observation.t_norm for c in r.candidates]
    assert times == sorted(times), "results are not in normalised-time order"


def test_04_trajectory_is_built_with_explanations(system, target):
    r = system["search"].search_plate(target)
    obs = [c.observation for c in r.candidates]
    hyps = system["solver"].solve(obs, target=target)
    assert hyps, "SILENT COLLAPSE: no trajectory hypothesis"
    h = hyps[0]
    assert h.camera_sequence, "empty route"
    # Not equality with len(obs): the solver coalesces track fragments of one
    # pass at one camera into a single sighting, so a route can legitimately be
    # shorter than the observation list. It must never be longer, and it must
    # account for what it merged.
    assert len(h.camera_sequence) <= len(obs)
    if len(h.camera_sequence) < len(obs):
        assert h.notes, "observations were merged without saying so"
    d = h.to_dict()
    assert d["status"] and d["score"] >= 0
    for leg in d["legs"]:
        assert leg["explanation"], "a leg without an explanation is not evidence"


def test_05_watchlist_hit_and_alert(system, target):
    wl, ae = system["watchlist"], system["alerts"]
    wl.add(VehicleOfInterest(
        plate=target, category=Category.STOLEN_VEHICLE,
        authority="SP Ahmedabad Rural, FIR 123/2026",
        reason="reported stolen 2026-08-20", priority=Priority.HIGH,
        jurisdiction="Ahmedabad", created_by="officer.e2e"))

    r = system["search"].search_plate(target)
    alerts = []
    for c in r.candidates:
        for m in wl.match(c.observation):
            a = ae.process(m)
            if a:
                alerts.append(a)
    assert alerts, "SILENT COLLAPSE: watchlist matched nothing"
    ids = {a.alert_id for a in alerts}
    assert len(ids) == 1, f"deduplication failed: {len(ids)} alerts for one vehicle"

    e = alerts[-1].explain()
    for key in ("what_matched", "why", "where", "when", "how_strong",
                "operator_action", "authority"):
        assert e[key], f"alert explanation missing {key}"


def test_06_evidence_is_created_and_verifies(system, target):
    es = system["evidence"]
    r = system["search"].search_plate(target)
    assert r.candidates
    created = [es.create(c.observation, device="e2e-node")
               for c in r.candidates]
    assert created, "SILENT COLLAPSE: no evidence created"
    for m in created:
        v = es.verify(m.evidence_id)
        assert v.ok, f"{m.evidence_id} failed verification: {v.to_dict()}"
    assert es.verify_chain().ok, "evidence chain is broken"


def test_07_evidence_export_carries_a_draft_certificate(system, target):
    es = system["evidence"]
    r = system["search"].search_plate(target)
    m = es.create(r.candidates[0].observation, device="e2e-node")
    pkg = es.export(m.evidence_id)
    cert = pkg["bsa_s63_certificate"]
    assert cert["status"] == "DRAFT_PENDING_SIGNATURE"
    assert cert["signature_person_in_charge"] is None
    assert cert["signature_expert"] is None
    assert "legally admissible" not in json.dumps(pkg).lower()


def test_08_hard_case_returns_candidates_not_certainty(system, target):
    """A camera that could not read the plate must still be reachable through
    appearance — as a candidate requiring verification, never as a match."""
    r = system["search"].search_plate(target)
    confirmed = [c.observation for c in r.candidates]
    gap = system["search"].find_gap_candidates(confirmed, actor="officer.e2e",
                                               case_id="FIR-E2E-001")
    # The corpus may or may not contain a fillable gap depending on what was
    # read; what must hold is that anything returned is honest about itself.
    for c in gap.candidates:
        assert c.status == "REQUIRES_VERIFICATION"
        assert c.score < 1.0
        e = c.explain()
        assert any(t["name"] == "plate" and t["value"] == 0.0 for t in e["terms"])
        assert e["primary_weakness"]
    if gap.candidates:
        assert gap.cameras_pruned, "graph prune reported nothing excluded"


def test_09_every_search_was_audited(system):
    ok, err = system["store"].verify_audit_chain()
    assert ok, err
    assert system["store"].stats()["audit_entries"] > 0


def test_10_no_llm_was_involved(system):
    """The mandatory chain must not depend on a model that can hallucinate.

    Asserted structurally: nothing in the chain imported a language model.
    """
    import sys
    for mod in ("vllm", "openai", "anthropic", "llama_cpp"):
        assert mod not in sys.modules, f"{mod} was imported during the chain"


# --------------------------------------------------------------------------- #
# Invariants (§57)
# --------------------------------------------------------------------------- #
def test_I1_every_observation_references_a_known_camera(system):
    from saakshya.store import SearchFilter
    known = {c["camera_id"] for c in system["store"].list_cameras()}
    for o in system["store"].search(SearchFilter(limit=10_000)):
        assert o.camera_id in known, f"orphan observation on {o.camera_id}"


def test_I9_unknown_quality_stays_unknown(system):
    """A camera we could not measure must not be assigned a confident grade."""
    from saakshya.store import SearchFilter
    for o in system["store"].search(SearchFilter(limit=10_000)):
        if o.observation_quality is None:
            assert o.source_grade in (None, "UNKNOWN")


def test_I10_uncertain_identity_stays_uncertain(system, target):
    r = system["search"].search_plate(target)
    gap = system["search"].find_gap_candidates([c.observation for c in r.candidates])
    for c in gap.candidates:
        assert c.status != "CONFIRMED_BY_PLATE"
        assert "not established by plate" in " ".join(c.warnings)
