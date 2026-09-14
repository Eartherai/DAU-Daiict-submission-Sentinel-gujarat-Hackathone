"""Measure what metadata-first transport actually saves, on the real grid.

The architecture rests on a claim: observations move, video does not. That claim
has been **modelled** in this repo and never measured, and a modelled saving is
not a result. This measures both sides on live government cameras.

Two quantities, both counted rather than estimated:

  * **video bytes** — the size of every compressed packet the camera actually
    sends, summed off the wire. Not bitrate multiplied by time, which is a
    specification; the real figure moves with scene activity.
  * **event bytes** — the serialised observations the same footage produces,
    which is what a metadata-first deployment would carry to the centre.

The ratio between them is the whole argument for Model 3 over Model 4, so it is
worth having as a number taken from this estate rather than from a datasheet.

    python tools/live/bandwidth.py --cameras cam01,cam04,cam16 --seconds 90
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import av

from saakshya.common.paths import display
from saakshya.live.credentials import credentialed, redact
from saakshya.store import Store

RTSP = "rtsp://103.250.160.189:8554/stream/{cam}"
OPTS = {"rtsp_transport": "tcp", "stimeout": "8000000", "rw_timeout": "8000000"}


@dataclass
class CameraBytes:
    camera_id: str
    packets: int = 0
    video_bytes: int = 0
    seconds: float = 0.0
    error: str | None = None
    keyframes: int = 0

    @property
    def bitrate_mbps(self) -> float:
        return (self.video_bytes * 8 / self.seconds / 1e6) if self.seconds else 0.0


def measure_camera(cam: str, seconds: float) -> CameraBytes:
    """Sum compressed packet sizes off the wire.

    Packets are demuxed, never decoded. Decoding would measure this host's CPU,
    not the network, and the question here is only what crosses the link.
    """
    rec = CameraBytes(camera_id=cam)
    try:
        container = av.open(credentialed(RTSP.format(cam=cam)), options=OPTS, timeout=25)
    except Exception as exc:
        rec.error = f"{type(exc).__name__}: {redact(str(exc))[:90]}"
        return rec
    t0 = time.monotonic()
    try:
        stream = container.streams.video[0]
        for packet in container.demux(stream):
            if packet.size:
                rec.packets += 1
                rec.video_bytes += packet.size
                if packet.is_keyframe:
                    rec.keyframes += 1
            if time.monotonic() - t0 >= seconds:
                break
    except Exception as exc:
        if not rec.packets:
            rec.error = f"{type(exc).__name__}: {redact(str(exc))[:90]}"
    finally:
        rec.seconds = time.monotonic() - t0
        with contextlib.suppress(Exception):
            container.close()
    return rec


def event_bytes(store: Store, cameras: list[str], limit: int = 400
                ) -> tuple[int, int, dict[str, Any]]:
    """Serialised size of real observations from these cameras.

    Measured on observations this system actually produced, not on an invented
    record: the fields a real one carries — provenance, model versions, quality
    terms — are most of its size, and a stripped example would flatter the
    result.
    """
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        rows = [dict(r._mapping) for r in c.execute(
            select(S.observations)
            .where(S.observations.c.camera_id.in_(cameras))
            .order_by(S.observations.c.t_norm_us.desc()).limit(limit))]
    if not rows:
        return 0, 0, {}
    blob = json.dumps(rows, default=str)
    return len(rows), len(blob.encode()), rows[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=f"sqlite:///{ROOT}/var/live.db")
    ap.add_argument("--cameras", default="cam01,cam04,cam16")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--observations-per-camera-hour", type=float, default=None,
                    help="override the rate; default is measured from the store")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    cams = [c.strip() for c in a.cameras.split(",") if c.strip()]
    store = Store(a.db)
    store.create_all()

    print(f"measuring {len(cams)} camera(s) for {a.seconds:.0f}s — demuxing "
          f"packets, not decoding\n")
    with cf.ThreadPoolExecutor(len(cams)) as ex:
        recs = list(ex.map(lambda c: measure_camera(c, a.seconds), cams))

    print(f"{'camera':<9}{'packets':>9}{'MB':>9}{'Mbps':>8}{'keyframes':>11}")
    total_bytes = total_seconds = 0.0
    live = []
    for r in sorted(recs, key=lambda x: x.camera_id):
        if r.error:
            print(f"{r.camera_id:<9} unreachable — {r.error}")
            continue
        live.append(r)
        total_bytes += r.video_bytes
        total_seconds = max(total_seconds, r.seconds)
        print(f"{r.camera_id:<9}{r.packets:>9,}{r.video_bytes / 1e6:>9.1f}"
              f"{r.bitrate_mbps:>8.2f}{r.keyframes:>11}")

    if not live:
        print("\nno camera delivered packets; nothing measured")
        return 1

    n_obs, obs_bytes, sample = event_bytes(store, cams)
    if not n_obs:
        print("\nno observations stored for these cameras — run an ingest "
              "first, or the metadata side of this comparison is invented")
        return 1

    per_obs = obs_bytes / n_obs
    aggregate_mbps = total_bytes * 8 / total_seconds / 1e6

    # Event rate at **peak**, not averaged over the whole store.
    #
    # Averaging across everything the store holds divides by the idle hours
    # between capture runs and produces a rate an order of magnitude below what
    # the link ever carries — which flatters this comparison by exactly the
    # factor it is meant to measure. A first version of this tool did that and
    # reported 1,421x; the honest figure is far smaller. Provisioning a link is
    # decided by the busiest minute, so that is what is measured.
    from sqlalchemy import select

    from saakshya.store import schema as S
    with store.engine.connect() as c:
        stamps = [r[0] for r in c.execute(
            select(S.observations.c.t_norm_us)
            .where(S.observations.c.camera_id.in_(cams))
            .order_by(S.observations.c.t_norm_us))]
    if a.observations_per_camera_hour:
        obs_per_s = a.observations_per_camera_hour / 3600 * len(live)
        rate_basis = "declared"
    elif len(stamps) < 2:
        obs_per_s, rate_basis = 0.0, "too few observations to measure"
    else:
        window_us = 60 * 1_000_000
        best = 0
        j = 0
        for i in range(len(stamps)):                   # sliding 60s window
            while stamps[i] - stamps[j] > window_us:
                j += 1
            best = max(best, i - j + 1)
        obs_per_s = best / 60.0
        rate_basis = f"busiest 60s window in the store: {best} observations"
    event_mbps = obs_per_s * per_obs * 8 / 1e6

    print(f"\nvideo      : {total_bytes / 1e6:,.1f} MB over {total_seconds:.0f}s "
          f"from {len(live)} camera(s) = {aggregate_mbps:.2f} Mbps")
    print(f"observation: {per_obs:,.0f} bytes each, measured on {n_obs} real "
          f"records with full provenance")
    print(f"event rate : {obs_per_s:.2f}/s across these cameras ({rate_basis})")
    print(f"events     : {event_mbps:.5f} Mbps")
    ratio = aggregate_mbps / event_mbps if event_mbps else float("inf")
    print(f"\nratio      : video is {ratio:,.0f}x the metadata for this scene")
    print("\nMEASURED on this estate at this hour, with the event side taken at "
          "peak rather than averaged across idle time. Both numbers move with "
          "scene activity — a busy junction produces more events *and* more "
          "video — so this is one point, not a constant, and not a claim about "
          "the whole estate.")

    payload = {
        "measured_at": datetime.now(UTC).isoformat(),
        "seconds": round(total_seconds, 1),
        "cameras": [r.__dict__ for r in recs],
        "video_bytes": int(total_bytes),
        "video_mbps": round(aggregate_mbps, 3),
        "observation_bytes_each": round(per_obs, 1),
        "observations_sampled": n_obs,
        "events_per_second": round(obs_per_s, 3),
        "event_rate_basis": rate_basis,
        "event_mbps": round(event_mbps, 6),
        "ratio": round(ratio, 1),
        "sample_observation": sample,
        "note": ("Video is demuxed, not decoded: this measures the link, not "
                 "the host. Observation size is taken from real records "
                 "carrying full provenance, because a stripped example would "
                 "flatter the result."),
    }
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(payload, indent=2, default=str))
        print(f"written    : {display(a.out, ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
