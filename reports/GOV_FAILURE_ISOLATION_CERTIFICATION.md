# Government camera failure isolation

Timestamp UTC: `2026-09-16T03:57:37.799214+00:00`

Victim: **cam05** · Peers: cam01, cam02

Overall: **PASS** (PASS=6, AMBER=0, FAIL=0)

| Stage | Status | Detail |
|---|---|---|
| baseline_ready | **PASS** | `{"pending": [], "before": {"cam01": {"ready": true, "bytes": 100019, "online": true}, "cam02": {"ready": true, "bytes": 120257, "online": true}, "cam05": {"ready": true, "bytes": 1` |
| victim_killed | **PASS** | `{"victim": "cam05", "after_kill": {"cam01": {"ready": true, "bytes": 180445, "online": true}, "cam02": {"ready": true, "bytes": 307616, "online": true}, "cam05": {"ready": false, "` |
| peers_continue | **PASS** | `{"peers": ["cam01", "cam02"], "after_wait": {"cam01": {"ready": true, "bytes": 354636, "online": true}, "cam02": {"ready": true, "bytes": 626049, "online": true}}}` |
| process_alive | **PASS** | `{"mediamtx_exit": null, "peer_exits": {"cam01": null, "cam02": null}}` |
| no_credential_argv | **PASS** | `"peer publisher argv inspected; credentials must not appear"` |
| no_stale_live_claim | **PASS** | `"victim not ready or bytes stopped advancing"` |

Artifact: `var/reports/phase8c/gov/failure_isolation.json`

