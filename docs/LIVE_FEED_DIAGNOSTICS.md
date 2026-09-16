# Live-feed diagnostic schema

`tools/live_feed_diagnostics.py` is a bounded, read-only probe for a local
media file or a URL. It never requires government credentials and never turns
declared FPS into a measured value.

```sh
python tools/live_feed_diagnostics.py sample.mp4 --seconds 10 --format json
python tools/live_feed_diagnostics.py rtsp://host/camera --retries 2 --format markdown
```

The JSON `schema_version` is currently `1`. `availability` is one of
`MEASURED`, `METADATA_ONLY`, `PARTIAL`, `UNAVAILABLE`, or `UNKNOWN`.
`stream` contains codec, resolution, pixel format, time base and declared FPS.
`timing` contains decoded-frame counts, missing/regressing/jumping PTS and
inter-frame statistics. `quality` contains sampled black-frame, freeze-frame,
corrupt-frame and luma heuristics. `reconnect.reconnects` counts extra open
attempts made by this probe; it does **not** claim that an upstream service
disconnected. A `null` measurement means it was unavailable, not zero.

PyAV is used for frame and PTS measurements. If PyAV is unavailable, `ffprobe`
may provide metadata only, and the report explicitly records that limitation.
Credentials are removed from displayed source URLs and errors.
