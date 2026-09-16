# GPU / media scaling plan

## Local (Apple M5) — MEASURED

| Item | Status |
|---|---|
| Metal compositor in headed Chromium | **MEASURED** (`ANGLE Metal Renderer: Apple M5`) |
| H.264 powerEfficient | **true** (headed) / false (headless) |
| HEVC powerEfficient | **true** (headed MediaCapabilities) |
| NVIDIA / CUDA | **None** |
| VideoToolbox in ffmpeg | present |
| PyAV VT decode wired in gov relay | **not yet** |

Local scaling path:

1. Headed Metal browser walls (done for 4–12)
2. Tiered WHEP budget (8 full + preview live)
3. Optional: VideoToolbox decode/encode in relay if publish CPU saturates
4. Mosaic compositor only if latency stays acceptable (not yet MEASURED)

## GPU server (NVIDIA) — ESTIMATED / MODELLED only

Do not treat as MEASURED. Methodology:

| Workload | Measure locally | Extrapolate with |
|---|---|---|
| H.264 decode | streams × resolution × FPS | NVDEC capacity tables + bench |
| Detector | images/sec @ batch | TensorRT/ONNX on L4/A10/A100 |
| OCR | plates/sec | same |
| Encode previews | NVENC sessions | vendor session limits |

Suggested regional architecture (**design**, not measured here):

```
Gov RTSP → regional ingest → NVDEC
              ├─ AI batch (CUDA)
              └─ NVENC adaptive ladders → MediaMTX/WHEP → command center
```

Candidate SKUs for later bench (untested): RTX-class, L4, A10/A10G, A100, H100.

## 30 → 50 story

| Layer | 30 | 50 |
|---|---|---|
| Registry / GIS / health | 30 real | 30 real + 20 synthetic |
| Full WHEP | ≤8–12 MEASURED band | same + more regional decode |
| Preview | remaining | remaining |
| AI | selected cameras | selected + regional GPU pool |

Artifacts: `var/reports/phase9/performance/gpu_scaling.json` (seed below).
