#!/usr/bin/env python3
"""Capacity and binding-constraint model for docs/STATEWIDE_ARCHITECTURE.md §10-§14.

Every input carries a label:
  M  MEASURED   - a committed file in var/reports or reports holds it; the
                  value is read from that file, not transcribed
  V  VERIFIED   - checked read-only against the government store
                  (var/live.db, gitignored) or by tools/sizing/measure_compression.py
  A  ASSUMED    - a planning input nobody here measured; source class stated
  D  DESIGNED   - a choice this architecture makes
Every output is MODELLED: arithmetic on the inputs below. Run:

    python tools/sizing/capacity_model.py   # prints tables, writes reports/capacity_model.json

Importing the module computes the model (``R``) without writing anything;
tests/unit/test_capacity_model.py pins its conclusions.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/capacity_model.json"
LABELS = {"M": "MEASURED", "V": "VERIFIED", "A": "ASSUMED", "D": "DESIGNED"}

I: dict[str, dict] = {}


def inp(name, value, label, source):
    assert all(part in LABELS for part in label.split("/")), (name, label)
    I[name] = {"value": value, "label": label, "source": source}
    return value


def _report(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


_BANDWIDTH = _report("var/reports/bandwidth.json")
_COMPRESSION = _report("reports/measure_compression.json")
_STORE_ENGINES = _report("var/reports/store_engines.json")
_GIS = _report("var/reports/gis_postgis.json")
_CAMERA_LOAD = _report("var/reports/camera_load.json")
_PIPELINE_DEVICE = _report("var/reports/pipeline_device.json")


# ---------------------------------------------------------------- inputs
OBS_WIRE_B = inp("obs_wire_bytes", _BANDWIDTH["observation_bytes_each"], "M",
                 "var/reports/bandwidth.json:observation_bytes_each")
OBS_Z_B = inp("obs_zlib_bytes_batch100", _COMPRESSION["batches"]["100"]["zlib6_bytes_per_row"], "V",
              "reports/measure_compression.json:batches.100.zlib6_bytes_per_row "
              f"({_COMPRESSION['rows']:,} real government rows)")
OBS_Z_RATIO = inp("obs_zlib_ratio_batch100", _COMPRESSION["batches"]["100"]["zlib6_ratio"], "V",
                  "reports/measure_compression.json:batches.100.zlib6_ratio")
OBS_DISK_SQLITE_B = inp("obs_disk_bytes_sqlite", round(901_152_768 / 1_163_767, 1), "V",
                        "stat var/live.db = 901,152,768 B / 1,163,767 observations (all tables and indexes included)")
PG_ROW_B = inp("pg_row_bytes_with_index", 2 * 1331.7, "A",
               "2 x wire row; PostgreSQL row+index size not measured (HLD §20.5 uses the same factor)")
STORE_OBS = 1_155_325
WINDOW_H = (1_790_246_409.848994 - 1_788_312_287.770108) / 3600  # min/max t_norm_us, cam01-cam30
R_CAL_H = inp("obs_per_camera_calendar_hour", round(STORE_OBS / (30 * WINDOW_H), 1), "V",
              "1,155,325 obs (verified snapshot) / (30 cameras x 537.3 h window) - understates: only 4 slots analysed at a time")
R_SLOT_H = inp("obs_per_analysis_slot_hour", round(STORE_OBS / (4 * WINDOW_H), 1), "V",
               "1,155,325 / (4 slots x 537.3 h) - if the 4 deep-inference slots ran the whole window")
R_MEAN_H = inp("obs_per_active_camera_hour", round(STORE_OBS / 1280, 1), "V",
               "1,155,325 / 1,280 distinct (camera, hour) buckets holding >=1 observation (SQL, var/live.db)")
R_BUSIEST_CAM_H = inp("busiest_camera_mean_per_active_hour", 2529, "V", "per-camera obs/active-hour, maximum over 30 cameras (SQL)")
R_PESS_H = inp("obs_per_camera_hour_pessimistic", 3000, "A",
               "statewide average set above the busiest measured camera's average (2,529/h)")
HOT_CAM_PEAK_H = inp("hot_camera_peak_hour", 11232, "V", "cam04, max obs in one clock hour (SQL)")
HOT_CAM_PEAK_MIN = inp("hot_camera_peak_minute", 491, "V", "cam04, max obs in one minute (SQL)")
PG_WRITE_RPS = inp("pg_write_rows_per_s_one_stream",
                   round(_STORE_ENGINES["migration"]["rows_copied"] / _STORE_ENGINES["migration"]["seconds"]), "M",
                   "var/reports/store_engines.json:migration rows_copied / seconds (single-stream copy, lower bound)")
PLATE_SEARCH_MS = inp("pg_plate_search_p50_ms_1.16M_rows",
                      _STORE_ENGINES["api_latency"]["GET /search (plate)"]["postgresql_p50_ms"], "M",
                      "var/reports/store_engines.json:api_latency['GET /search (plate)'].postgresql_p50_ms")
GIS_VIEWPORT_MS = inp("postgis_viewport_p50_ms_80k", _GIS["results"]["viewport_0.1deg"]["postgis"]["p50_ms"], "M", "var/reports/gis_postgis.json:results.viewport_0.1deg.postgis.p50_ms")
PIPE_FPS_CPU = inp("full_pipeline_fps_cpu_4cams", 5.6, "M",
                   "reports/SCALE_80K_LOAD_TEST.md 'aggregate ~5.6 fps' and analytics/worker.py:358-360 comment (no JSON key)")
S_GPU = inp("gpu_speedup_S", 10, "A", "HLD §20.2 planning assumption; only S measured is "
            f"{_PIPELINE_DEVICE['speedup_median']} (var/reports/pipeline_device.json:speedup_median)")
GPU_FPS = PIPE_FPS_CPU * S_GPU
DECODE_CORES = inp("decode_cores_per_stream", 0.25, "A",
                   "HLD §20.2 derivation (40 streams per 10 cores from camera_load.json 44/50); no per-stream CPU was measured")
RSS_MB = inp("rss_mb_per_camera", round(_CAMERA_LOAD["peak_rss_mb"] / _CAMERA_LOAD["requested_cameras"], 1), "M",
             "var/reports/camera_load.json:peak_rss_mb / requested_cameras")
F_BASE = inp("analysis_fps_default", 1.0, "D", "HLD §17.2 sample_rate_hz")
F_ANPR = inp("analysis_fps_anpr_camera", 5.0, "D",
             "CONFIRM_VOTES=2 (reports/anpr.py:39) needs >=2 frames per pass; 5 fps gives margin")
ANPR_FRAC = inp("anpr_capable_fraction", 0.20, "A", "share of estate graded GOOD/DEGRADED for ANPR; evaluation grid had 0 GOOD")
PLATE_FRAC = inp("plate_fraction_of_anpr_obs", 0.5, "A", "pessimistic; government store 901 plated of 1,155,325 (0.08%)")
PLATE_ROW_B = inp("plate_index_row_bytes", 160, "D", "slim row: folded plate, plate, camera, t, conf, votes, cell, obs ref")
HEALTH_B = inp("health_msg_bytes", 500, "A", "one health sample")
HEALTH_PERIOD_S = inp("health_period_s", 10, "D", "per camera")
CELL_MAX = inp("cameras_per_cell_max", 2500, "D", "HLD §20 planning unit, kept")
CELL_OBS_CAP = inp("observations_per_s_per_cell_max", 4000, "D",
                   "second cell limit, from the highway-heavy hostile case (Self-check)")
N_CELLS = inp("cells", 40, "D", "80,000/2,500 = 32 minimum; 40 lets big districts split and small ones stand alone")
C = inp("cameras_total", 80000, "D", "FAQ Q30/35")
WAN_CELL_HLD = inp("wan_cell_primary_mbps_hld", 20, "A", "HLD §20.4")
WAN_CELL = inp("wan_cell_primary_mbps", 50, "D/A", "this design; GSWAN-class link, rate ASSUMED")
VIEW_CAP_CELL = inp("remote_view_budget_mbps_per_cell", 30, "D", "admission-controlled; beyond it tiles fall to 1 Hz stills")
WAN_STATE = inp("state_ingress_mbps", 2000, "D/A", "2 x 1 Gbps, different carriers")
KAFKA_BROKER_MBPS = inp("kafka_broker_ingress_MBps", 50, "A", "conservative community-benchmark class, NVMe, RF=3 counted separately")
KAFKA_BROKERS = inp("kafka_brokers", 6, "D", "state DC")
KAFKA_RF = inp("kafka_rf", 3, "D", "")
NATS_MSGPS = inp("jetstream_msgs_per_s_per_cell", 50000, "A", "conservative vendor-benchmark class for R3 file-backed streams")
PLATE_SHARDS = inp("plate_index_shards", 4, "D", "hash(folded plate), PostgreSQL primaries")
B_SUB = inp("substream_mbps_pessimistic", 1.0, "A", "ONVIF sub-stream; measured government main streams 0.26-0.66 Mbps each (bandwidth.json cameras[])")
B_MAIN = inp("main_stream_mbps", 2.0, "A", "HLD §1 / SCALE_MODEL.md")
CELL_LAN_GBPS = inp("cell_ingest_lan_gbps", 50, "D/A", "2 x 25 GbE")
RGW_PUT_PS = inp("object_put_per_s_per_gateway", 1000, "A", "S3-compatible gateway, small objects, vendor-documentation class")
RGW_GW = inp("object_gateways_state", 4, "D", "")
WATCHLIST_W = inp("watchlist_entries", 1_000_000, "A", "pessimistic statewide list size")
ALERT_MATCH_FRAC = inp("alert_storm_match_fraction", 0.05, "A", "5% of plate reads match (e.g. a bad bulk list import)")
USERS = inp("concurrent_users", 5000, "A", "officers statewide")
USER_RPS = inp("requests_per_user_s", 1.0, "A", "peak")
API_P50_MS = inp("api_point_query_ms", PLATE_SEARCH_MS, "M",
                 "var/reports/store_engines.json PostgreSQL plate search p50, used as the per-request cost")
T_OUT_H = inp("outage_hours", 24, "D", "catch-up scenario")

# ---------------------------------------------------------------- helpers
H = lambda x: round(x, 2)


def obs_rate(n, per_h):
    return n * per_h / 3600.0


def fps_demand(n):
    return n * ((1 - ANPR_FRAC) * F_BASE + ANPR_FRAC * F_ANPR)


def per_cell(n_a):
    return min(CELL_MAX, n_a / N_CELLS if n_a >= N_CELLS * CELL_MAX else CELL_MAX * n_a / C)


R = {}

# ---------------------------------------------------------------- §10 compute
for case, n in (("pess_all_80k", C),):
    fps = fps_demand(n)
    gpus = math.ceil(fps / GPU_FPS)
    R["compute"] = {
        "fps_demand": H(fps),
        "gpu_fps_each": H(GPU_FPS),
        "gpus_planning": gpus,
        "gpus_with_spares": gpus + 2 * N_CELLS,
        "servers_4gpu": math.ceil((gpus + 2 * N_CELLS) / 4),
        "gpus_hld_1hz": math.ceil(C * F_BASE / GPU_FPS),
        "decode_cores": H(C * DECODE_CORES),
        "decode_servers_64c": math.ceil(C * DECODE_CORES / 64),
        "ram_tb": H(C * RSS_MB / 1e6),
        "per_cell_gpus": math.ceil(CELL_MAX * ((1 - ANPR_FRAC) * F_BASE + ANPR_FRAC * F_ANPR) / GPU_FPS) + 2,
        "per_cell_gpus_1hz": math.ceil(CELL_MAX * F_BASE / GPU_FPS) + 2,
    }

# ---------------------------------------------------------------- §11 per-resource rows
rows = []


def row(resource, demand, capacity, unit, formula, choice):
    rows.append({"resource": resource, "demand": H(demand), "capacity": H(capacity), "unit": unit,
                 "headroom": H(capacity / demand) if demand else None, "formula": formula,
                 "design_choice": choice})


cell_obs_p = obs_rate(CELL_MAX, R_PESS_H)
cell_obs_m = obs_rate(CELL_MAX, R_MEAN_H)
state_obs_p = obs_rate(C, R_PESS_H)
state_obs_m = obs_rate(C, R_MEAN_H)
plates_state_p = obs_rate(C * ANPR_FRAC, R_PESS_H) * PLATE_FRAC
plates_cell_p = obs_rate(CELL_MAX * ANPR_FRAC, R_PESS_H) * PLATE_FRAC
health_cell = CELL_MAX / HEALTH_PERIOD_S
health_state = C / HEALTH_PERIOD_S

meta_cell_mbps_z = cell_obs_p * OBS_Z_B * 8 / 1e6
meta_cell_mbps_raw = cell_obs_p * OBS_WIRE_B * 8 / 1e6
rt_cell_mbps = (plates_cell_p * PLATE_ROW_B + health_cell * HEALTH_B) * 8 / 1e6
cell_wan_demand = meta_cell_mbps_z + rt_cell_mbps
R["wan_cell"] = {"bulk_compressed_mbps": H(meta_cell_mbps_z), "bulk_raw_mbps": H(meta_cell_mbps_raw),
                 "realtime_mbps": H(rt_cell_mbps), "total_mbps": H(cell_wan_demand),
                 "mean_rate_total_mbps": H(cell_obs_m * OBS_Z_B * 8 / 1e6 + rt_cell_mbps)}

row("Cell WAN uplink (metadata, compressed), 2,500-camera cell", cell_wan_demand,
    WAN_CELL - VIEW_CAP_CELL, "Mbps",
    "2,500 x 3,000/h x 154.2 B x 8 + plates 2,500x0.2x3,000/3600x0.5x160 B x8 + health 250/s x 500 B x8; capacity = 50 Mbps minus 30 Mbps viewing budget",
    "batch-compressed metadata lane; viewing budget admission-controlled; video never on WAN")
row("Cell WAN uplink, same demand, HLD 20 Mbps link, no viewing", cell_wan_demand, WAN_CELL_HLD, "Mbps",
    "as above against HLD §20.4 primary link", "HLD link is enough for compressed metadata alone")
row("Cell WAN uplink, raw (uncompressed) metadata, HLD 20 Mbps link", meta_cell_mbps_raw + rt_cell_mbps, WAN_CELL_HLD, "Mbps",
    "2,500 x 3,000/h x 1,331.7 B x 8 + real-time lanes", "WOULD BIND (<1x): compression is mandatory, not an optimisation")

hot_d_obs = obs_rate(5000, R_PESS_H)
hot_d_mbps = hot_d_obs * OBS_Z_B * 8 / 1e6 + 2 * rt_cell_mbps
row("District uplink, 5,000-camera district (2 cells, one 100 Mbps link, 60 Mbps viewing budget)", hot_d_mbps, 100 - 60, "Mbps",
    "5,000 x 3,000/h x 154.2 B x 8 + 2 x real-time lanes", "cell split at 2,500; link scaled per cell")

backlog_bytes = hot_d_obs * T_OUT_H * 3600 * OBS_Z_B
drain_s = backlog_bytes * 8 / ((100 - hot_d_mbps) * 1e6)
R["catchup_hot_district"] = {"backlog_GB": H(backlog_bytes / 1e9), "drain_h_100mbps_viewing_paused": H(drain_s / 3600),
                             "drain_h_40mbps_spare": H(backlog_bytes * 8 / ((40 - hot_d_mbps) * 1e6) / 3600),
                             "queue_disk_7d_GB_raw": H(hot_d_obs * 7 * 86400 * OBS_WIRE_B / 1e9)}
row("Catch-up after 24 h WAN outage, 5,000-camera district: drain time vs outage", drain_s / 3600, T_OUT_H, "hours",
    "backlog = rate x 24 h x 154.2 B; drain = backlog / (100 Mbps - live rate), viewing paused during catch-up",
    "priority lanes: alerts, plates, health first; bulk last; dedup_key makes replay idempotent")

site_rule = 1.5
row("Site uplink (camera site -> cell), by design rule", 1.0, site_rule, "x (ratio)",
    "pull to cell only if n_site x 1.0 Mbps x 1.5 <= site uplink; otherwise an edge box analyses on site",
    "placement rule converts any would-be link bottleneck into edge compute")
row("Cell ingest LAN (sub-streams of 2,500 analysed cameras)", CELL_MAX * B_SUB / 1000, CELL_LAN_GBPS, "Gbps",
    "2,500 x 1.0 Mbps", "sub-stream for T0/T1, main-stream bursts only for T2 crops")

row("Cell event bus (NATS JetStream R3)", cell_obs_p + plates_cell_p + health_cell, NATS_MSGPS, "msg/s",
    "2,083 obs/s + 208 plates/s + 250 health/s", "one JetStream cluster per cell; subjects obs.<cell>.<camera>")
state_bus_MBps = (plates_state_p * PLATE_ROW_B + health_state * HEALTH_B + plates_state_p * ALERT_MATCH_FRAC * 2000) / 1e6
kafka_cap = KAFKA_BROKERS * KAFKA_BROKER_MBPS / KAFKA_RF
row("State event bus (Kafka), real-time lanes only", state_bus_MBps, kafka_cap, "MB/s",
    "plates 6,667/s x 160 B + health 8,000/s x 500 B + alert storm 333/s x 2 KB; capacity = 6 x 50 / RF 3",
    "bulk observations bypass Kafka as compressed micro-batches to object storage")
state_bus_raw_all = state_obs_p * OBS_WIRE_B / 1e6
row("State event bus IF all observations went through it raw", state_bus_raw_all, kafka_cap, "MB/s",
    "66,667 obs/s x 1,331.7 B", "rejected alternative: 1.1x headroom is not a design")
row("State bus partitions: plate topic", plates_state_p / 128, 5000, "msg/s per partition",
    "6,667 plates/s / 128 partitions; capacity ASSUMED 5,000 msg/s per partition", "key = OCR-folded plate")

row("Cell DB write rate (PostgreSQL primary)", cell_obs_p, PG_WRITE_RPS, "rows/s",
    "2,500 x 3,000/h; capacity = measured single-stream copy 14,187 rows/s", "batched COPY per 1 s; partitioned by day")
row("State plate-index write rate (4 hash shards)", plates_state_p, PLATE_SHARDS * PG_WRITE_RPS, "rows/s",
    "80,000 x 0.2 x 3,000/h x 0.5", "shard by folded plate = same key as Kafka partition")
catch_rows = plates_state_p * T_OUT_H * 3600
row("State plate-index catch-up after 24 h state outage: drain hours", catch_rows / (PLATE_SHARDS * PG_WRITE_RPS - plates_state_p) / 3600,
    T_OUT_H, "hours", "576 M rows / (56,748 - 6,667) rows/s", "cells keep working meanwhile")

cell_hot_TB_p = cell_obs_p * 30 * 86400 * PG_ROW_B / 1e12
cell_hot_TB_m = cell_obs_m * 30 * 86400 * PG_ROW_B / 1e12
row("Cell hot store, 30 days (NVMe per copy)", cell_hot_TB_p, 32, "TB",
    "2,083 obs/s x 30 d x 2,663 B; capacity 32 TB NVMe per copy", "time-partitioned; detach to lake after 30 d")
lake_TB_yr_p = state_obs_p * 365 * 86400 * OBS_Z_B / 1e12
lake_TB_yr_m = state_obs_m * 365 * 86400 * OBS_Z_B / 1e12
plate_TB_yr = plates_state_p * 365 * 86400 * PLATE_ROW_B * 2 / 1e12
R["storage"] = {"cell_hot_TB_pess": H(cell_hot_TB_p), "cell_hot_TB_mean": H(cell_hot_TB_m),
                "cell_hot_TB_pess_sqlite_basis": H(cell_obs_p * 30 * 86400 * OBS_DISK_SQLITE_B / 1e12),
                "lake_TB_per_year_pess": H(lake_TB_yr_p), "lake_TB_per_year_mean": H(lake_TB_yr_m),
                "plate_index_TB_per_year_pess": H(plate_TB_yr),
                "hld_hot_TB_per_district": 1.2}
row("State object store, 3 years of compressed observations", 3 * lake_TB_yr_p, 1500, "TB",
    "66,667 obs/s x 3 y x 154.2 B; capacity 1.5 PB usable (erasure-coded)", "grows per year retained, not per camera-second")

puts = N_CELLS / 60 + plates_state_p * ALERT_MATCH_FRAC
row("Object store request rate (micro-batches + alert-storm evidence stills)", puts, RGW_PUT_PS * RGW_GW, "PUT/s",
    "40 cells x 1 batch/min + 333 stills/s", "micro-batches of >=1 minute keep object count low")

VIEWED_CELL = inp("cameras_viewed_concurrently_per_cell", 200, "A", "2 district walls x 64 tiles + 72 remote tiles")
GW_SESS = inp("gateway_copy_sessions_per_node", 150, "A", "copy-remux WHEP sessions per gateway node; not measured (15 transcoded bridges measured on the M5, phase16_bridge_scale.json)")
row("Media gateway sessions per cell (cameras being viewed)", VIEWED_CELL, 3 * GW_SESS, "sessions",
    "200 viewed cameras; capacity 3 gateway nodes x 150 copy sessions (ASSUMED)",
    "one upstream session per camera shared by AI and all viewers (live/hub.py:1-12); gateway sessions set by viewers, not by analysed cameras")
row("Remote viewing (state + investigators)", 1000 * 0.5 + 100 * 1.5, WAN_STATE, "Mbps",
    "1,000 preview tiles x 0.5 Mbps + 100 full tiles x 1.5 Mbps (bitrates: phase16_bridge_profile.json settings)",
    "independent of analysed cameras; set by people watching")
row("TURN relay (remote/mobile only)", 200 * 0.5, 2 * 6 * 1000 * 0.5, "Mbps",
    "200 relayed tiles x 0.5 Mbps; capacity 6 regions x 2 coturn x 0.5 Gbps usable", "police LAN clients connect direct")

api_rps = USERS * USER_RPS
worker_rps = 1000 / API_P50_MS
row("API request rate (all users at the state API, pessimistic)", api_rps, 128 * worker_rps, "req/s",
    "5,000 users x 1 req/s; capacity 8 servers x 16 workers x (1000/10.38 ms)", "stateless; district users served by their cell API; heavy aggregates served from rollups")
rows.append({"resource": "Search: plate lookup fan-out", "demand": 1, "capacity": None, "unit": "shard per query",
             "headroom": None, "formula": "plate -> one hash shard; no scatter", "design_choice": "key choice removes fan-out"})
row("Search: attribute search scatter-gather", N_CELLS, 8 * N_CELLS, "cell queries in flight",
    "one query hits 40 cells; each cell admits 8 concurrent searches (api/deps.py:100)", "bounded by time window and 2,000-row cap")
row("Spatial viewport query (PostGIS, 80k cameras)", GIS_VIEWPORT_MS, 100, "ms p50 vs 100 ms SLO",
    "measured 1.3 ms at 80,000 cameras", "camera count is fixed by the estate, not by analysis")
wl_bytes = WATCHLIST_W * 16
row("Watchlist bootstrap of one cell + its 25 edge boxes, seconds over 20 Mbps", 26 * wl_bytes * 8 / 20e6, 3600, "s vs 1 h target",
    "1,000,000 entries x 16 B (two 8-byte keyed hashes) x 26 nodes / 20 Mbps; deltas thereafter ~320 KB/day",
    "hashed, delta-versioned bundles; O(1) match per read regardless of list size")
row("Alert storm: alert rows written at the state", plates_state_p * ALERT_MATCH_FRAC, PG_WRITE_RPS, "rows/s",
    "6,667 plates/s x 5% match", "incident grouping (watchlist/incidents.py) and per-district notification token buckets; the human queue is rate-limited on purpose")
row("Busy highway camera: metadata off its site", HOT_CAM_PEAK_MIN / 60 * OBS_WIRE_B * 8 / 1000, 1000, "kbps vs 1 Mbps",
    "491 obs/min x 1,331.7 B x 8 / 60", "compute for this camera scales (5 fps ANPR); its metadata does not matter")
row("Health telemetry (metrics series at state)", 1000 * N_CELLS * 20 / 1e6, 10, "M active series",
    "per-camera series stay in cell Prometheus; state keeps ~1,000 series x 20 per cell", "cell Prometheus + Thanos, downsampled")
row("Control plane: nodes per cell cluster", 50, 5000, "nodes", "~21 GPU + 10 decode + 10 other + edge boxes on their own fleet", "one cluster per cell; no statewide cluster")
row("Image/model rollout per cell (25 edge boxes x 2 GB) over 20 Mbps spare", 25 * 2 * 8e9 / 20e6 / 3600, 72, "hours per ring",
    "25 x 2 GB x 8 / 20 Mbps", "regional OCI mirror; staged rings over >= 3 days")

# What drives each row's demand, and what kind of limit it is. "cameras" rows
# grow with the number of analysed cameras; "viewers" and "users" rows grow with
# people; "estate" rows with registered (not analysed) cameras; "list" with the
# watchlist; "fixed" with neither. An "alternative" row is a rejected design
# kept to show why it was rejected.
ROW_CLASS = {
    "Cell WAN uplink (metadata, compressed)": ("cameras", "throughput", False),
    "Cell WAN uplink, same demand, HLD": ("cameras", "throughput", False),
    "Cell WAN uplink, raw (uncompressed)": ("cameras", "throughput", True),
    "District uplink, 5,000-camera district": ("cameras", "throughput", False),
    "Catch-up after 24 h WAN outage": ("cameras", "recovery time", False),
    "Site uplink": ("cameras", "placement rule", False),
    "Cell ingest LAN": ("cameras", "throughput", False),
    "Cell event bus": ("cameras", "throughput", False),
    "State event bus (Kafka), real-time lanes only": ("cameras", "throughput", False),
    "State event bus IF all observations": ("cameras", "throughput", True),
    "State bus partitions": ("cameras", "throughput", False),
    "Cell DB write rate": ("cameras", "throughput", False),
    "State plate-index write rate": ("cameras", "throughput", False),
    "State plate-index catch-up": ("cameras", "recovery time", False),
    "Cell hot store": ("cameras", "storage", False),
    "State object store, 3 years": ("cameras", "storage", False),
    "Object store request rate": ("cameras", "throughput", False),
    "Media gateway sessions": ("viewers", "throughput", False),
    "Remote viewing": ("viewers", "throughput", False),
    "TURN relay": ("viewers", "throughput", False),
    "API request rate": ("users", "throughput", False),
    "Search: plate lookup fan-out": ("users", "fan-out", False),
    "Search: attribute search": ("users", "throughput", False),
    "Spatial viewport query": ("estate", "latency", False),
    "Watchlist bootstrap": ("list", "recovery time", False),
    "Alert storm": ("cameras", "throughput", False),
    "Busy highway camera": ("cameras", "throughput", False),
    "Health telemetry": ("cameras", "throughput", False),
    "Control plane": ("cameras", "throughput", False),
    "Image/model rollout": ("fixed", "recovery time", False),
}
for r in rows:
    match = [v for k, v in ROW_CLASS.items() if r["resource"].startswith(k)]
    assert len(match) == 1, r["resource"]
    r["driver"], r["kind"], r["alternative"] = match[0]

R["rows"] = rows
R["inputs"] = I
R["rates"] = {"cell_obs_per_s_pess": H(cell_obs_p), "cell_obs_per_s_mean": H(cell_obs_m),
              "state_obs_per_s_pess": H(state_obs_p), "state_obs_per_s_mean": H(state_obs_m),
              "state_plates_per_s_pess": H(plates_state_p), "window_hours": H(WINDOW_H),
              "hot_camera_peak_obs_per_s": H(HOT_CAM_PEAK_MIN / 60),
              "hot_camera_peak_kbps_raw": H(HOT_CAM_PEAK_MIN / 60 * OBS_WIRE_B * 8 / 1000),
              "state_metadata_mbps_raw_pess": H(state_obs_p * OBS_WIRE_B * 8 / 1e6),
              "state_metadata_mbps_z_pess": H(state_obs_p * OBS_Z_B * 8 / 1e6),
              "central_video_gbps_2mbps": H(C * B_MAIN / 1000)}


# ---------------------------------------------------------------- growth sweep
def sweep(frac):
    n = C * frac
    fps = fps_demand(n)
    return {"analysed": int(n), "gpus": math.ceil(fps / GPU_FPS) + 2 * N_CELLS,
            "avg_cell_wan_mbps": H(obs_rate(n / N_CELLS, R_PESS_H) * OBS_Z_B * 8 / 1e6 + rt_cell_mbps * (n / N_CELLS) / CELL_MAX),
            "state_bus_MBps": H(state_bus_MBps * frac + 0.0),
            "cell_db_rows_s": H(obs_rate(n / N_CELLS, R_PESS_H)),
            "lake_TB_yr": H(lake_TB_yr_p * frac)}


R["sweep"] = [sweep(f) for f in (0.1, 0.25, 0.5, 1.0)]


# ---------------------------------------------------------------- §14 cost (HLD §20.8 rates, lakh)
def rng(q, lo, hi):
    return (q * lo, q * hi)


# What is bought, as a function of the number of analysed cameras. Compute is
# sized to demand; everything else is provisioned per cell, region and state at
# the planning design and does not change with how many cameras are analysed.
COMPUTE_ITEMS = ("inference_servers", "decode_servers", "edge_boxes", "compute_ram_TB")
UNIT_RATES_LAKH = {  # HLD §20.8, ASSUMED
    "inference_servers": (30, 70), "decode_servers": (8, 15), "edge_boxes": (1.5, 4),
    "compute_ram_TB": (0, 0),  # inside the compute servers' price
    "cell_db_servers": (15, 30), "cell_app_bus_servers": (8, 15), "cell_hot_nvme_TB": (0.5, 1.5),
    "cell_network_set": (15, 35), "cell_rack": (10, 20), "region_sfu_turn_servers": (8, 15),
    "region_backup_object_TB": (0.1, 0.3), "state_kafka_servers": (8, 15), "state_db_servers": (25, 50),
    "state_app_trino_monitoring": (8, 15), "state_object_store_TB": (0.1, 0.3), "state_nvme_TB": (0.5, 1.5),
    "evidence_worm_TB": (0.1, 0.3),
}


def provision(n_analysed, anpr=True):
    fps = fps_demand(n_analysed) if anpr else n_analysed * F_BASE
    gpus = math.ceil(fps / GPU_FPS) + 2 * N_CELLS
    return {
        "inference_servers": math.ceil(gpus / 4),
        "decode_servers": math.ceil(n_analysed * DECODE_CORES / 64),
        "edge_boxes": math.ceil(25 * N_CELLS * n_analysed / C),
        "compute_ram_TB": H(n_analysed * RSS_MB / 1e6),
        "cell_db_servers": 2 * N_CELLS,
        "cell_app_bus_servers": 3 * N_CELLS,
        "cell_hot_nvme_TB": 2 * 32 * N_CELLS,
        "cell_network_set": N_CELLS,
        "cell_rack": N_CELLS,
        "region_sfu_turn_servers": 6 * 3,
        "region_backup_object_TB": 6 * 200,
        "state_kafka_servers": KAFKA_BROKERS + 3,
        "state_db_servers": 2 * PLATE_SHARDS + 2 + PLATE_SHARDS,
        "state_app_trino_monitoring": 6 + 4 + 3,
        "state_object_store_TB": 1500 + 1500,
        "state_nvme_TB": 120,
        "evidence_worm_TB": 100,
    }


def cost(items):
    cp = {k: rng(q, *UNIT_RATES_LAKH[k]) for k, q in items.items() if k in COMPUTE_ITEMS}
    nc = {k: rng(q, *UNIT_RATES_LAKH[k]) for k, q in items.items() if k not in COMPUTE_ITEMS}
    c_lo = sum(v[0] for v in cp.values()); c_hi = sum(v[1] for v in cp.values())
    n_lo = sum(v[0] for v in nc.values()); n_hi = sum(v[1] for v in nc.values())
    return {"compute_lakh": (H(c_lo), H(c_hi)), "noncompute_lakh": (H(n_lo), H(n_hi)),
            "compute_share": (H(c_lo / (c_lo + n_lo)), H(c_hi / (c_hi + n_hi))),
            "total_crore": (H((c_lo + n_lo) / 100), H((c_hi + n_hi) / 100)), "items": {**cp, **nc}}


R["provision"] = {str(int(C * f)): provision(C * f) for f in (0.1, 0.25, 0.5, 1.0)}
R["cost_planning"] = cost(provision(C))
R["cost_hld_1hz"] = cost(provision(C, anpr=False))
wan_opex = rng(N_CELLS * 70 * 12, 700 / 1e5, 2000 / 1e5)
R["wan_opex_lakh_per_year"] = (H(wan_opex[0] + 2000 * 12 * 300 / 1e5), H(wan_opex[1] + 2000 * 12 * 800 / 1e5))


# ---------------------------------------------------------------- Step 4: hostile recomputation
def hostile():
    out = {}
    z4 = OBS_WIRE_B / 4
    out["a_compression_only_4x"] = {"cell_wan_mbps": H(cell_obs_p * z4 * 8 / 1e6 + rt_cell_mbps),
                                    "headroom_vs_20": H(20 / (cell_obs_p * z4 * 8 / 1e6 + rt_cell_mbps))}
    hw = obs_rate(CELL_MAX, HOT_CAM_PEAK_H)  # every camera in a cell at cam04's peak hour
    out["b_all_highway_cell_at_peak_hour"] = {
        "obs_per_s": H(hw),
        "db_headroom_measured": H(PG_WRITE_RPS / hw),
        "db_headroom_half_measured": H(PG_WRITE_RPS / 2 / hw),
        "wan_mbps": H(hw * OBS_Z_B * 8 / 1e6 + rt_cell_mbps),
        "wan_headroom_vs_20": H(20 / (hw * OBS_Z_B * 8 / 1e6 + rt_cell_mbps)),
        "hot_30d_TB_2x_wire": H(hw * 30 * 86400 * PG_ROW_B / 1e12),
        "hot_30d_TB_sqlite_basis": H(hw * 30 * 86400 * OBS_DISK_SQLITE_B / 1e12),
        "cameras_per_cell_if_capped_at_4000_obs_s": int(CELL_OBS_CAP / (HOT_CAM_PEAK_H / 3600)),
        "at_cap_db_headroom_half_measured": H(PG_WRITE_RPS / 2 / CELL_OBS_CAP),
        "at_cap_wan_headroom_vs_20": H(20 / (CELL_OBS_CAP * OBS_Z_B * 8 / 1e6 + rt_cell_mbps)),
        "at_cap_hot_30d_headroom_2x_wire": H(32 / (CELL_OBS_CAP * 30 * 86400 * PG_ROW_B / 1e12)),
        "at_cap_hot_30d_headroom_sqlite_basis": H(32 / (CELL_OBS_CAP * 30 * 86400 * OBS_DISK_SQLITE_B / 1e12))}
    out["c_kafka_10MBps_per_broker"] = {"headroom": H(KAFKA_BROKERS * 10 / KAFKA_RF / state_bus_MBps)}
    out["d_pg_half_of_measured"] = {"cell_headroom": H(PG_WRITE_RPS / 2 / cell_obs_p)}
    pl = obs_rate(C * 0.5, R_PESS_H) * 1.0
    bus = (pl * PLATE_ROW_B + health_state * HEALTH_B + pl * ALERT_MATCH_FRAC * 2000) / 1e6
    out["e_half_estate_anpr_every_obs_plated"] = {
        "plates_per_s": H(pl), "shards4_headroom": H(4 * PG_WRITE_RPS / pl), "shards8_headroom": H(8 * PG_WRITE_RPS / pl),
        "kafka_MBps": H(bus), "kafka_headroom": H(kafka_cap / bus),
        "plate_index_hot_90d_TB": H(pl * 90 * 86400 * PLATE_ROW_B * 2 / 1e12),
        "gpus_if_those_cameras_run_5fps": math.ceil((C * 0.5 * F_BASE + C * 0.5 * F_ANPR) / GPU_FPS)}
    out["f_api_10k_users_2rps"] = {"headroom_128_workers": H(128 * worker_rps / 20000),
                                   "workers_for_2x": math.ceil(2 * 20000 / worker_rps)}
    out["g_5000_remote_preview_tiles"] = {"mbps": 5000 * 0.5, "headroom_vs_2000": H(2000 / 2500),
                                          "thumb_1hz_15KB_mbps": H(5000 * 15e3 * 8 / 1e6)}
    out["h_state_outage_72h_plate_catchup_h"] = H(plates_state_p * 72 * 3600 / (PLATE_SHARDS * PG_WRITE_RPS - plates_state_p) / 3600)
    out["i_wan_outage_7d_cell_queue_GB_compressed"] = H(cell_obs_p * 7 * 86400 * OBS_Z_B / 1e9)
    return out


R["hostile"] = hostile()


def main() -> None:
    OUT.write_text(json.dumps(R, indent=1, default=list) + "\n")
    print(json.dumps({k: v for k, v in R.items() if k not in ("inputs", "rows", "hostile")},
                     indent=1, default=list))
    print("\nrows:")
    for r in rows:
        print(f"  {r['headroom']!s:>8}x  {r['resource']}: {r['demand']} / {r['capacity']} {r['unit']}")
    print("\nhostile:")
    print(json.dumps(R["hostile"], indent=1))
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
