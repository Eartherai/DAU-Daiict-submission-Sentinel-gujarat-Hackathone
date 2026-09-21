# Model 4 certification — central intelligence (hero)

Golden files mapped this run:

- OWN-PEOPLE ← `/Users/earther/Desktop/Gujarat CCTV/1.mp4` (29.1 s)
- OWN-TRAFFIC ← `/Users/earther/Desktop/Gujarat CCTV/2.mp4` (762.5 s)

**Strongest measured result:** own-file decode first-frame OWN-PEOPLE 15.9 ms; OWN-TRAFFIC 7.8 ms. Controlled watchlist DETECTION→ALERT 1.701 ms (DEMO / CONTROLLED TEST).

**Bottleneck:** live own-feed WHEP/AI worker not attached in this process; GPU NOT_MEASURED.

Own-feed CameraPipeline ran this session.

ANPR accuracy = NOT_MEASURED. GPU = NOT_MEASURED (never 0%).

## TEST A — VIDEO ONLY

[
  {
    "camera_id": "OWN-PEOPLE",
    "path": "/Users/earther/Desktop/Gujarat CCTV/1.mp4",
    "requested_window_s": 30.0,
    "frames": 873,
    "last_pts_s": 29.067,
    "first_frame_ms": 15.9,
    "wall_s": 3.597,
    "steady_decode_fps": 243.75,
    "file_exhausted": true,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  },
  {
    "camera_id": "OWN-PEOPLE",
    "path": "/Users/earther/Desktop/Gujarat CCTV/1.mp4",
    "requested_window_s": 60.0,
    "frames": 873,
    "last_pts_s": 29.067,
    "first_frame_ms": 15.48,
    "wall_s": 3.599,
    "steady_decode_fps": 243.6,
    "file_exhausted": true,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  },
  {
    "camera_id": "OWN-PEOPLE",
    "path": "/Users/earther/Desktop/Gujarat CCTV/1.mp4",
    "requested_window_s": 120.0,
    "frames": 873,
    "last_pts_s": 29.067,
    "first_frame_ms": 15.52,
    "wall_s": 3.599,
    "steady_decode_fps": 243.59,
    "file_exhausted": true,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  },
  {
    "camera_id": "OWN-TRAFFIC",
    "path": "/Users/earther/Desktop/Gujarat CCTV/2.mp4",
    "requested_window_s": 30.0,
    "frames": 361,
    "last_pts_s": 30.0,
    "first_frame_ms": 7.8,
    "wall_s": 0.217,
    "steady_decode_fps": 1727.81,
    "file_exhausted": false,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  },
  {
    "camera_id": "OWN-TRAFFIC",
    "path": "/Users/earther/Desktop/Gujarat CCTV/2.mp4",
    "requested_window_s": 60.0,
    "frames": 721,
    "last_pts_s": 60.0,
    "first_frame_ms": 7.77,
    "wall_s": 0.5,
    "steady_decode_fps": 1465.75,
    "file_exhausted": false,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  },
  {
    "camera_id": "OWN-TRAFFIC",
    "path": "/Users/earther/Desktop/Gujarat CCTV/2.mp4",
    "requested_window_s": 120.0,
    "frames": 1441,
    "last_pts_s": 120.0,
    "first_frame_ms": 7.74,
    "wall_s": 1.485,
    "steady_decode_fps": 975.75,
    "file_exhausted": false,
    "cpu": "NOT_MEASURED",
    "ram_mb": 375.6,
    "gpu": "NOT_MEASURED",
    "freeze": "NOT_MEASURED",
    "drop": "NOT_MEASURED",
    "label": "MEASURED_OWN_FEED decode-only (PyAV, no Sentinel)",
    "note": "Decode FPS is not browser playback FPS and not detector FPS."
  }
]

## TEST B — DETECTION / TRACKER / OCR / FULL

Own-feed pipeline: [
  {
    "camera_id": "OWN-PEOPLE",
    "path": "/Users/earther/Desktop/Gujarat CCTV/1.mp4",
    "label": "MEASURED_OWN_FEED",
    "error": null,
    "anpr_accuracy": "NOT_MEASURED",
    "gpu": "NOT_MEASURED",
    "frames_in": 12,
    "frames_analysed": 12,
    "elapsed_s": 3.584,
    "inference_p50_ms": 22.2788,
    "inference_p95_ms": 1529.1339,
    "people_observations": 0,
    "vehicle_observations": 0,
    "plates": 0,
    "tracks": 0,
    "pipeline_stats": {
      "vehicle_detections": 0,
      "person_detections": 0,
      "plate_detections": 0,
      "tracks_created": 0
    },
    "pipeline_fps": 3.348,
    "detector_fps": "NOT_MEASURED",
    "note": "pipeline_fps is CameraPipeline.process wall rate. detector_fps is only set when observations were emitted."
  },
  {
    "camera_id": "OWN-TRAFFIC",
    "path": "/Users/earther/Desktop/Gujarat CCTV/2.mp4",
    "label": "MEASURED_OWN_FEED",
    "error": null,
    "anpr_accuracy": "NOT_MEASURED",
    "gpu": "NOT_MEASURED",
    "frames_in": 12,
    "frames_analysed": 12,
    "elapsed_s": 0.44,
    "inference_p50_ms": 22.759,
    "inference_p95_ms": 116.0195,
    "people_observations": 0,
    "vehicle_observations": 0,
    "plates": 0,
    "tracks": 0,
    "pipeline_stats": {
      "vehicle_detections": 0,
      "person_detections": 0,
      "plate_detections": 0,
      "tracks_created": 0
    },
    "pipeline_fps": 27.296,
    "detector_fps": "NOT_MEASURED",
    "note": "pipeline_fps is CameraPipeline.process wall rate. detector_fps is only set when observations were emitted."
  }
]

Government cam01 (not M4 own-feed): {
  "label": "MEASURED_REAL government cam01",
  "artifact": "var/reports/phase8c/gov/cam01_ai_runtime.json",
  "modes": [
    {
      "mode": "VIDEO_ONLY",
      "verdict": "AMBER",
      "pipeline_p50_ms": null,
      "pipeline_p95_ms": null,
      "frames_analysed": null,
      "vehicle_detections": null,
      "person_note": "government cam01 \u2014 not an own-feed benchmark"
    },
    {
      "mode": "DETECTION",
      "verdict": "PASS",
      "pipeline_p50_ms": 47.8,
      "pipeline_p95_ms": 90.43,
      "frames_analysed": 775,
      "vehicle_detections": 5457,
      "person_note": "government cam01 \u2014 not an own-feed benchmark"
    },
    {
      "mode": "DETECTION_TRACKER",
      "verdict": "PASS",
      "pipeline_p50_ms": 61.0,
      "pipeline_p95_ms": 69.48,
      "frames_analysed": 761,
      "vehicle_detections": 10306,
      "person_note": "government cam01 \u2014 not an own-feed benchmark"
    },
    {
      "mode": "DETECTION_TRACKER_OCR",
      "verdict": "PASS",
      "pipeline_p50_ms": 54.45,
      "pipeline_p95_ms": 133.86,
      "frames_analysed": 777,
      "vehicle_detections": 6347,
      "person_note": "government cam01 \u2014 not an own-feed benchmark"
    },
    {
      "mode": "FULL",
      "verdict": "PASS",
      "pipeline_p50_ms": 101.07,
      "pipeline_p95_ms": 119.97,
      "frames_analysed": 547,
      "vehicle_detections": 9050,
      "person_note": "government cam01 \u2014 not an own-feed benchmark"
    }
  ],
  "anpr_accuracy": null,
  "not_own_feed": true,
  "gpu": "NOT_MEASURED"
}

## TEST C — PEOPLE

People observations: 0 (MEASURED_OWN_FEED)

## TEST D — VEHICLES

Vehicle observations: 0 (MEASURED_OWN_FEED)

## TEST E — ANPR

Accuracy: NOT_MEASURED (no own-feed ground truth).

## TEST F — WATCHLIST

| Field | Value |
|---|---|
| label | DEMO / CONTROLLED TEST |
| entries | `["GJ01TA0001", "GJ01WA0002", "GJ01CU0003"]` |
| live_match_fabricated | False |
| detection_to_match_ms | 0.972 |
| match_to_alert_ms | 0.73 |
| detection_to_alert_ms | 1.701 |
| alert_id | AL01M2P5XS1JCWZJ704KPVKESJHA |
| plate | GJ01TA0001 |
| camera | OWN-TRAFFIC |
| note | Observation was inserted as a controlled fixture, not read from pixels. |


## TEST G / H — INVESTIGATION + ROUTE

Valid: {
  "hops": [
    "FIRST SEEN",
    "NEXT",
    "LAST SEEN"
  ],
  "n_hops": 3,
  "verdicts": [
    "MATCH",
    "MATCH",
    "MATCH"
  ],
  "first": {
    "role": "FIRST SEEN",
    "camera_id": "OWN-TRAFFIC",
    "signal": "OWN-TRAFFIC",
    "t": "2026-09-01T08:00:00+00:00",
    "observation_id": "OB01M2P5XS1M3A6QE07M4K7HZGBZ",
    "evidence_ref": null,
    "plate": "GJ01VV0001",
    "lat": 23.04,
    "lon": 72.58,
    "object_type": null,
    "elapsed_from_prev_s": null,
    "elapsed_label": null,
    "source_domain": "OWN_FEED",
    "location": "Ahmedabad"
  },
  "last": {
    "role": "LAST SEEN",
    "camera_id": "cam12",
    "signal": "cam12",
    "t": "2026-09-01T08:04:00+00:00",
    "observation_id": "OB01M2P5XS1MKDBJ408WRKWSY4XW",
    "evidence_ref": null,
    "plate": "GJ01VV0001",
    "lat": 23.05,
    "lon": 72.59,
    "object_type": null,
    "elapsed_from_prev_s": 120.0,
    "elapsed_label": "2m 00s",
    "source_domain": "GOVERNMENT",
    "location": "Ahmedabad"
  }
}

Impossible: {
  "contradictions": [
    {
      "from_camera": "OWN-TRAFFIC",
      "to_camera": "FAR",
      "distance_km": 173.46,
      "elapsed_s": 2.0,
      "expected_minimum_s": 3122.3,
      "implied_speed_kmh": 312235.4,
      "reason": "173.46 km in 2.0 s implies 312,235 km/h, above the 200 km/h road ceiling",
      "result": "CONTRADICTION",
      "verdict": "CONTRADICTION",
      "confidence": 0.0,
      "operator_reason": "distance 173.46 km \u00b7 elapsed 2.0s \u00b7 minimum plausible travel 3122.3s"
    },
    {
      "from_camera": "FAR",
      "to_camera": "cam07",
      "distance_km": 173.35,
      "elapsed_s": 118.0,
      "expected_minimum_s": 3120.3,
      "implied_speed_kmh": 5288.7,
      "reason": "173.35 km in 118.0 s implies 5,289 km/h, above the 200 km/h road ceiling",
      "result": "CONTRADICTION",
      "verdict": "CONTRADICTION",
      "confidence": 0.0,
      "operator_reason": "distance 173.35 km \u00b7 elapsed 118.0s \u00b7 minimum plausible travel 3120.3s"
    },
    {
      "from_camera": "FAR",
      "to_camera": "cam12",
      "distance_km": 172.36,
      "elapsed_s": 238.0,
      "expected_minimum_s": 3102.5,
      "implied_speed_kmh": 2607.1,
      "reason": "172.36 km in 238.0 s implies 2,607 km/h, above the 200 km/h road ceiling",
      "result": "CONTRADICTION",
      "verdict": "CONTRADICTION",
      "confidence": 0.0,
      "operator_reason": "distance 172.36 km \u00b7 elapsed 238.0s \u00b7 minimum plausible travel 3102.5s"
    },
    {
      "from_camera": "OWN-TRAFFIC",
      "to_camera": "cam07",
      "distance_km": 0.15,
      "elapsed_s": 120.0,
      "expected_minimum_s": null,
      "reason": "appearance/class/colour lead; plate unreadable",
      "result": "CANDIDATE",
      "verdict": "MATCH",
      "confidence": 0.734,
      "operator_reason": "distance 0.15 km \u00b7 elapsed 120.0s \u00b7 minimum plausible travel \u2014s"
    },
    {
      "from_camera": "OWN-TRAFFIC",
      "to_camera": "cam12",
      "distance_km": 1.51,
      "elapsed_s": 240.0,
      "expected_minimum_s": null,
      "reason": "appearance/class/colour lead; plate unreadable",
      "result": "CANDIDATE",
      "verdict": "MATCH",
      "confidence": 0.712,
      "operator_reason": "distance 1.51 km \u00b7 elapsed 240.0s \u00b7 minimum plausible travel \u2014s"
    }
  ],
  "pass": true
}

## TEST I — JUMP

Government seekable: False

Own-file seek: {
  "ok": true,
  "seekable": true,
  "requested_pts_s": 10.0,
  "landed_pts_s": 9.933333333333334,
  "first_frame_ms": 129.8,
  "seek_latency_ms": 1219.7,
  "label": "MEASURED_OWN_FEED file PTS seek",
  "note": "Live WHEP is not seekable; this path is own-feed file replay only."
}

## TEST J — FAST / BALANCED / DEEP

{
  "presets": [
    {
      "preset": "FAST",
      "overlay_poll_ms": 400,
      "intent": "lowest overlay / admission latency",
      "infer_flags_per_100": 100,
      "ocr_flags_per_100": 13,
      "queue_admit_20": 8,
      "queue_shed_20": 12,
      "label": "MEASURED scheduler cadence \u2014 not detector FPS"
    },
    {
      "preset": "BALANCED",
      "overlay_poll_ms": 1000,
      "intent": "normal analysis",
      "infer_flags_per_100": 25,
      "ocr_flags_per_100": 13,
      "queue_admit_20": 8,
      "queue_shed_20": 12,
      "label": "MEASURED scheduler cadence \u2014 not detector FPS"
    },
    {
      "preset": "DEEP",
      "overlay_poll_ms": 1000,
      "intent": "maximum useful analysis; overlay poll stays bounded",
      "infer_flags_per_100": 100,
      "ocr_flags_per_100": 100,
      "queue_admit_20": 8,
      "queue_shed_20": 12,
      "label": "MEASURED scheduler cadence \u2014 not detector FPS"
    }
  ],
  "best": "NOT_MEASURED",
  "note": "No preset is labelled best; FAST infers more often, DEEP OCRs more often."
}

## TEST K — FAILURE ISOLATION

{
  "kill_ai_worker": {
    "video_continued": true,
    "frames_after_kill": 10,
    "ai_error": "ai worker killed",
    "label": "MEASURED in-process isolation (not a live Sentinel soak)"
  },
  "stop_ocr": {
    "video_continues": true,
    "detection_continues": true,
    "note": "OCR is gated by scheduler ocr_every; video/detect flags remain.",
    "label": "DESIGNED + scheduler-measured"
  },
  "stop_watchlist": {
    "video_continues": true,
    "detection_continues": true,
    "alerts": "degraded / none if engine not called",
    "label": "DESIGNED"
  },
  "queue_overload_sheds_normal": true,
  "gpu": "NOT_MEASURED"
}

## TEST L — DASHBOARD KPIs

`/command/summary` exposes `kpis` and `resources` with a source on every cell. GPU is NOT_MEASURED.
