# Final limitations and external dependencies

Companion to `FINAL_TECHNICAL_EVIDENCE_MASTER.md` and `FINAL_PPT_TECHNICAL_CONTENT.md`.  
Purpose: keep judging language honest. No production-code claims beyond what was measured.

---

## External / access limitations

| Limitation | Label | Implication |
|---|---|---|
| Sentinel catalogue session (`SENTINEL_GRID_COOKIE` / TOKEN) not available in this environment | BLOCKED_BY_EXTERNAL_ACCESS | `/api/ingest` not used; no authentication bypass |
| 30 source identities are documented **probe IDs**, not authoritative catalogue output | NOT_AUTHORITATIVE | Do not present cam01–cam30 as official inventory |
| Intermittent upstream RTSP **401 / connection refuse / DESCRIBE timeout** under large concurrent fan-in | MEASURED_REAL (observed) / BLOCKED_BY_EXTERNAL_ACCESS (session budget) | Bridge readiness on hybrid wall dropped even when local encode scaled to 15 under healthy conditions |
| Government RTSP auth was periodically blocked during earlier phases | BLOCKED_BY_EXTERNAL_ACCESS | Phase 10 recorded 401 periods; live gov re-runs paused then resumed when credentials accepted again |

---

## Measured coverage limits (do not oversell)

| Fact | Value | Label |
|---|---|---|
| Best real hybrid browser-visible wall | **19** (15 direct WHEP + 4 bridged) at 30/60/120s | MEASURED_REAL — Phase 16 |
| Direct WHEP browser decode (census) | **15 / 30** | MEASURED_REAL — Phase 14 |
| RTSP frames (census) | **30 / 30** | MEASURED_REAL — Phase 14 |
| Concurrent bridges when upstream healthy | **15** | MEASURED_REAL — Phase 16 scale |
| Bridges ready on best hybrid soak | **4** | MEASURED_REAL — Phase 16 wall |
| Remaining RTSP-only on that soak | **11** (AI-capable; not NO_SIGNAL) | MEASURED_REAL |
| NO_SIGNAL on hybrid soaks | **0** | MEASURED_REAL |
| Peak simultaneous real PASS tiles (Phase 12 progression) | ≈ **10** | MEASURED_REAL |
| Best all-PASS real direct wall | **n=8** | MEASURED_REAL |

---

## What remains AI-capable but not browser-visible

On the best hybrid soak:

- **11** cameras stayed **RTSP_ONLY_AI**: upstream produced RTSP frames historically (census) / remain intended for AI plane, but no browser WHEP tile on that wall.
- These must **not** be labeled NO_SIGNAL unless both RTSP and WHEP planes fail (Phase 14 classification rule).

---

## Compatibility path limits

| Path | Result | Label |
|---|---|---|
| H.264 B-frame source → **copy** → MediaMTX WebRTC | FAIL | MEASURED_REAL |
| H.264 → **VideoToolbox baseline** → WHEP | PASS | MEASURED_REAL |
| Intent | Compatibility bridge is selective, not a replacement for direct WHEP | DESIGNED + MEASURED_REAL |

---

## Latency figures — do not mix

| Figure | Value | Label | Warning |
|---|---|---|---|
| Bridged PREVIEW warm promote p50 | **35.75 ms** | MEASURED_REAL (Phase 16) | Use this for bridged promote claims |
| Bridged PREVIEW cold promote | **721.7 ms** | MEASURED_REAL (Phase 16) | Cold path |
| Phase 10 synthetic/local prewarm | ~44 ms (337→44) | MEASURED_SYNTHETIC | **Do not** present as real bridged warm |
| Operator cert warm p50 (~28 ms) | Phase 13 operator path | MEASURED_REAL | Different path than Phase 16 bridged prewarm — cite separately |

---

## Architecture vs measurement

| Statement | Allowed label |
|---|---|
| Regional media/AI pools; one upstream session → fan-out | DESIGNED |
| 50-camera logical registry / GIS / scheduler | DESIGNED |
| Regional NVIDIA NVDEC/NVENC multi-host | ESTIMATED / untested |
| Completed measurement of 50 government feeds | **Forbidden claim** |
| Synthetic 16/20/24/30 browser ceiling | MEASURED_SYNTHETIC only |

Cite: `50_CAMERA_SCALING.md`, Phase 10.

---

## Bottleneck (repeat for reviewers)

> Under controlled source conditions, the local media/bridge layer scaled to 15 concurrent preview bridges. During the real mixed-camera wall, large concurrent upstream Sentinel RTSP fan-in produced authentication/time-out/source-availability failures that reduced the number of ready bridges. The remaining limitation is therefore observed at the upstream source/session layer rather than demonstrated as a local VideoToolbox encode-capacity limit.

---

## If Sentinel concurrency / session access improves — remaining validation

1. **Hybrid wall toward 24–30 browser-visible** using measured bridge budget (up to 15) + 15 direct WHEP, without upstream auth stampede.
2. **Persistent source/session layer** proving single upstream pull with fan-out to AI + browser under operator load.
3. **Authoritative catalogue** binding replacing NOT_AUTHORITATIVE probe IDs.
4. **Long soak** (≥120s) at higher bridge counts with stable ready_n.
5. **Regional GPU pool** measurements (today ESTIMATED).

---

## Security / credentials

- Grid credentials: environment only (`SENTINEL_GRID_EMAIL` / `SENTINEL_GRID_PASSWORD`).
- Never in URLs in artifacts, screenshots, or reports.
- No catalogue session bypass.
- Secret scan required before submission (`tools/verify/secret_scan.py`).
