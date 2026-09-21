# Model 3 certification — VMS federation + middleware

**Strongest measured result:** 50 DEMO/TEST adapters; kill-one pass=True; kill-10% pass=True; in-process bus 2036798.4 events/s.

**Bottleneck:** real departmental VMS credentials (EXTERNAL_DEPENDENCY). In-process bus is not Kafka.

**UI:** SYSTEM → Connected systems is labelled **DEMO / TEST**.

## Adapter counts

| n | setup_s | discover P50/P95 ms | health P50/P95 ms | response P50/P95 ms | kill-one | kill-10% |
|---|---|---|---|---|---|---|
| 2 | 0.0001 | 0.0009/0.0011 | 0.0053/0.008 | 0.014/0.0183 | True | True |
| 5 | 0.0 | 0.0002/0.0003 | 0.001/0.0012 | 0.0034/0.0043 | True | True |
| 10 | 0.0001 | 0.0001/0.0002 | 0.0008/0.0011 | 0.0019/0.0268 | True | True |
| 25 | 0.0001 | 0.0001/0.0002 | 0.0007/0.0008 | 0.0017/0.0029 | True | True |
| 50 | 0.0002 | 0.0001/0.0002 | 0.0007/0.0008 | 0.0015/0.0027 | True | True |

Reconnect to a live VMS: NOT_MEASURED (EXTERNAL_DEPENDENCY).

## Event bus

| Field | Value |
|---|---|
| events | 5000 |
| elapsed_s | 0.0025 |
| events_per_s | 2036798.4 |
| producer_p50_ms | 0.0004 |
| producer_p95_ms | 0.0005 |
| consumer_count | 5000 |
| consumer_last_s | 0.0025 |
| queue_depth_end | 5000 |
| label | MEASURED_IN_PROCESS |
| production_scale_design | Kafka / RabbitMQ |
| kafka_throughput | NOT_MEASURED |


PRODUCTION SCALE DESIGN: Kafka / RabbitMQ.
