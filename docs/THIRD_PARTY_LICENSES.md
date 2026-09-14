# Third-Party Licence Register

Every dependency is recorded in the commit that adds it. Licence risk in a
government PoC that is intended to become a product is a design constraint, not
an afterthought.

## Runtime dependencies (ship with the product)

| Component | Version | Licence | Class | Notes |
|---|---|---|---|---|
| PyAV | 18.1.0 | BSD-3-Clause | Permissive | Wraps FFmpeg libs (LGPL as distributed in the wheel). Dynamic linking, no modification. |
| numpy | 2.5.2 | BSD-3-Clause | Permissive | |
| FastAPI | 0.141.1 | MIT | Permissive | |
| Uvicorn | ≥0.32 | BSD-3-Clause | Permissive | |
| Pydantic | 2.13.5 | MIT | Permissive | |
| httpx | ≥0.27 | BSD-3-Clause | Permissive | |
| SQLAlchemy | 2.0.52 | MIT | Permissive | |
| Pillow | 12.3.0 | MIT-CMU (HPND) | Permissive | |
| onnxruntime | 1.29.0 | MIT | Permissive | |
| fast-alpr | current | MIT | Permissive | Thin orchestration over the two below |
| fast-plate-ocr | current | MIT | Permissive | OCR runtime |
| open-image-models | current | MIT | Permissive | Plate detector runtime |
| opencv-python | transitive | Apache-2.0 | Permissive | Pulled in by fast-alpr. See conflict note below. |
| MediaMTX | 1.20.1 | MIT | Permissive | **Dev/test only** — the sandbox replica. Not shipped. |
| torch | 2.13.0 | BSD-3-Clause | Permissive | Required by `transformers`. Apple MPS measured 3.5x faster than CPU for RT-DETRv2. |
| torchvision | current | BSD-3-Clause | Permissive | torch dependency |
| transformers | 5.16.1 | Apache-2.0 | Permissive | RT-DETRv2 / DINOv2 loading |

## Model weights — licensed separately from code

| Model | Licence | Notes |
|---|---|---|
| `yolo-v9-t-640-license-plate-end2end` | MIT (open-image-models) | Selected by measurement over the `-s-608` variant |
| `cct-s-v2-global-model` | MIT (fast-plate-ocr) | 10 plate slots — required for 10-character Indian marks |

## Build-time tools (never linked into the product)

| Tool | Licence | Use |
|---|---|---|
| FFmpeg 7.1 via `imageio-ffmpeg` | **GPL build** (`--enable-gpl`, libx264/libx265) | Invoked as an external binary to render the synthetic corpus and publish test streams. Not linked, not distributed with the product. If corpus media is ever redistributed, the GPL implications of the encoder must be re-examined. |

## Explicitly rejected

| Component | Licence | Why rejected |
|---|---|---|
| Ultralytics YOLO (all versions) | **AGPL-3.0** | Ultralytics states the licence covers trained models, not only training code. A network-served government platform would inherit an obligation over the larger work. |
| BoxMOT | **AGPL-3.0** | Same class of risk; it is the default many teams reach for. |
| InsightFace | **No repository licence**; research-only model terms | One of several reasons facial recognition is out of scope for the PoC. |

## Open issues

- **opencv-python / PyAV native conflict.** Both bundle FFmpeg shared libraries
  (`libavdevice.61` vs `.62`). Loading both in one process logs a duplicate-class
  warning on macOS and produced one observed crash
  (`recursive_mutex lock failed`) at interpreter shutdown. Mitigation: keep
  decode (PyAV) and inference (ONNX/cv2) in **separate processes**, which is
  also the correct scaling architecture. Tracked as a blocking item before the
  pipeline runs decode and ANPR in one process.
