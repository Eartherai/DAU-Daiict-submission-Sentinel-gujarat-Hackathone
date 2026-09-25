"""The film draws only the plate the store records for the track.

`tools/demo/analyse_own_feed.py` draws a plate from the frame on which the
vote would accept it. The agreement rule can withdraw that acceptance as more
reads arrive, and the store then records no plate - so a plate drawn early had
to be taken back off the film once the track's own vote was known.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from saakshya.analytics.anpr import AnprConfig, PlateVoter, RawRead

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "demo"))

import analyse_own_feed as own


def _read(text: str, i: int) -> RawRead:
    return RawRead(text, 0.95, (0, 0, 10, 5), 0.9, i * 0.1)


def _film(texts: list[str], track: str = "TR-BLUR") -> tuple[list[list], dict[str, str]]:
    """Feed one read a frame, draw as the tool does, and resolve at the end."""
    cfg = AnprConfig()
    voter = PlateVoter(cfg)
    pipe = SimpleNamespace(_voters={track: voter})
    plate_of: dict[str, str] = {}
    frames: list[list] = []
    for i, text in enumerate(texts):
        voter.add(track, [_read(text, i)])
        plate_of.update(own._accepted_now(pipe, cfg))
        frames.append([i * 0.1, [[0, 0, 10, 10, "c", 1, 90, plate_of.get(track) or "", 1]]])
    best = voter.resolve(track)
    final_plate = {track: best.plate.canonical} if best else {}
    own._settle_drawn_plates(frames, {1: track}, final_plate)
    return frames, final_plate


def test_a_plate_the_vote_withdrew_is_taken_off_the_film() -> None:
    texts = ["MH01EX0900"] * 3 + ["MH01EK0900", "MH01EK0900", "MH01EX0800",
                                 "MH01EK9900", "MH01EK0800"]
    # The overlay did accept it on the way: three agreeing reads, no rival yet.
    cfg = AnprConfig()
    voter = PlateVoter(cfg)
    voter.add("T", [_read(t, i) for i, t in enumerate(texts[:3])])
    assert own._accepted_now(SimpleNamespace(_voters={"T": voter}), cfg) == {"T": "MH01EX0900"}

    frames, final_plate = _film(texts)
    assert final_plate == {}
    assert all(box[7] == "" for _, boxes in frames for box in boxes)


def test_a_published_plate_stays_drawn_from_its_acceptance() -> None:
    frames, final_plate = _film(["MH02GB4920"] * 6)
    assert final_plate == {"TR-BLUR": "MH02GB4920"}
    drawn = [boxes[0][7] for _, boxes in frames]
    assert drawn == ["", "", "MH02GB4920", "MH02GB4920", "MH02GB4920", "MH02GB4920"]


def test_a_box_keeps_no_plate_the_store_holds_for_another_track() -> None:
    frames = [[0.0, [[0, 0, 10, 10, "c", 1, 90, "MH02GB4920", 1],
                     [0, 0, 10, 10, "c", 2, 90, "MH02GB4926", 1]]]]
    cleared = own._settle_drawn_plates(frames, {1: "A", 2: "B"},
                                       {"A": "MH02GB4920", "B": "MH02GB4920"})
    assert cleared == 1
    assert [b[7] for b in frames[0][1]] == ["MH02GB4920", ""]


def test_the_overlay_counts_zero_filled_lookalikes_as_the_vote_does() -> None:
    cfg = AnprConfig()
    voter = PlateVoter(cfg)
    voter.add("T", [_read(t, i) for i, t in enumerate(
        ["MH01EK0900"] * 3 + ["MH01EK0000"] * 3)])
    assert own._accepted_now(SimpleNamespace(_voters={"T": voter}), cfg) == {}
    assert voter.resolve("T") is None
