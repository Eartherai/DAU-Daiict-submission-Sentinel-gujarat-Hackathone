# 80k scale certification

Architecture claim: centralized analytics and command orchestration with regional media/AI pools for statewide deployment.

**Not claimed:** 80,000 cameras centrally decoded, recorded, or inferred.

| Layer | What was measured | Label |
|---|---|---|
| Model 1 registry | 80k synthetic SQLite insert + P50/P95 lookup | MEASURED_SYNTHETIC |
| Model 1 GIS | cluster + max_features cap; returned 6 | MEASURED_SYNTHETIC |
| Model 2 video | 15 government browser tiles at 60s (prior 19 at 120s) | MEASURED_REAL |
| Model 3 federation | 50 mock adapters + in-process bus | MEASURED_SYNTHETIC / MEASURED_IN_PROCESS |
| Model 4 AI | regional AI DESIGNED; own-file decode MEASURED_OWN_FEED | DESIGNED at 80k |

50-camera logical test: {'government': 30, 'own_feed': 2, 'synthetic_control': 18, 'onboarded': 50}
