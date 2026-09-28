# Model 2 certification — unified viewing + metadata

**Strongest measured result:** 19 browser-visible government tiles (8 LIVE, 11 PREVIEW, 15 DIRECT WHEP, 4 BRIDGED, 11 RTSP_ONLY_AI, 0 NO_SIGNAL) on the Phase 16 120 s hybrid wall. First-frame P50 8122.1 ms / P95 14831.76 ms.

**Observed:** upstream WHEP failures during this test window. The report does not establish a fixed upstream session ceiling or a local bridge maximum.

**MEASURED DURING A TEST WINDOW:** 19 simultaneous government browser tiles MEASURED_REAL. 30 cameras registered. 50 = logical composition, not 50 government live feeds.

**GPU / browser CPU / RAM:** NOT_MEASURED.

Current wall policies: CONTROL ROOM up to 30 / OPTIMIZED VIEW at most 12
(`ui/app.js`). See `docs/SENTINEL_SUPPORT_CLARIFICATION.md`.

## TEST A — wall sizes

[
  {
    "logical_n": 1,
    "domain": "GOVERNMENT",
    "bridge_n": 1,
    "tier": "PREVIEW",
    "live_tiles": 1,
    "first_frame_ms_p50": 2010.7,
    "ffmpeg_cpu_sum": 6.4,
    "label": "MEASURED_REAL",
    "note": "PREVIEW-tier VT bridges, not the 19-tile hybrid wall"
  },
  {
    "logical_n": 4,
    "domain": "GOVERNMENT",
    "bridge_n": 4,
    "tier": "PREVIEW",
    "live_tiles": 4,
    "first_frame_ms_p50": 1574.1500000059605,
    "ffmpeg_cpu_sum": 45.4,
    "label": "MEASURED_REAL",
    "note": "PREVIEW-tier VT bridges, not the 19-tile hybrid wall"
  },
  {
    "logical_n": 8,
    "domain": "GOVERNMENT",
    "bridge_n": 8,
    "tier": "PREVIEW",
    "live_tiles": 8,
    "first_frame_ms_p50": 1299.3999999985099,
    "ffmpeg_cpu_sum": 72.3,
    "label": "MEASURED_REAL",
    "note": "PREVIEW-tier VT bridges, not the 19-tile hybrid wall"
  },
  {
    "logical_n": 12,
    "domain": "GOVERNMENT",
    "bridge_n": 12,
    "tier": "PREVIEW",
    "live_tiles": 12,
    "first_frame_ms_p50": 2858.7000000029802,
    "ffmpeg_cpu_sum": 45.6,
    "label": "MEASURED_REAL",
    "note": "PREVIEW-tier VT bridges, not the 19-tile hybrid wall"
  },
  {
    "logical_n": 16,
    "domain": "GOVERNMENT",
    "label": "NOT_MEASURED",
    "note": "No dedicated 16-tile government wall soak in artifacts"
  },
  {
    "logical_n": 25,
    "domain": "GOVERNMENT",
    "label": "NOT_MEASURED",
    "note": "No dedicated 25-tile government wall soak in artifacts"
  },
  {
    "logical_n": 30,
    "domain": "GOVERNMENT",
    "registered": 30,
    "browser_visible": 19,
    "FULL": 8,
    "PREVIEW": 11,
    "RTSP_ONLY_AI": 11,
    "NO_SIGNAL": 0,
    "first_frame_p50_ms": 8122.1,
    "first_frame_p95_ms": 14831.76,
    "freezes": 24,
    "drops": 260,
    "packet_loss": 56,
    "browser_cpu": "NOT_MEASURED",
    "browser_ram": "NOT_MEASURED",
    "gpu": "NOT_MEASURED",
    "label": "MEASURED_REAL hybrid 120s"
  },
  {
    "logical_n": 50,
    "domain": "GOVERNMENT",
    "registered": "30 GOVERNMENT + 2 OWN_FEED + 18 SYNTHETIC_CONTROL",
    "browser_visible_government": 19,
    "label": "MEASURED_SYNTHETIC composition; government live \u2260 50",
    "FULL": "NOT_MEASURED",
    "PREVIEW": "NOT_MEASURED",
    "first_frame_p50_ms": "NOT_MEASURED"
  }
]

## TEST B — UI modes

{
  "modes": [
    {
      "mode": "VIDEO ONLY",
      "car": false,
      "person": false,
      "plate": false,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "VEHICLES",
      "car": true,
      "person": false,
      "plate": true,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "PEOPLE",
      "car": false,
      "person": true,
      "plate": false,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "VEHICLES + PEOPLE",
      "car": true,
      "person": true,
      "plate": true,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "ANPR",
      "car": false,
      "person": false,
      "plate": true,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "FULL",
      "car": true,
      "person": true,
      "plate": true,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    },
    {
      "mode": "INCIDENT",
      "car": true,
      "person": true,
      "plate": true,
      "duplicate_whep": false,
      "note": "Overlay is store metadata; it does not open a second WHEP."
    }
  ],
  "label": "MEASURED unit overlay filters",
  "global_wall_reset": false
}

## TEST C — COMPARE

Compare copies the same video element with canvas.drawImage. No second WHEP.

## TEST D — operator actions

Product actions exist. Latency of click-through is NOT_MEASURED this run (no new Sentinel soak).
