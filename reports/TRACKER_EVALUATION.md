# Tracker evaluation

`tools/benchmark_trackers.py` measured the in-tree PTS-aware ByteTracker on
`C-014.mp4`: 20 frames, 0.208 ms p50, 0.378 ms p95, and 3072.255 FPS. No
track bounding-box or identity ground truth is present, so accuracy is
**unavailable**, not 100%.

DeepSORT, OC-SORT, and BoT-SORT were reported unavailable in the same run and
were not installed or substituted. Focused regression tests cover PTS-derived
velocity, irregular PTS ordering, age-out in stream seconds, low-confidence
recovery, and segment isolation. These tests establish behaviour, not
real-world identity accuracy.
