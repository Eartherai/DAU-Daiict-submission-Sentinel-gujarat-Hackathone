# Golden cam01 end-to-end certification

Timestamp UTC: `2026-09-16T03:49:55.093533+00:00`

Overall: **AMBER** (PASS=10, AMBER=1, FAIL=0)

| Stage | Status | Detail |
|---|---|---|
| credentials_env | **PASS** | SENTINEL_GRID_* present |
| cam01_whep_browser | **PASS** | status=MEASURED summary={'first_frame_ms': 1866.5, 'negotiation_ms': 143.19999999925494, 'currentTime': 15.2, 'resolution': '1920x1080', 'canvasMeanLuma': 97.88 |
| overlay_raf | **PASS** | live overlay canvas/rAF present in ui/app.js |
| path_selector | **PASS** | StreamPathSelector module present |
| watchlist_module | **PASS** | watchlist package present |
| evidence_module | **PASS** | evidence package present |
| follow_vehicle_api | **PASS** | follow-vehicle route present |
| gis_module | **PASS** | gis package present |
| demo_cam01_config | **PASS** | config/demo_cam01.yaml present |
| secret_scan | **PASS** | SECRET SCAN: PASS (0 tracked files + full history) |
| api_health | **AMBER** | API not reachable at http://127.0.0.1:8080 (code=0); static stages still valid |

## Command

```bash
python tools/gov_cam01_golden_e2e.py
```

Artifact: `var/reports/phase8c/gov/cam01_golden_e2e.json`

