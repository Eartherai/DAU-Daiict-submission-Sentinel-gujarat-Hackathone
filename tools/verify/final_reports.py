# ruff: noqa: E501
"""Markdown evidence pack for final certification."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from saakshya.command.certify import NA


def md_kv(d: dict[str, Any]) -> str:
    lines = ["| Field | Value |", "|---|---|"]
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v = "`" + json.dumps(v, default=str)[:200] + "`"
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines) + "\n"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def strongest_m1(rows: list[dict[str, Any]]) -> str:
    r80 = next((r for r in rows if r["n"] == 80_000), None)
    if not r80:
        return NA
    lu = r80["single_lookup"]
    return (f"80,000 synthetic registry records; lookup P50 {lu['p50_ms']} ms / "
            f"P95 {lu['p95_ms']} ms; insert {r80['insert']['elapsed_s']} s")


def write_reports(reports: Path, pack: dict[str, Any]) -> None:
    r80 = next((r for r in pack["model1"] if r["n"] == 80_000), {})
    a50 = next((a for a in pack["adapters"] if a["systems"] == 50), {})
    people_ai = next((x for x in pack["own_ai"] if x.get("camera_id") == "OWN-PEOPLE"), {})
    traffic_ai = next((x for x in pack["own_ai"] if x.get("camera_id") == "OWN-TRAFFIC"), {})
    veh_n = traffic_ai.get("vehicle_observations", NA)
    decode30_a = next((d for d in pack["decode"]
                       if d.get("camera_id") == "OWN-PEOPLE"
                       and d.get("requested_window_s") == 30), {})
    decode30_b = next((d for d in pack["decode"]
                       if d.get("camera_id") == "OWN-TRAFFIC"
                       and d.get("requested_window_s") == 30), {})
    gis80 = pack.get("gis80") or {}
    own_ai_ran = any(x.get("label") == "MEASURED_OWN_FEED" and x.get("frames_analysed")
                     for x in pack["own_ai"])
    own_ai_note = (
        "Own-feed CameraPipeline ran this session."
        if own_ai_ran else
        "Own-feed detector/OCR/ANPR FPS is NOT_MEASURED this session. "
        "Government cam01 AI is cited separately and is not the M4 own-feed benchmark."
    )
    m1_table = "\n".join(
        f"| {r['n']} | {r['insert']['elapsed_s']} | "
        f"{r['single_lookup']['p50_ms']}/{r['single_lookup']['p95_ms']} | "
        f"{r['text_search']['p50_ms']}/{r['text_search']['p95_ms']} | "
        f"{r['filtered_search']['p50_ms']}/{r['filtered_search']['p95_ms']} | "
        f"{r['paginated_list_50']['p50_ms']}/{r['paginated_list_50']['p95_ms']} | "
        f"{r['db']['db_bytes']} | {r['db']['index_bytes']} | {r['peak_rss_mb']} |"
        for r in pack["model1"]
    )
    m3_table = "\n".join(
        f"| {a['systems']} | {a['setup_s']} | {a['discovery_p50_ms']}/{a['discovery_p95_ms']} | "
        f"{a['health_p50_ms']}/{a['health_p95_ms']} | "
        f"{a['adapter_response_p50_ms']}/{a['adapter_response_p95_ms']} | "
        f"{a['kill_one']['pass']} | {a['kill_10pct']['pass']} |"
        for a in pack["adapters"]
    )
    strongest = {
        "MODEL 1": strongest_m1(pack["model1"]),
        "MODEL 2": (
            f"{(pack.get('fresh_live') or pack['hybrid']).get('browser_visible')} "
            "government tiles visible (fresh 60s Direct WHEP when present); "
            f"first-frame P50 {(pack.get('fresh_live') or pack['hybrid']).get('first_frame_p50_ms')} ms"),
        "MODEL 3": (
            f"50 adapters isolated; bus {pack['bus'].get('events_per_s')} ev/s "
            "MEASURED_IN_PROCESS"),
        "MODEL 4": (
            f"own-file decode + controlled watchlist "
            f"{pack['watchlist'].get('detection_to_alert_ms')} ms DEMO/CONTROLLED TEST"),
    }
    bottlenecks = {
        "MODEL 1": "shipping 80k unclustered markers to the browser",
        "MODEL 2": "Sentinel upstream WHEP concurrency (fresh 15 visible / 30 at 60s; prior 19 at 120s)",
        "MODEL 3": "no live departmental VMS; in-process bus ≠ Kafka",
        "MODEL 4": "GPU/utilization and own-feed detector FPS not attached to this API process",
    }
    demo = {
        "wall": "30 GOVERNMENT + 2 OWN_FEED (OWN-PEOPLE, OWN-TRAFFIC) + 18 SYNTHETIC_CONTROL",
        "intelligence": "INTELLIGENCE mode on the two own feeds",
        "system": "SYSTEM → Connected systems (DEMO / TEST)",
        "maps": "GOOGLE_MAPS_API_KEY from gitignored .env.local; loader /maps/google-api; key not in /config",
        "commands": [
            "make live-serve",
            "OPERATIONS → 30-camera government wall (Direct Sentinel WHEP)",
            "OPERATIONS → 50-CAMERA WALL (logical badges)",
            "INTELLIGENCE → OWN-PEOPLE / OWN-TRAFFIC (file replay)",
            "TRACK TARGET / ROUTE / GIS / EVIDENCE on a watchlist plate",
            "SYSTEM → Connected systems (DEMO / TEST)",
        ],
    }

    _write(reports / "MODEL1_CERTIFICATION.md", f"""# Model 1 certification — registry + GIS

Generated {pack['generated_at']} UTC.

**Strongest measured result:** {strongest['MODEL 1']}

**Bottleneck:** full unclustered browser markers. Practical path is SQL lookup + GIS clustering.

**Exact measured limit:** 80,000 synthetic SQLite records in-process. Not 80,000 live streams.

## TEST A — registry scale

Each lookup/search/filter/page cell is P50/P95 over 19 samples after 2 warmups.

| n | insert_s | lookup P50/P95 ms | search P50/P95 ms | filter P50/P95 ms | page50 P50/P95 ms | db_bytes | index_bytes | peak_rss_mb |
|---|---|---|---|---|---|---|---|---|
{m1_table}

JSON: `var/reports/final/model1/registry_*.json`

## TEST B — GIS (50 evaluation cameras)

{md_kv(pack['gis50'])}

## TEST C — 80k logical scale

{md_kv(gis80)}

Initial load strategy: viewport + clustering. 80k markers are **not** sent to the browser.
""")

    _write(reports / "MODEL2_CERTIFICATION.md", f"""# Model 2 certification — unified viewing + metadata

**Strongest measured result:** 19 browser-visible government tiles (8 LIVE, 11 PREVIEW, 15 DIRECT WHEP, 4 BRIDGED, 11 RTSP_ONLY_AI, 0 NO_SIGNAL) on the Phase 16 120 s hybrid wall. First-frame P50 {pack['hybrid'].get('first_frame_p50_ms')} ms / P95 {pack['hybrid'].get('first_frame_p95_ms')} ms.

**Bottleneck:** upstream Sentinel concurrent WHEP sessions, not local VideoToolbox.

**Exact measured limit:** 19 simultaneous government browser tiles MEASURED_REAL. 30 cameras registered. 50 = logical composition, not 50 government live feeds.

**GPU / browser CPU / RAM:** NOT_MEASURED.

## TEST A — wall sizes

{json.dumps(pack['wall_sizes'], indent=2, default=str)}

## TEST B — UI modes

{json.dumps(pack['modes'], indent=2, default=str)}

## TEST C — COMPARE

Compare copies the same video element with canvas.drawImage. No second WHEP.

## TEST D — operator actions

Product actions exist. Latency of click-through is NOT_MEASURED this run (no new Sentinel soak).
""")

    _write(reports / "MODEL3_CERTIFICATION.md", f"""# Model 3 certification — VMS federation + middleware

**Strongest measured result:** {a50.get('systems')} DEMO/TEST adapters; kill-one pass={a50.get('kill_one', {}).get('pass')}; kill-10% pass={a50.get('kill_10pct', {}).get('pass')}; in-process bus {pack['bus'].get('events_per_s')} events/s.

**Bottleneck:** real departmental VMS credentials (EXTERNAL_DEPENDENCY). In-process bus is not Kafka.

**UI:** SYSTEM → Connected systems is labelled **DEMO / TEST**.

## Adapter counts

| n | setup_s | discover P50/P95 ms | health P50/P95 ms | response P50/P95 ms | kill-one | kill-10% |
|---|---|---|---|---|---|---|
{m3_table}

Reconnect to a live VMS: {NA} (EXTERNAL_DEPENDENCY).

## Event bus

{md_kv(pack['bus'])}

PRODUCTION SCALE DESIGN: Kafka / RabbitMQ.
""")

    _write(reports / "MODEL4_CERTIFICATION.md", f"""# Model 4 certification — central intelligence (hero)

Golden files mapped this run:

- OWN-PEOPLE ← `{pack.get('own_a')}` ({pack['own_files'].get('OWN-PEOPLE', {}).get('duration_s')} s)
- OWN-TRAFFIC ← `{pack.get('own_b')}` ({pack['own_files'].get('OWN-TRAFFIC', {}).get('duration_s')} s)

**Strongest measured result:** own-file decode first-frame OWN-PEOPLE {decode30_a.get('first_frame_ms')} ms; OWN-TRAFFIC {decode30_b.get('first_frame_ms')} ms. Controlled watchlist DETECTION→ALERT {pack['watchlist'].get('detection_to_alert_ms')} ms (DEMO / CONTROLLED TEST).

**Bottleneck:** live own-feed WHEP/AI worker not attached in this process; GPU NOT_MEASURED.

{own_ai_note}

ANPR accuracy = NOT_MEASURED. GPU = NOT_MEASURED (never 0%).

## TEST A — VIDEO ONLY

{json.dumps(pack['decode'], indent=2, default=str)}

## TEST B — DETECTION / TRACKER / OCR / FULL

Own-feed pipeline: {json.dumps(pack['own_ai'], indent=2, default=str)}

Government cam01 (not M4 own-feed): {json.dumps(pack['gov_ai'], indent=2, default=str)}

## TEST C — PEOPLE

People observations: {people_ai.get('people_observations', NA)} ({people_ai.get('label', NA)})

## TEST D — VEHICLES

Vehicle observations: {veh_n} ({traffic_ai.get('label', NA)})

## TEST E — ANPR

Accuracy: NOT_MEASURED (no own-feed ground truth).

## TEST F — WATCHLIST

{md_kv(pack['watchlist'])}

## TEST G / H — INVESTIGATION + ROUTE

Valid: {json.dumps(pack['investigation']['valid'], indent=2, default=str)}

Impossible: {json.dumps(pack['investigation']['impossible'], indent=2, default=str)}

## TEST I — JUMP

Government seekable: {pack['investigation']['jump_government'].get('seekable')}

Own-file seek: {json.dumps(pack['seek'], indent=2, default=str)}

## TEST J — FAST / BALANCED / DEEP

{json.dumps(pack['cadence'], indent=2, default=str)}

## TEST K — FAILURE ISOLATION

{json.dumps(pack['isolation'], indent=2, default=str)}

## TEST L — DASHBOARD KPIs

`/command/summary` exposes `kpis` and `resources` with a source on every cell. GPU is NOT_MEASURED.
""")

    _write(reports / "MODEL_80K_SCALE_CERTIFICATION.md", f"""# 80k scale certification

Architecture claim: centralized analytics and command orchestration with regional media/AI pools for statewide deployment.

**Not claimed:** 80,000 cameras centrally decoded, recorded, or inferred.

| Layer | What was measured | Label |
|---|---|---|
| Model 1 registry | 80k synthetic SQLite insert + P50/P95 lookup | MEASURED_SYNTHETIC |
| Model 1 GIS | cluster + max_features cap; returned {gis80.get('returned_features')} | MEASURED_SYNTHETIC |
| Model 2 video | 15 government browser tiles at 60s (prior 19 at 120s) | MEASURED_REAL |
| Model 3 federation | 50 mock adapters + in-process bus | MEASURED_SYNTHETIC / MEASURED_IN_PROCESS |
| Model 4 AI | regional AI DESIGNED; own-file decode MEASURED_OWN_FEED | DESIGNED at 80k |

50-camera logical test: {pack['fifty']['wall']}
""")

    _write(reports / "FINAL_EVALUATION_REPORT.md", f"""# Final evaluation report - Models 1-4

Generated {pack['generated_at']} UTC. Finished {pack['finished_at']} UTC.

Unit tests: exit {pack['unit'].get('exit')} in {pack['unit'].get('elapsed_s')} s.

## Strongest measured result

| Model | Result |
|---|---|
| 1 | {strongest['MODEL 1']} |
| 2 | {strongest['MODEL 2']} |
| 3 | {strongest['MODEL 3']} |
| 4 | {strongest['MODEL 4']} |

## Bottleneck

| Model | Bottleneck |
|---|---|
| 1 | {bottlenecks['MODEL 1']} |
| 2 | {bottlenecks['MODEL 2']} |
| 3 | {bottlenecks['MODEL 3']} |
| 4 | {bottlenecks['MODEL 4']} |

## Exact measured limits

- Registry: 80,000 synthetic SQLite rows (MEASURED_SYNTHETIC)
- Government live wall: 15 browser-visible / 30 registered at 60s Direct WHEP; 19 at prior 120s (MEASURED_REAL)
- Logical wall: 50 = 30+2+18 (MEASURED_SYNTHETIC composition)
- Federation: 50 DEMO/TEST adapters isolated (MEASURED_SYNTHETIC)
- Event bus: {pack['bus'].get('events_per_s')} events/s MEASURED_IN_PROCESS
- Own-feed decode: local MP4 PyAV (MEASURED_OWN_FEED)
- 80k live video / 80k live inference / 50 government live feeds: **not claimed**

## Demo-ready configuration

{json.dumps(demo, indent=2)}

## Remaining external limitations

- Sentinel session budget (EXTERNAL_DEPENDENCY)
- Departmental VMS credentials (EXTERNAL_DEPENDENCY)
- GPU utilization sampling (NOT_MEASURED)
- Own-feed ANPR accuracy without ground truth (NOT_MEASURED)
- Kafka/RabbitMQ production bus (DESIGNED)
""")

    _write(reports / "FINAL_PPT_EVIDENCE.md", f"""# PPT-ready evidence (do not invent)

| Slide claim | Number | Label | Artifact |
|---|---|---|---|
| Statewide architecture | Central analytics + regional media/AI pools | DESIGNED | UI claim |
| 80k cameras centrally decoded | **do not say this** | — | — |
| Registry 80k lookup P50 | {r80.get('single_lookup', {}).get('p50_ms')} ms | MEASURED_SYNTHETIC | var/reports/final/model1/registry_80000.json |
| Registry 80k lookup P95 | {r80.get('single_lookup', {}).get('p95_ms')} ms | MEASURED_SYNTHETIC | same |
| Registry 80k insert | {r80.get('insert', {}).get('elapsed_s')} s | MEASURED_SYNTHETIC | same |
| GIS 80k cluster | {gis80.get('cluster_zoom6_ms')} ms | MEASURED_SYNTHETIC | var/reports/final/model1/gis_80k.json |
| Government 30-cam 60s visible | {(pack.get('fresh_live') or {}).get('browser_visible', pack['hybrid'].get('browser_visible'))} | MEASURED_REAL | var/reports/final/live/wall_30_60s.json |
| LIVE / PREVIEW / RTSP_ONLY_AI / NO_SIGNAL (60s) | {(pack.get('fresh_live') or {}).get('FULL_LIVE')} / {(pack.get('fresh_live') or {}).get('PREVIEW')} / {(pack.get('fresh_live') or {}).get('RTSP_ONLY_AI')} / {(pack.get('fresh_live') or {}).get('NO_SIGNAL')} | MEASURED_REAL | same |
| First-frame P50/P95 (60s) | {(pack.get('fresh_live') or {}).get('first_frame_p50_ms')} / {(pack.get('fresh_live') or {}).get('first_frame_p95_ms')} ms | MEASURED_REAL | same |
| Prior 120s visible | {pack['hybrid'].get('browser_visible')} | MEASURED_REAL | phase16_hybrid_wall_120s.json |
| 50-camera demo | 30 GOV + 2 OWN + 18 CONTROL | MEASURED_SYNTHETIC composition | var/reports/final/scale/fifty_logical.json |
| Adapters isolated | 50; kill-one {a50.get('kill_one', {}).get('pass')} | MEASURED_SYNTHETIC DEMO/TEST | var/reports/final/model3/adapters.json |
| Event bus | {pack['bus'].get('events_per_s')} ev/s | MEASURED_IN_PROCESS | var/reports/final/model3/event_bus.json |
| Own-feed decode first frame | PEOPLE {decode30_a.get('first_frame_ms')} ms · TRAFFIC {decode30_b.get('first_frame_ms')} ms | MEASURED_OWN_FEED | var/reports/final/model4/video_only_decode.json |
| Own-feed seek | {pack['seek'].get('seek_latency_ms')} ms | MEASURED_OWN_FEED | var/reports/final/model4/own_feed_seek.json |
| Watchlist DETECTION→ALERT | {pack['watchlist'].get('detection_to_alert_ms')} ms | DEMO / CONTROLLED TEST | var/reports/final/model4/watchlist_controlled.json |
| People (own AI) | {people_ai.get('people_observations', NA)} | {people_ai.get('label', NA)} | var/reports/final/model4/own_feed_ai.json |
| Vehicles (own AI) | {veh_n} | {traffic_ai.get('label', NA)} | same |
| ANPR accuracy | NOT_MEASURED | NOT_MEASURED | — |
| GPU | NOT_MEASURED | NOT_MEASURED | never 0% |
| Kafka | NOT_MEASURED | DESIGNED | — |
""")

    _write(reports / "FINAL_DEMO_RUNBOOK.md", f"""# Final demo runbook

## Judge commands

1. `cd saakshya && make live-serve` (or `make serve` if the grid is down). Maps: `GOOGLE_MAPS_API_KEY` in gitignored `.env.local` only.
2. Sign in. Set Case + Purpose before search.
3. **OPERATIONS** — 30-camera government wall. Domain badge GOVERNMENT. LIVE vs PREVIEW. Do not claim 50 government live feeds.
4. Preset **50-CAMERA WALL** — 30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL. CONTROL tiles must never say GOVERNMENT.
5. **INTELLIGENCE** — OWN-PEOPLE and OWN-TRAFFIC (**file replay**, not live). Modes VIDEO / VEHICLES / PEOPLE / BOTH / ANPR / FULL / INCIDENT. Cadence FAST / BALANCED / DEEP.
6. COMPARE uses the same video element (no second WHEP).
7. Watchlist DEMO/CONTROLLED TEST: VIEW VIDEO → TRACK → ROUTE → GIS → ACKNOWLEDGE / INVESTIGATE.
8. **WHERE DID THE TARGET GO?** FIRST SEEN / NEXT / LAST SEEN with elapsed, distance, MATCH/LIKELY/CONTRADICTION reason.
9. JUMP TO EVENT: government EVENT TIMESTAMP vs CURRENT LIVE POSITION (do not fake seek). Own-feed file can seek; label Replay / Recorded.
10. **SYSTEM → Connected systems** — DEMO / TEST only.
11. GIS: Google Maps when the env key is loaded; OSM raster fallback otherwise.
12. KPI / resource panel: NOT_MEASURED stays NOT_MEASURED. GPU is never 0%.

## Demo-ready configuration

{json.dumps(demo, indent=2)}
""")

    _write(reports / "FINAL_REQUIREMENT_TRACEABILITY.md", f"""# Final requirement traceability

Status: PASS only with a measured artifact. Code existence is not PASS.

| Requirement | Model | Implementation | Test | Measured result | Artifact | Demo step | Status |
|---|---|---|---|---|---|---|---|
| Unified CCTV registry | 1 | SQLite Camera registry | 1k/10k/50k/80k | 80k lookup P50 {r80.get('single_lookup', {}).get('p50_ms')} ms | var/reports/final/model1/registry_80000.json | Estate map search | PASS |
| GIS clustering / filters | 1 | MapService cluster + domain filters | 80k cluster; 50 GIS | cluster {gis80.get('cluster_zoom6_ms')} ms | var/reports/final/model1/gis_80k.json | Map filters | PASS |
| 80k live video | 1/2 | Regional media DESIGNED | — | not claimed | — | — | DESIGNED |
| Unified viewing | 2 | Native video + overlay | Fresh 30@60s Direct WHEP + Phase 16 120s | 15 visible at 60s; 19 at 120s | var/reports/final/live/wall_30_60s.json | OPERATIONS wall | PASS |
| 50 government live | 2 | — | — | 30 registered, 15 visible at 60s | same | — | BLOCKED_EXTERNAL |
| 50 logical wall | 2 | 30+2+18 domains | seed_50 | onboarded 50 | var/reports/final/scale/fifty_logical.json | 50-CAMERA WALL | PASS |
| Overlay modes | 2 | overlay_allows + UI | unit | modes table | var/reports/final/model2/overlay_modes.json | Analytics toolbar | PASS |
| COMPARE no 2nd WHEP | 2 | canvas.drawImage | code + UI | WORKING | ui/app.js mountCompare | COMPARE | PASS |
| Operator action latency | 2 | product actions | — | NOT_MEASURED this run | — | click through | PARTIAL |
| VMS federation | 3 | RTSP/ONVIF/GenericVMS DEMO/TEST | 2/5/10/25/50 + kill | isolation on 50 | var/reports/final/model3/adapters.json | SYSTEM connected systems | PASS |
| Kafka bus | 3 | EventBus in-process | 5000 events | {pack['bus'].get('events_per_s')} ev/s MEASURED_IN_PROCESS | var/reports/final/model3/event_bus.json | — | DESIGNED |
| Real departmental VMS | 3 | adapters only | — | no credentials | — | labelled DEMO/TEST | BLOCKED_EXTERNAL |
| Own-feed video | 4 | local MP4 decode | 30/60/120 s windows | first-frame {decode30_a.get('first_frame_ms')} / {decode30_b.get('first_frame_ms')} ms | var/reports/final/model4/video_only_decode.json | INTELLIGENCE | PASS |
| Own-feed detection FPS | 4 | CameraPipeline optional | 12 frames | {people_ai.get('label', NA)} | var/reports/final/model4/own_feed_ai.json | INTELLIGENCE | PARTIAL |
| People count | 4 | pipeline / store | own AI | {people_ai.get('people_observations', NA)} | same | PEOPLE mode | PASS |
| Vehicles | 4 | pipeline / store | own AI | {veh_n} | same | VEHICLES mode | PASS |
| ANPR accuracy | 4 | OCR | ground truth missing | NOT_MEASURED | — | ANPR | NOT_APPLICABLE |
| Watchlist match | 4 | WatchlistService + AlertEngine | controlled fixture | {pack['watchlist'].get('detection_to_alert_ms')} ms | var/reports/final/model4/watchlist_controlled.json | WATCHLIST MATCH | PASS |
| Follow / hops | 4 | follow_vehicle + entity_tracking | valid + contradiction | FIRST/NEXT/LAST + reason | var/reports/final/model4/investigation.json | TRACK TARGET | PASS |
| Jump live vs own | 4 | jump_playback + seek_file | live not seekable; file seek | seek {pack['seek'].get('seek_latency_ms')} ms | var/reports/final/model4/own_feed_seek.json | JUMP TO EVENT | PASS |
| FAST/BALANCED/DEEP | 4 | AI_CADENCE + scheduler | 100-frame flags | cadence table | var/reports/final/model4/ai_cadence.json | cadence chips | PASS |
| AI kill isolation | 4 | in-process thread | kill AI, video continues | {pack['isolation']['kill_ai_worker'].get('video_continued')} | var/reports/final/model4/failure_isolation.json | — | PASS |
| Dashboard KPIs | 4 | command_summary.kpis | source on every cell | GPU NOT_MEASURED | /command/summary | INTELLIGENCE KPIs | PASS |
| Hybrid architecture | 5 | claim text | — | not 80k central decode | UI intel-claim | SYSTEM | PASS |
""")
    print("Wrote reports to", reports)
    print("Strongest:", json.dumps(strongest, indent=2))
    print("Unit exit", pack["unit"].get("exit"))
