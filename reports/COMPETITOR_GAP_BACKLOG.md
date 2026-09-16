# Competitor gap backlog

Priority uses impact × probability of judge notice × implementation cost.

| Feature | Competitor signal | Our state | Importance | Proposed change | Status |
|---|---|---|---|---|---|
| Full-analytics 50-camera run | Multiple repos pitch multi-camera operation | Decode/load measured; analytics not full-scale | P0 | Add explicit staged 50-camera analytics benchmark with memory and alert latency | Open, correctly documented |
| Government cross-camera repeat | DrishtiNet/TRINETRA/Prahari emphasize route tracing | Synthetic route works; live exact repeats = 0 | P0 | Profile synchronized cameras and report only actual repeated identities | Open; cannot fabricate data |
| Visual command-center polish | Redeye/TRINETRA | Working static workspace and films | P1 | Keep incident-first overview and live health visible in the first screen | Partially implemented |
| Behavior analytics | intel-i-gujarat | Motion/person/attributes exist; suspicion policy absent | P2 | Add auditable rules only with measured false-positive tests | Deferred |
| Adapter catalogue | NETRA/Arka | Protocol fields and adapter-ready model | P1 | Add explicit `CameraAdapter` interface/ONVIF discovery when target endpoint exists | Partial |
| Central Postgres HA | SENTINEL/NETRA architecture | Migration direction, SQLite measured | P1 | Exercise Postgres/PostGIS migration and failover in deployment environment | Open |
| Cost model | Most competitors are conceptual | `docs/SCALE_MODEL.md` exists | P1 | Add assumptions and per-camera/regional/state estimates | Open |
| Judge evidence pack | Competitors compete on presentation | Existing films/docs; reports newly added | P1 | Generate score, benchmark, security, feed, and scale reports from artifacts | Implemented in this branch |
| License clarity | Priyanshu project is Apache-2.0 | Our dependency policy is documented | P1 | Preserve SPDX/third-party audit and never copy unlicensed competitor code | Implemented policy |
