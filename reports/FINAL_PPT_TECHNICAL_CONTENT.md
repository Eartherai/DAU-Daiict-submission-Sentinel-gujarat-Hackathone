# Final PPT — technical content (slide-ready)

Paste into slides as-is. Every number inherits its label from `FINAL_TECHNICAL_EVIDENCE_MASTER.md`. Do not upgrade DESIGNED → MEASURED.

---

## Slide A — Title / thesis

**Saakshya — measured live media for a 30-camera command wall**

Framing (speak):

> Measured and pushed the local browser/media stack through controlled concurrency limits, then isolated remaining constraints at the external live-source/session layer.

Supporting lines:

- Direct WHEP preferred where supported; compatibility bridging applied selectively.
- AI and video planes are decoupled.
- Adaptive media prevents weak cameras from destabilizing the wall.

---

## Slide B — Architecture (30–50 camera production)

**Title:** 30–50 Camera Production Architecture

```
Sentinel RTSP/TCP
        ↓
Persistent source / session layer
        ↓
Regional media / AI pool
   ├─ Direct WHEP          → browser LIVE
   ├─ H.264 compatibility bridge → browser PREVIEW
   ├─ Preview tier         → wall density
   └─ AI (RTSP/TCP)        → detect / ANPR / watchlist
        ↓
Command center (wall · promote · alert · evidence · GIS)
```

**One session → fan-out (speak):**

- One upstream camera session is established and held in the **persistent source/session layer**.
- Downstream consumers **fan out** from that session: AI, direct WHEP (if available), or a selective H.264 compatibility bridge for browser tiles.
- Goal: **avoid duplicate upstream pulls** of the same camera for every browser tile and every AI worker.
- 50-camera statement = **regional pool design** (DESIGNED), not 50 government feeds measured.

**Labels on this slide:** architecture = DESIGNED; direct WHEP + bridge behaviors = MEASURED_REAL (Phases 11, 15, 16).

---

## Slide C — Scalability table

**Title:** Scalability — measured vs design

| Capability | Measured | Target / Design |
|---|---|---|
| 1 camera (direct WHEP) | PASS — MEASURED_REAL (Ph 11/12) | Production LIVE tile |
| 4 camera wall | PASS 4/4 — MEASURED_REAL (Ph 11/12) | Strong operator cluster |
| 8 camera wall | PASS 8/8 — MEASURED_REAL (Ph 12) | Best all-PASS real band |
| ~10 simultaneous PASS | Peak band — MEASURED_REAL (Ph 12) | FULL_WHEP budget seed |
| 15 local bridges | PASS n=15 when sources healthy — MEASURED_REAL (Ph 16) | Compatibility PREVIEW pool |
| 19 real browser-visible | Hybrid wall 30/60/120s — MEASURED_REAL (Ph 16) | Demo hybrid configuration |
| 30 real source census | RTSP 30/30; WHEP 15/30 — MEASURED_REAL (Ph 14) | Identity / health truth |
| 30 adaptive wall | Budgeted FULL + PREVIEW + RTSP_ONLY_AI — MEASURED_REAL + DESIGNED (Ph 12–16) | Operator wall |
| Synthetic 16 full WHEP | 16 PASS — MEASURED_SYNTHETIC (Ph 10) | Browser plane ceiling check |
| 50 logical architecture | — | DESIGNED regional pools (`50_CAMERA_SCALING.md`) |

**Speak:** Do not read the Design column as measured.

---

## Slide D — Evidence headline numbers

**Title:** What we measured on real sources

| Fact | Value | Label |
|---|---|---|
| RTSP frames (census) | **30 / 30** | MEASURED_REAL |
| Direct WHEP browser | **15 / 30** | MEASURED_REAL |
| Concurrent bridges (healthy upstream) | **15** | MEASURED_REAL |
| Hybrid browser-visible (60s) | **19** (15 direct + 4 bridged) | MEASURED_REAL |
| RTSP-only AI on that soak | **11** | MEASURED_REAL |
| NO_SIGNAL | **0** | MEASURED_REAL |
| Warm promote (bridged) | **35.75 ms** p50 | MEASURED_REAL |
| Cold promote (bridged) | **721.7 ms** | MEASURED_REAL |
| H.264 copy → WebRTC | **FAIL** (B-frames) | MEASURED_REAL |
| VT baseline → WebRTC | **PASS** | MEASURED_REAL |

---

## Slide E — Bottleneck (precise)

**Title:** Where the limit sits

> Under controlled source conditions, the local media/bridge layer scaled to 15 concurrent preview bridges. During the real mixed-camera wall, large concurrent upstream Sentinel RTSP fan-in produced authentication/time-out/source-availability failures that reduced the number of ready bridges. The remaining limitation is therefore observed at the upstream source/session layer rather than demonstrated as a local VideoToolbox encode-capacity limit.

**Not claimed:** upstream system failure as a verdict; impossibility of a 30-tile wall; a completed 50-feed government measurement.

---

## Slide F — Demo operator workflow

**Title:** Operator workflow (final demo)

```
30-camera wall
    → select camera
    → warm promotion          (bridged p50 35.75 ms MEASURED_REAL)
    → detection
    → ANPR
    → watchlist
    → alert
    → evidence
    → Follow Vehicle
    → GIS
```

**Demo configuration (strongest real):**

- Wall: **15 direct Sentinel WHEP + 4 bridged PREVIEW** (= **19** browser-visible)
- Remaining tiles: **RTSP-only AI** (source live; not NO_SIGNAL)
- Layout: keep **12**-tile demo framing; 16 / 25 / 30 layouts available
- Camera evidence: real Sentinel IDs from Phase 14 matrix (e.g. cam01 family for LIVE; cam07-class for bridge proof)

---

## Slide G — Planes & isolation

**Title:** Decoupled planes + peer isolation

| Plane | Path |
|---|---|
| Browser primary | Direct Sentinel WHEP + Basic auth |
| Browser compatibility | RTSP → VT baseline H.264 → local WHEP |
| AI | RTSP/TCP (unchanged by browser bridge load) |

Speak:

- Adaptive media architecture prevents weak cameras from destabilizing the wall.
- One-camera failure does not take down peers (independent negotiation — MEASURED_REAL).

---

## Slide H — Limitations (short)

See full text in `FINAL_LIMITATIONS_AND_EXTERNAL_DEPENDENCIES.md`. Slide bullets:

- Sentinel catalogue session not available → IDs **NOT_AUTHORITATIVE**
- Best hybrid browser-visible: **19** (MEASURED_REAL)
- Remaining RTSP-only cams stay **AI-capable**
- Large upstream fan-in → auth/timeouts affecting bridge readiness
- **50-camera** = architecture/scaling design, not 50-gov-feed measurement

---

## Slide I — Closing ask / next validation

If Sentinel concurrency / session access improves, validate next:

1. Sustained hybrid wall with **>4** ready bridges toward **15 direct + N bridged → 24–30 browser-visible**
2. Persistent source layer with **single upstream session** per camera under operator load
3. Authoritative catalogue binding (`/api/ingest`) replacing probe IDs
4. Regional NVDEC/NVENC pool estimates under real multi-host deploy (today: ESTIMATED / untested)
