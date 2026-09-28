"""Offline checks for exporter compatibility and evidence boundaries in the deck."""

import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "submission_deck", ROOT / "tools/demo/render_submission_deck.py"
)
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)


@pytest.fixture
def text_calls(monkeypatch):
    calls = []
    original = ImageDraw.ImageDraw.text

    def record(self, xy, text, *args, **kwargs):
        calls.append(str(text))
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    return calls


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    directory = tmp_path / "var/demo/plate_gallery"
    directory.mkdir(parents=True)
    Image.new("RGB", (160, 60), "white").save(directory / "crop.jpg")
    rows = [
        dict(
            image="crop.jpg",
            display_image="crop.jpg",
            camera="cam06",
            timestamp="2026-09-28T04:20:31+00:00",
            plate_text=f"TEST{i}",
            original_image="originals/crop.jpg",
            original_sha256="test-only",
            display_scale=4,
            confidence="0.95",
            agreeing_reads="3",
            provenance="RENDER_TEST_FIXTURE",
        )
        for i in range(8)
    ]
    stats = dict(
        total_reads=1000,
        distinct_plates=100,
        confirmed_registrations=50,
        cameras_with_reads=2,
        window_start="2026-09-27T00:00:00+00:00",
        window_end="2026-09-28T00:00:00+00:00",
        source="fixture",
        note="Layout test only",
    )
    (directory / "selected.json").write_text(json.dumps(rows))
    (directory / "stats.json").write_text(json.dumps(stats))
    monkeypatch.setattr(deck, "ROOT", tmp_path)
    return directory, rows, stats


def test_absent_gallery_warns_and_omits(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deck, "ROOT", tmp_path)
    assert deck.government_anpr_gallery() is None
    assert "WARNING: GOVERNMENT ANPR GALLERY OMITTED" in capsys.readouterr().err


@pytest.mark.parametrize(
    "fault",
    [
        "missing_stats",
        "bad_json",
        "missing_crop",
        "missing_field",
        "nan_confidence",
        "negative_count",
        "negative_camera_count",
        "boolean_camera_count",
        "list_camera_count",
    ],
)
def test_incomplete_gallery_never_substitutes_evidence(gallery, capsys, fault):
    directory, rows, stats = gallery
    if fault == "missing_stats":
        (directory / "stats.json").unlink()
    elif fault == "bad_json":
        (directory / "selected.json").write_text("{")
    elif fault == "missing_crop":
        (directory / "crop.jpg").unlink()
    elif fault == "missing_field":
        del rows[0]["provenance"]
        (directory / "selected.json").write_text(json.dumps(rows))
    elif fault == "nan_confidence":
        rows[0]["confidence"] = float("nan")
        (directory / "selected.json").write_text(json.dumps(rows))
    else:
        key = "total_reads" if fault == "negative_count" else "cameras_with_reads"
        stats[key] = {"boolean_camera_count": True, "list_camera_count": ["cam06"]}.get(fault, -1)
        (directory / "stats.json").write_text(json.dumps(stats))
    assert deck.government_anpr_gallery() is None
    assert "WARNING" in capsys.readouterr().err


@pytest.mark.parametrize("count", [6, 8])
def test_gallery_uses_full_window_stats_and_card_metadata(gallery, text_calls, count):
    directory, rows, _stats = gallery
    (directory / "selected.json").write_text(json.dumps(rows[:count]))
    page = deck.government_anpr_gallery()
    assert page.size == (1920, 1080)
    assert page.info["truth_tags"] == ("DEMO",)
    rendered = " ".join(text_calls)
    assert "1,000 total reads" in rendered and "100 distinct plates" in rendered
    assert "50 confirmed registrations" in rendered and "2 cameras" in rendered
    assert all(f"TEST{i}" in rendered for i in range(count))
    assert "cam06  ·  OCR confidence 95.0%" in rendered
    # The fixture's UTC time, converted to IST rather than relabelled.
    assert "28 Sep 2026  ·  09:50:31 IST" in rendered


def test_empty_plate_lists_do_not_claim_ocr_parity(text_calls):
    deck.gpu_measured()
    rendered = " ".join(text_calls)
    assert "same observations (no plates in sample)" in rendered
    assert "same plates" not in rendered


@pytest.mark.parametrize(
    "sweep", [None, {"deep_inference_concurrency": 3}, {"decode_sessions": 30}, [], "invalid-json"]
)
def test_coverage_uses_analysed_cameras_never_decode_count(
    tmp_path, monkeypatch, text_calls, capsys, sweep
):
    reports = tmp_path / "var/reports"
    reports.mkdir(parents=True)
    for name in ("pipeline_device", "detector_device", "live_cluster", "camera_load"):
        (reports / f"{name}.json").write_bytes((ROOT / f"var/reports/{name}.json").read_bytes())
    if sweep is not None:
        (reports / "ai_concurrency_sweep.json").write_text(
            "{" if sweep == "invalid-json" else json.dumps(sweep)
        )
    monkeypatch.setattr(deck, "ROOT", tmp_path)
    deck.ai_coverage()
    rendered = " ".join(text_calls)
    assert "4 deep-inference slots by default" in rendered
    assert "not current concurrency" in rendered or "separate test configuration" in rendered
    assert "deep inference on 30" not in rendered
    assert "not the current slot count" in rendered
    if isinstance(sweep, dict) and "deep_inference_concurrency" in sweep:
        assert "Sweep: 3 concurrent cameras" in rendered
    elif sweep is not None:
        assert "WARNING" in capsys.readouterr().err


def test_exporter_relative_image_cannot_be_shadowed_by_repo_file(tmp_path, monkeypatch):
    directory = tmp_path / "var/demo/plate_gallery"
    (tmp_path / "display").mkdir()
    (tmp_path / "display/crop.png").write_bytes(b"wrong image")
    monkeypatch.setattr(deck, "ROOT", tmp_path)
    assert deck.gallery_path("display/crop.png", directory) == directory / "display/crop.png"
    assert (
        deck.gallery_path("var/demo/plate_gallery/display/crop.png", directory)
        == directory / "display/crop.png"
    )


def test_government_trace_separates_full_store_standin_and_synthetic_route(text_calls):
    page = deck.government_designated()
    rendered = " ".join(text_calls)
    assert "1,101 reads · 264 distinct plates · 9 cameras" in rendered
    assert "57 reads · cam06 only" in rendered
    assert "not organiser-issued" in rendered
    assert "all 5 precede the filmed take" in rendered
    assert deck.SYNTHETIC_ROUTE in rendered
    assert "zero confirmed reads" in rendered
    assert "A verified hash proves the bytes only" in rendered
    assert "MEASURED" not in page.info["truth_tags"]
    assert "178 distinct plates" not in rendered
    assert "OWN-FEED MULTI-CAMERA" not in rendered


@pytest.mark.parametrize("page", [deck.government_evidence, deck.films])
def test_session_reads_are_not_claimed_inside_the_film(page, text_calls, monkeypatch):
    monkeypatch.setattr(deck, "_film_meta", lambda _: "offline test")
    page()
    rendered = " ".join(text_calls)
    assert "200" in rendered and "11:15–12:53 IST" in rendered
    assert "21" in rendered and "12:41–12:47" in rendered
    assert "during the recording." not in rendered
    assert "recogniser, recorded in the government film" not in rendered


def test_gallery_does_not_repeat_unbounded_exporter_note(gallery, text_calls):
    directory, _rows, stats = gallery
    stats["note"] = "statistics cover every government read in the store"
    (directory / "stats.json").write_text(json.dumps(stats))
    deck.government_anpr_gallery()
    rendered = " ".join(text_calls)
    assert "24 Sep snapshot" in rendered
    assert "stated window" in rendered
    assert stats["note"] not in rendered
    assert "1,101 reads / 264 plates" in rendered


@pytest.mark.parametrize("page", [deck.cover, deck.scenario])
def test_registry_slots_are_not_presented_as_video_feeds(page, text_calls):
    page()
    rendered = " ".join(text_calls)
    assert "30 government + 2 own feeds with video" in rendered
    assert "18 control slots are registry rows without video" in rendered


def test_integration_and_analytics_boundaries_are_rendered(text_calls):
    deck.watchlist_method()
    deck.analytics()
    deck.system_architecture()
    deck.evaluation_day()
    rendered = " ".join(text_calls)
    for name in ("VAHAN", "SARATHI", "eGujCop (CCTNS)", "AFIS", "NAFIS"):
        assert name in rendered
    for phrase in ("SourceUnavailable", "FRS is DESIGNED", "cam12 administrator DEMONSTRATION rule",
                   "intrusion accuracy is unmeasured", "fixed interval", "live-worker wiring is DESIGNED",
                   "case and purpose", "whole authorised estate", "watchlist", "trace report"):
        assert phrase in rendered
    assert "cadence adapts by priority" not in rendered


def test_build_dates_all_screenshots_and_uses_replacement_assets(monkeypatch, text_calls):
    opened = []

    def placeholder(path):
        opened.append(path.name)
        return Image.new("RGB", (320, 180), "white")

    monkeypatch.setattr(deck, "_open", placeholder)
    monkeypatch.setattr(deck, "government_anpr_gallery", lambda: None)
    monkeypatch.setattr(deck, "_film_meta", lambda _: "offline test")
    deck.build()
    rendered = " ".join(text_calls)
    assert "gov_live_dense_2026-09-28.png" in opened
    assert "05_statewide_architecture.png" in opened
    assert "gov_overview.png" not in opened
    assert "gov_live_twoup_boxes.jpg" not in opened
    assert "12 of 30 government cameras live in this recording" in rendered
    assert "counts plate-bearing route observations" in rendered
    assert "0 confirmed reads" in rendered
    assert "never as stolen" not in rendered
    assert "GJ07XZ4409" in rendered
    for date in ("15 Sep 2026", "24 Sep 2026", "28 Sep 2026"):
        assert f"Historical capture: {date}" in rendered
    # Every screenshot goes through the date-enforcing renderer, including
    # captures whose filenames predate their replacement with a newer film.
    assert sum(t.startswith("Historical capture:") for t in text_calls) == len(deck.SHOT_DATES)
