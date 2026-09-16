# Live feed root-cause status

> Phase 7C artifact-level findings are maintained in
> [GOVERNMENT_FEED_ROOT_CAUSE.md](GOVERNMENT_FEED_ROOT_CAUSE.md), including
> the per-camera raw-frame review and the explicit proven/likely/unverified
> boundary.

## Current classification

| Layer | Evidence | Status |
| --- | --- | --- |
| Source | No authenticated representative stream in this workspace | UNDETERMINED |
| Network | No packet capture or venue run available | UNDETERMINED |
| Decoder | PyAV/PTS ingest and corruption heuristics exist; no current external sample | UNDETERMINED |
| Gateway | WHEP gateway endpoint is not configured in this environment | UNAVAILABLE |
| Browser transport | WHEP lifecycle and browser stats are instrumented; no live session available | UNAVAILABLE |
| Browser rendering | Snapshot fallback and selected-camera lifecycle are covered in code; no browser run available | UNAVAILABLE |
| AI overlay | Analytics remains separate from the selected-camera video path; no live overlay run available | UNAVAILABLE |

No layer is accused without a controlled comparison. The next venue run must
compare the same browser/player against a known-good own feed and an affected
government camera, with UTC timestamps and diagnostic artifacts.
