# 50-camera logical pipeline: baseline versus adaptive scheduler

This is a **SYNTHETIC / LOGICAL 50-CAMERA TEST**. The local catalogue contains
six media clips, so six cameras were processed; the target value of 50 is the
capacity scenario, not a fabricated count of available clips.

| Run | Target | Catalogue | Media processed | Frames | Throughput | Errors |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 50 | 6 | 6 | 42 | 5.850 fps | 0 |
| Adaptive | 50 | 6 | 6 | 42 | 10.606 fps | 0 |

The adaptive result is a short CPU smoke measurement. It validates that the
same catalogue-sized execution path can be selected for a 50-camera scenario;
it does not prove 50 simultaneous government feeds or full 50-camera AI
throughput.

## Required government distinction

```text
Government: 30 currently accessible/measured; approximately 50 official target
Logical validation: target-50 benchmark path executed on available synthetic media
Unverified: 50-camera simultaneous government analytics
```
