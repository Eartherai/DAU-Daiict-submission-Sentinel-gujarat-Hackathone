# Detector benchmark

Footage: `C-014.mp4, C-021.mp4`

| Detector | Frames | p50 ms | p95 ms | FPS | Accuracy | Availability |
|---|---:|---:|---:|---:|---:|---|
| `vehicle-rtdetrv2-r18@0.1.0` | 6 | 47.826 | 229.689 | 11.253 | None | available |
| `vehicle-rfdetr-base@0.1.0` | 6 | 72.508 | 101.793 | 12.951 | None | available |

## Caveats
- No vehicle bounding-box ground truth is present, so accuracy is null.
- Unavailable candidates are recorded; no packages or weights are installed.
- FPS is inference-only and excludes decode; compare on the named footage and host.
