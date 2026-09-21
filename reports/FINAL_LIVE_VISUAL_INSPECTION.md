# Visual inspection notes (this pass)

Screenshots: `reports/final_live_qa/ui/`. JSON: `reports/final_live_qa/ui/visual_qa.json`.

| File | What the pixels actually show |
|---|---|
| A_LOGIN.png | Gujarat Police login. Bearer field placeholder only. |
| OPERATIONS.png | 51 onboarded · 1 unacked alert GJ01TA0001 · grades UNKNOWN honest |
| 12-camera_wall.png | GOVERNMENT MODE · Grid · **12 of 12 showing a frame** · real CSITMS timestamps · mix STILL/LIVE |
| 16/25/30-camera_wall.png | Grid tiles exist; after cycling sizes Sentinel 502; do not read as 30 LIVE |
| 50-camera_logical_wall.png | cam01–10 GOVERNMENT; later tiles empty CONTROL/not captured |
| GIS.png | Google map of western India · registry strip with cam stills · 51 on map |
| TRACKING.png | GJ01TA0001 · FIRST SEEN OWN-TRAFFIC · LIKELY 0.73 · REQUIRES VERIFICATION |
| SYSTEM.png | System DEGRADED (honest) · hybrid architecture copy · ranks below fold |
| CAMERA_HEALTH.png | Capability table · UNKNOWN · CTL-* then cam01 |
| INTELLIGENCE.png | Ahmedabad Google Map only in viewport (overlay covers Model-4 chrome) |
| WATCHLIST / ALERT_DETAIL | OPEN stolen_vehicle OWN-TRAFFIC 0.83 |

Console: Maps `loading=async` warning (expected); 502/503 during wall cycling (upstream busy); map canvas 1×1 then recover. No Maps key in artifacts.
