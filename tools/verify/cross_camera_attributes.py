"""Attribute-based cross-camera correlation on live observations.

Plates cannot carry this. Measured across three clusters, roughly two cameras
in five produce a plate crop at all: cam14 and cam16 saw 2,781 vehicles between
them and yielded not one. A statewide system therefore cannot make movement
reconstruction depend on ANPR, and this is the path that works on the other
three in five.

What this is NOT: an identity claim. The repository already measured a DINOv2
embedding on this government feed - same vehicle mean 0.830, different vehicles
mean 0.576, best balanced accuracy 0.831 - and concluded the distributions
overlap too much to assert that two sightings are one vehicle. That conclusion
governs here. This ranks candidates for an investigator to accept or reject,
and every row carries the evidence it was ranked on.

Scoring, all of it explainable to the officer reading it:

    colour agreement   colour_agreement()  1.0 exact, 0.5 an expected confusion
    size agreement     size_agreement()    1.0 exact, 0.5 adjacent class
    travel plausibility 1.0 when the gap between sightings fits a 15-90 km/h
                        crossing of the real distance between the two cameras,
                        tapering outside it
    quality            the lower of the two observation qualities
    distinctiveness    how rare that description is in this window

Distinctiveness is the part that makes the output usable. Without it the
ranking fills with grey cars: a grey car matching a grey car scores 1.0 on
colour while carrying almost no information, because 1,677 other grey cars were
seen in the same window. The score is therefore damped by how many vehicles
share the description, and every row states that count so the officer can see
the ambiguity rather than infer it from a number.

A candidate is only offered when colour and size both agree at all, because a
pair matched on timing alone is not evidence of anything.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from saakshya.analytics.attributes import colour_agreement, size_agreement

#: Plausible road speeds between two fixed cameras, km/h.
MIN_KMH, MAX_KMH = 15.0, 90.0
#: A pair seen closer together in time than this is one camera's own track.
MIN_GAP_S = 5.0


def haversine_km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def travel_plausibility(km: float, gap_s: float) -> tuple[float, float | None]:
    """1.0 when the implied speed is an ordinary road speed, tapering outside."""
    if gap_s <= MIN_GAP_S:
        return 0.0, None
    kmh = km / (gap_s / 3600.0)
    if MIN_KMH <= kmh <= MAX_KMH:
        return 1.0, kmh
    ref = MIN_KMH if kmh < MIN_KMH else MAX_KMH
    return max(0.0, 1.0 - abs(kmh - ref) / ref), kmh


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "var/live.db"))
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--district", default=None)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    c = sqlite3.connect(a.db)
    cams = {r[0]: {"name": r[1], "district": r[2], "lat": r[3], "lon": r[4]}
            for r in c.execute(
                "select camera_id,name,district,lat,lon from cameras "
                "where lat is not null and lon is not null")}
    cut = int((time.time() - a.minutes * 60) * 1_000_000)
    rows = c.execute(
        "select observation_id,camera_id,object_type,colour,colour_confidence,"
        "observation_quality,t_ingest_us,track_id from observations "
        "where t_ingest_us > ? and colour is not null and colour <> '' "
        "and object_type is not null order by t_ingest_us", (cut,)).fetchall()

    obs = []
    for o in rows:
        cam = cams.get(o[1])
        if not cam:
            continue
        if a.district and cam["district"] != a.district:
            continue
        obs.append({"id": o[0], "cam": o[1], "type": o[2], "colour": o[3],
                    "colour_conf": o[4] or 0.0, "quality": o[5] or 0.0,
                    "ts": o[6] / 1_000_000, "track": o[7],
                    "name": cam["name"], "district": cam["district"],
                    "lat": cam["lat"], "lon": cam["lon"]})

    # How common is each description in this window? A match on a description
    # shared by hundreds of vehicles is not evidence, however well it scores on
    # colour and size, and the ranking must say so.
    from collections import Counter
    desc_counts = Counter((o["type"], o["colour"]) for o in obs)

    by_cam = {}
    for o in obs:
        by_cam.setdefault(o["cam"], []).append(o)
    print(f"observations with attributes: {len(obs)} across {len(by_cam)} cameras")
    for k, v in sorted(by_cam.items()):
        print(f"  {k} {v[0]['name'][:26]:<28}{len(v)} obs  ({v[0]['district']})")
    if len(by_cam) < 2:
        print("\nNeed two cameras with attributed observations to correlate.")
        return 1

    cands = []
    cam_ids = sorted(by_cam)
    for i, ca in enumerate(cam_ids):
        for cb in cam_ids[i + 1:]:
            km = haversine_km(by_cam[ca][0]["lat"], by_cam[ca][0]["lon"],
                              by_cam[cb][0]["lat"], by_cam[cb][0]["lon"])
            for x in by_cam[ca]:
                for y in by_cam[cb]:
                    col = colour_agreement(x["colour"], y["colour"])
                    siz = size_agreement(x["type"], y["type"])
                    if col <= 0 or siz <= 0:
                        continue          # timing alone is not evidence
                    gap = abs(y["ts"] - x["ts"])
                    trav, kmh = travel_plausibility(km, gap)
                    if trav <= 0:
                        continue
                    q = min(x["quality"], y["quality"])
                    # Inverse-frequency damping: a description shared by n
                    # vehicles in this window carries roughly 1/log(n) of the
                    # weight of a unique one.
                    shared = max(desc_counts[(x["type"], x["colour"])],
                                 desc_counts[(y["type"], y["colour"])])
                    distinct = 1.0 / (1.0 + math.log(max(1, shared)))
                    score = ((0.30 * col + 0.15 * siz + 0.20 * trav + 0.05 * q)
                             * (0.35 + 0.65 * distinct)) + 0.30 * distinct
                    first, second = (x, y) if x["ts"] <= y["ts"] else (y, x)
                    cands.append({
                        "score": round(score, 3),
                        "colour_agreement": col, "size_agreement": siz,
                        "travel_plausibility": round(trav, 3),
                        "implied_kmh": round(kmh, 1) if kmh else None,
                        "distance_km": round(km, 2), "gap_s": round(gap, 1),
                        "quality": round(q, 3),
                        "shares_description_with": shared,
                        "distinctiveness": round(distinct, 3),
                        "colour": f'{x["colour"]}/{y["colour"]}',
                        "type": f'{x["type"]}/{y["type"]}',
                        "from": {"camera": first["cam"], "name": first["name"],
                                 "lat": first["lat"], "lon": first["lon"],
                                 "observation_id": first["id"],
                                 "at": time.strftime("%H:%M:%S", time.localtime(first["ts"]))},
                        "to": {"camera": second["cam"], "name": second["name"],
                               "lat": second["lat"], "lon": second["lon"],
                               "observation_id": second["id"],
                               "at": time.strftime("%H:%M:%S", time.localtime(second["ts"]))},
                    })

    cands.sort(key=lambda r: -r["score"])
    top = cands[:a.limit]
    print(f"\nRANKED CANDIDATES (not identity claims): {len(cands)} scored, showing {len(top)}")
    print(f"  {'score':>6} {'colour':<13}{'type':<14}{'gap':>6} {'km/h':>6} {'shared':>7}  route")
    for r in top:
        print(f"  {r['score']:>6.3f} {r['colour']:<13}{r['type']:<14}"
              f"{r['gap_s']:>6.0f}s{r['implied_kmh']!s:>6}{r['shares_description_with']:>7}  "
              f"{r['from']['camera']}->{r['to']['camera']} "
              f"({r['from']['at']} -> {r['to']['at']})")

    if top:
        b = top[0]
        print("\nTOP CANDIDATE — GIS ROUTE")
        print(f"  {b['from']['name']} ({b['from']['camera']}) "
              f"{b['from']['lat']:.5f},{b['from']['lon']:.5f} at {b['from']['at']}")
        print(f"       | {b['distance_km']} km, {b['gap_s']:.0f}s, "
              f"implied {b['implied_kmh']} km/h")
        print(f"  {b['to']['name']} ({b['to']['camera']}) "
              f"{b['to']['lat']:.5f},{b['to']['lon']:.5f} at {b['to']['at']}")
        print(f"  matched on: colour {b['colour']} (agreement {b['colour_agreement']}), "
              f"size {b['type']} (agreement {b['size_agreement']})")
        print(f"  {b['shares_description_with']} vehicles in this window share that "
              f"description (distinctiveness {b['distinctiveness']})")
        print("  CANDIDATE for investigator review - appearance correlation, not identity.")

    if a.json:
        Path(a.json).write_text(json.dumps(
            {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "window_minutes": a.minutes,
             "observations_considered": len(obs),
             "cameras": {k: {"name": v[0]["name"], "district": v[0]["district"],
                             "lat": v[0]["lat"], "lon": v[0]["lon"],
                             "observations": len(v)} for k, v in by_cam.items()},
             "candidates_scored": len(cands), "candidates": top,
             "basis": "appearance correlation (colour + size + travel time); "
                      "ranked for review, not an identity assertion"},
            indent=1))
        print(f"\nwrote {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
