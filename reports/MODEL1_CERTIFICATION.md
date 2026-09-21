# Model 1 certification — registry + GIS

Generated 2026-09-16T22:37:54.371769+00:00 UTC.

**Strongest measured result:** 80,000 synthetic registry records; lookup P50 0.044 ms / P95 0.0551 ms; insert 0.6686 s

**Bottleneck:** full unclustered browser markers. Practical path is SQL lookup + GIS clustering.

**Exact measured limit:** 80,000 synthetic SQLite records in-process. Not 80,000 live streams.

## TEST A — registry scale

Each lookup/search/filter/page cell is P50/P95 over 19 samples after 2 warmups.

| n | insert_s | lookup P50/P95 ms | search P50/P95 ms | filter P50/P95 ms | page50 P50/P95 ms | db_bytes | index_bytes | peak_rss_mb |
|---|---|---|---|---|---|---|---|---|
| 1000 | 0.0079 | 0.049/0.0927 | 0.1254/0.1792 | 0.0577/0.0635 | 0.1567/0.1616 | 659456 | 327680 | 64.3 |
| 10000 | 0.0776 | 0.0432/0.0495 | 0.1447/0.1516 | 0.4043/0.4335 | 0.1548/0.1796 | 3878912 | 1490944 | 75.4 |
| 50000 | 0.3928 | 0.0427/0.0528 | 0.1476/0.2133 | 2.1087/2.3366 | 0.1555/0.1888 | 18763776 | 6811648 | 108.7 |
| 80000 | 0.6686 | 0.044/0.0551 | 0.149/0.2314 | 3.3905/3.4951 | 0.1499/0.1573 | 30076928 | 10895360 | 131.2 |

JSON: `var/reports/final/model1/registry_*.json`

## TEST B — GIS (50 evaluation cameras)

| Field | Value |
|---|---|
| layer_ms | 0.983 |
| registry_total | 50 |
| unlocated | 0 |
| domains | `{"GOVERNMENT": {"ms": 0.919, "registry_total": 30}, "OWN_FEED": {"ms": 0.906, "registry_total": 2}, "SYNTHETIC_CONTROL": {"ms": 1.119, "registry_total": 18}}` |
| label | MEASURED_SYNTHETIC 50-camera evaluation store |


## TEST C — 80k logical scale

| Field | Value |
|---|---|
| registry_n | 80000 |
| cluster_zoom6_ms | 38.848 |
| cluster_groups | 18 |
| map_layer_ms | 217.54 |
| map_filter_search_ms | 208.858 |
| filter_returned | 22 |
| max_features | 1500 |
| returned_features | 6 |
| strategy | server-side clustering + max_features cap; 80k markers not sent to browser |
| label | MEASURED_SYNTHETIC |


Initial load strategy: viewport + clustering. 80k markers are **not** sent to the browser.
