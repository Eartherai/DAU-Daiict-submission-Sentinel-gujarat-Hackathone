# Final visual acceptance

Reviewer questions applied to captured product screens. Not declared perfect.

| SCREEN | CHECK | RESULT | ARTIFACT |
|---|---|---|---|
| LOGIN | Professional command-center gate, task obvious, Gujarati + English | **PASS** | `var/reports/final/ui/A_LOGIN.png` |
| OPERATIONS | 50 onboarded, KPI source note, AI DEGRADED / OCR DEGRADED chips | **AMBER** — handling strip wrapped `final_qa.db` / LIVE CAPTURE; purpose field cramped | `var/reports/final/ui/OPERATIONS.png` |
| 12-camera wall | LIVE vs PREVIEW, domain | **AMBER** — demo-store stills; live grid sparse in 1440×900 capture | `var/reports/final/ui/12-camera_wall.png` |
| 16-camera wall | Same | **AMBER** | `var/reports/final/ui/16-camera_wall.png` |
| 25-camera wall | Same | **AMBER** | `var/reports/final/ui/25-camera_wall.png` |
| 30-camera wall | Same | **AMBER** | `var/reports/final/ui/30-camera_wall.png` |
| 50-camera logical | CONTROL vs GOVERNMENT | **AMBER** — composition is 30+2+18 in store; capture did not show CONTROL badges on every tile | `var/reports/final/ui/50-camera_logical_wall.png` |
| INTELLIGENCE | OWN feeds, M4 | **AMBER** — signed-in; hero/KPI block sparse in capture | `var/reports/final/ui/INTELLIGENCE.png` |
| INVESTIGATION | Search / track | **AMBER** | `var/reports/final/ui/INVESTIGATION.png` |
| SYSTEM | Architecture claim | **AMBER** — copy wraps tightly in the left column | `var/reports/final/ui/SYSTEM.png` |
| GIS | Real map, 50 points | **AMBER** — 51 registry cameras listed; canvas empty in this capture (Maps loader 302 when keyed) | `var/reports/final/ui/GIS.png` |
| WATCHLIST / ALERT DETAIL | GJ01TA0001, VIEW VIDEO / TRACK / GIS | **AMBER** — plate/actions clipped before CSS fix | `var/reports/final/ui/ALERT_DETAIL.png` |
| CAMERA HEALTH | Health rows | **AMBER** | `var/reports/final/ui/CAMERA_HEALTH.png` |
| CONNECTED SYSTEMS | DEMO/TEST | **AMBER** — captured on SYSTEM surface | `var/reports/final/ui/CONNECTED_SYSTEMS.png` |

Focused fixes applied after review (not a redesign): Alerts JS syntax, handling-strip wrap, alert-card overflow, live-grid / map / intelligence min-heights, session token reread, Maps key kept off `/config`.

JSON: `var/reports/final/ui/visual_qa.json` (`google_enabled: true`, `google_key_published: false`).
