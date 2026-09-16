# Tracker benchmark

Footage: `C-014.mp4`

| Tracker | Available | Frames | p50 ms | p95 ms | FPS | Accuracy |
|---|---|---:|---:|---:|---:|---|
| `ByteTracker (in-tree, PTS-aware)` | True | 20 | 0.208 | 0.378 | 3072.255 | None |
| `DeepSORT` | False | 0 | None | None | 0 | None |
| `OC-SORT` | False | 0 | None | None | 0 | None |
| `BoT-SORT` | False | 0 | None | None | 0 | None |

## Caveats
- No track bounding-box or identity ground truth is present; accuracy is null.
- The measured input uses the project's model-free motion boxes, not fabricated boxes.
- Candidate availability is an environment check only; no migration or installation occurs.
