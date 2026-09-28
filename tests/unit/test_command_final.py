"""Final product: source domains, jump playback honesty, golden own feeds."""
from __future__ import annotations

import pytest

from saakshya.command.domain import (
    AI_CADENCE,
    GOVERNMENT,
    OWN_FEED,
    SYNTHETIC_CONTROL,
    classify_source_domain,
    jump_playback,
    tile_status,
    wall_composition,
)
from saakshya.command.investigate import entity_tracking, format_elapsed, jump_payload
from saakshya.command.scale import seed_50_evaluation
from saakshya.command.summary import command_summary
from saakshya.store import Store
from tests.conftest import make_observation


def test_domains_are_never_confused():
    assert classify_source_domain("cam07") == GOVERNMENT
    assert classify_source_domain("OWN-PEOPLE") == OWN_FEED
    assert classify_source_domain("OWN-TRAFFIC") == OWN_FEED
    assert classify_source_domain("C-014") == SYNTHETIC_CONTROL
    assert classify_source_domain("CTL-00001") == SYNTHETIC_CONTROL
    assert classify_source_domain("mystery") == SYNTHETIC_CONTROL
    assert classify_source_domain(
        "cam01", stored=OWN_FEED) == OWN_FEED


def test_still_is_never_live():
    assert tile_status({"state": "OBSERVED"}) == "PREVIEW"
    assert tile_status({"state": "UNKNOWN"}) == "NO SIGNAL"
    assert tile_status({"state": "STREAMING", "whep_capable": True}) == "LIVE"
    assert tile_status({"state": "STREAMING", "rtsp_capable": True}) == "RTSP_ONLY_AI"
    assert tile_status({"state": "DOWN"}) == "NO SIGNAL"


def test_jump_live_is_not_seekable(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'j.db'}")
    store.create_all()
    store.upsert_camera({
        "camera_id": "cam07", "district": "Ahmedabad",
        "source_domain": GOVERNMENT,
    })
    store.add_observations([make_observation("cam07", plate="GJ01AA1111", offset_s=0)])
    obs = store.search_plate("GJ01AA1111")[0]
    payload = jump_payload(store, obs.observation_id)
    assert payload["playback"]["seekable"] is False
    assert "EVENT TIMESTAMP" in payload["playback"]["note"] or (
        payload["playback"]["kind"] == "LIVE_POSITION")
    assert payload["event_timestamp"]


def test_own_feed_jump_is_replay_when_file_present(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'o.db'}")
    store.create_all()
    store.upsert_camera({
        "camera_id": "OWN-TRAFFIC", "district": "Ahmedabad",
        "source_domain": OWN_FEED,
    })
    monkeypatch.setattr(
        "saakshya.command.domain.local_media_url", lambda cid: "/tmp/OWN-TRAFFIC.mp4")
    pb = jump_playback(store, "OWN-TRAFFIC", pts_s=12.5)
    assert pb["seekable"] is True
    assert pb["kind"] == "OWN_FEED_REPLAY"
    assert pb["event_pts_s"] == 12.5


def test_fifty_wall_is_thirty_plus_two_plus_control(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'w.db'}")
    store.create_all()
    seed_50_evaluation(store)
    wall = wall_composition(store)
    assert wall["government"] == 30
    assert wall["own_feed"] >= 2
    assert "OWN-PEOPLE" in wall["golden_own_feeds"]
    assert wall["onboarded"] == 50
    ids = wall["cameras"][SYNTHETIC_CONTROL]
    assert all(not i.startswith("cam") for i in ids)
    assert all(not i.startswith("OWN-") for i in ids)


def test_hop_elapsed_and_contradiction_reason():
    follow = {
        "plate": "GJ01AA1111",
        "route": [
            {"camera_id": "A", "site": "Signal A",
             "t_norm": "2026-09-01T08:00:00+00:00", "observation_id": "O1"},
            {"camera_id": "B", "site": "Signal B",
             "t_norm": "2026-09-01T08:03:17+00:00", "observation_id": "O2"},
        ],
        "contradictions": [{
            "from_camera": "A", "to_camera": "FAR",
            "distance_m": 160000, "elapsed_s": 2, "implied_speed_kmh": 288000,
            "reason": "impossible travel",
        }],
        "candidates": [],
    }
    card = entity_tracking(follow)
    assert card["hops"][0]["role"] == "FIRST SEEN"
    assert card["hops"][1]["role"] == "LAST SEEN"
    assert card["hops"][1]["elapsed_from_prev_s"] == 197.0
    assert card["hops"][1]["elapsed_label"] == format_elapsed(197)
    contra = card["transitions"][0]
    assert contra["verdict"] == "CONTRADICTION"
    assert "160.0 km" in contra["operator_reason"]
    assert "elapsed 2s" in contra["operator_reason"]


def test_ai_cadence_deep_does_not_raise_overlay_poll():
    assert AI_CADENCE["FAST"]["overlay_poll_ms"] < AI_CADENCE["BALANCED"]["overlay_poll_ms"]
    assert AI_CADENCE["DEEP"]["overlay_poll_ms"] <= AI_CADENCE["BALANCED"]["overlay_poll_ms"]
    assert AI_CADENCE["DEEP"]["ocr_every"] < AI_CADENCE["BALANCED"]["ocr_every"]


def test_command_summary_gpu_is_never_zero(tmp_path, monkeypatch):
    # The summary reads the AI worker's heartbeat from disk, so a worker
    # running on the developer's machine would otherwise decide this test.
    # State the case under test instead of inheriting the host's.
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat",
                        lambda: {}, raising=False)
    store = Store(f"sqlite:///{tmp_path / 'k.db'}")
    store.create_all()
    summary = command_summary(store)
    gpu = summary["resources"]["gpu"]
    assert gpu["display"] == "NOT_MEASURED"
    assert gpu["display"] != 0
    assert gpu["display"] != "0%"
    assert summary["kpis"]["ai_latency_p50"]["display"] == "NOT_MEASURED"
    assert summary["kpis"]["cameras_online"]["timestamp"]
    assert summary["kpis"]["cameras_online"]["scope"]
    assert summary["isolation"]["ai_worker"]["chip"] == "AI DEGRADED"
    assert summary["isolation"]["ocr"]["chip"] == "OCR DEGRADED"
    assert summary["rank_equivalence"]
    assert summary["rank_equivalence"][0]["role"] == "SUPERVISOR"


def test_command_summary_reports_a_live_ai_worker(tmp_path, monkeypatch):
    """A running worker must not still be reported as degraded.

    The chip was a constant, so the masthead read "AI DEGRADED" while the
    operator watched that same worker draw detections on screen.
    """
    monkeypatch.setattr(
        "saakshya.analytics.worker.read_heartbeat",
        lambda: {"pid": 4242, "cameras": {"cam06": {
            "ai": "ACTIVE", "detector_fps": 2.5, "queue_depth": 2,
            "inference_p50_ms": 300.0, "inference_p95_ms": 410.0}}},
        raising=False)
    store = Store(f"sqlite:///{tmp_path / 'hb.db'}")
    store.create_all()
    summary = command_summary(store)
    res = summary["resources"]
    assert summary["isolation"]["ai_worker"]["chip"] == "AI ACTIVE"
    assert res["ai_workers"]["display"] == "1"
    assert res["detector_fps"]["display"] == "2.5"
    assert res["inference_p50"]["display"] == "300.0 ms"
    assert res["inference_p95"]["display"] == "410.0 ms"
    assert res["queue_depth"]["display"] == "2"
    for key in ("ai_workers", "detector_fps", "inference_p50", "queue_depth"):
        assert res[key]["label"] == "MEASURED"
    # An unsampled figure is still never invented.
    assert res["gpu"]["display"] == "NOT_MEASURED"


def test_command_summary_stale_heartbeat_is_not_measured(tmp_path, monkeypatch):
    """A stale heartbeat is an unknown, never a zero."""
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat",
                        lambda: {"stale": True, "pid": None}, raising=False)
    store = Store(f"sqlite:///{tmp_path / 'st.db'}")
    store.create_all()
    res = command_summary(store)["resources"]
    for key in ("ai_workers", "detector_fps", "inference_p50", "queue_depth"):
        assert res[key]["display"] == "NOT_MEASURED"


@pytest.mark.parametrize("heartbeat,deep,chip,cadence", [
    ({"pid": 4242, "cameras": {"cam01": {"ai": "ACTIVE"},
                               "cam02": {"ai": "CONNECTING"}}},
     "1 of 2 active", "AI ACTIVE", "sampled"),
    ({"pid": 4242, "cameras": {"cam01": {"ai": "CONNECTING"}}},
     "0 of 2 active", "AI STARTING", "sampled"),
    ({}, "not measured of 2 with stream", "AI DEGRADED", "not measured"),
    ({"pid": 4242, "stale": True, "cameras": {"cam01": {"ai": "ACTIVE"}}},
     "not measured of 2 with stream", "AI DEGRADED", "not measured"),
    ({"cameras": {"cam01": {"ai": "ACTIVE"}}},
     "not measured of 2 with stream", "AI DEGRADED", "not measured"),
])
def test_ai_coverage_distinguishes_registry_health_and_inference(
        tmp_path, monkeypatch, heartbeat, deep, chip, cadence):
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat", lambda: heartbeat)
    monkeypatch.delenv("SAAKSHYA_AI_CAMERAS", raising=False)
    monkeypatch.delenv("SAAKSHYA_AI_CAMERA_LIMIT", raising=False)
    store = Store(f"sqlite:///{tmp_path / 'coverage.db'}")
    store.create_all()
    for cid, url in (("cam01", "rtsp://example.invalid/one"),
                     ("cam02", "rtsp://example.invalid/two"),
                     ("slot", "   ")):
        store.upsert_camera({"camera_id": cid, "rtsp_url": url})
    store.upsert_health("cam01", {"state": "STREAMING"})
    # A health record outside the registry must not inflate coverage.
    monkeypatch.setattr(store, "list_health", lambda: {
        "cam01": {"state": "STREAMING"}, "removed": {"state": "UNKNOWN"}})
    ai = command_summary(store)["isolation"]["ai_worker"]
    assert ai["chip"] == chip
    assert ai["note"] == (
        "COVERAGE 3 registered · 2 with stream · 1 with stored health | "
        f"DEEP INFERENCE {deep} | CADENCE {cadence}"
        " | POLICY 4 deep-inference slots, prioritised by measured capability")
    assert "throughput on this machine" in ai["detail"]
    assert "Stored health may be old" in ai["detail"]
    assert "idle hub cameras are not probed" in ai["detail"]
    assert "at worker boot by measured ANPR grade: GOOD > DEGRADED > UNKNOWN > UNSUITABLE" in ai["detail"]
    assert "Cameras are not rotated at runtime" in ai["detail"]
    assert "ADAPTIVE" not in ai["note"]
    assert "rotation" not in ai["note"]


@pytest.mark.parametrize("cameras,limit,policy", [
    ("", "8", "POLICY 8 deep-inference slots, prioritised by measured capability"),
    ("cam06,cam21", "4", "POLICY 2 operator-selected camera(s) for deep inference"),
])
def test_ai_slot_policy_follows_the_worker_settings(tmp_path, monkeypatch,
                                                    cameras, limit, policy):
    """The policy is read from what the worker reads, never a fixed number."""
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat", lambda: {})
    monkeypatch.setenv("SAAKSHYA_AI_CAMERAS", cameras)
    monkeypatch.setenv("SAAKSHYA_AI_CAMERA_LIMIT", limit)
    store = Store(f"sqlite:///{tmp_path / 'policy.db'}")
    store.create_all()
    assert command_summary(store)["isolation"]["ai_worker"]["note"].endswith(policy)


def test_ai_coverage_empty_registry_keeps_denominator(tmp_path, monkeypatch):
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat", lambda: {})
    store = Store(f"sqlite:///{tmp_path / 'empty-coverage.db'}")
    store.create_all()
    note = command_summary(store)["isolation"]["ai_worker"]["note"]
    assert "COVERAGE 0 registered · 0 with stream · 0 with stored health" in note
    assert "DEEP INFERENCE not measured of 0 with stream" in note


def test_government_seed_urls_have_no_userinfo(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'u.db'}")
    store.create_all()
    seed_50_evaluation(store)
    cam = store.get_camera("cam01")
    assert cam["whep_url"].startswith("http://")
    assert "@" not in cam["whep_url"]
    assert cam["camera_id"] in cam["whep_url"]
    assert cam["rtsp_url"].startswith("rtsp://")
    assert "@" not in cam["rtsp_url"]
    ctl = store.get_camera("CTL-00000") or store.get_camera("CTL-00001")
    if ctl:
        assert not (ctl.get("whep_url") or "").startswith("http://103.250")


def test_ocr_chip_follows_the_worker_not_a_fixed_verdict(tmp_path, monkeypatch):
    """'OCR DEGRADED' was hard-coded, shown while the worker read plates."""
    import os
    hb = {"pid": os.getpid(), "cameras": {
        "CAM-1": {"ai": "ACTIVE", "frames": 40, "anpr": "MEASURED", "plates_read": 3},
        "CAM-2": {"ai": "ACTIVE", "frames": 40, "anpr": "RUNNING", "plates_read": 0}}}
    monkeypatch.setattr("saakshya.analytics.worker.read_heartbeat", lambda: hb,
                        raising=False)
    store = Store(f"sqlite:///{tmp_path / 'o.db'}")
    store.create_all()
    ocr = command_summary(store)["isolation"]["ocr"]
    assert ocr["chip"] == "OCR ACTIVE" and "3 plate" in ocr["note"]
    hb["cameras"]["CAM-1"].update(anpr="RUNNING", plates_read=0)
    fresh = Store(f"sqlite:///{tmp_path / 'o2.db'}")      # the summary is cached per store
    fresh.create_all()
    assert command_summary(fresh)["isolation"]["ocr"]["chip"] == "OCR RUNNING"
