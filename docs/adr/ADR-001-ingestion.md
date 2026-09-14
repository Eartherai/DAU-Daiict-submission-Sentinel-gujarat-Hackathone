# ADR-001: Decode via PyAV, not OpenCV VideoCapture
**Status:** accepted **Date:** 2026-08-31 (reaffirmed 2026-09-01)

## Context
The organiser's Integrator's Guide states `CAP_PROP_FPS` "often does not match
the actual delivery rate" and that timing must come from presentation
timestamps. It also warns that on connect the gateway replays a buffered GOP, so
frames briefly arrive faster than real time.

## Options
1. `cv2.VideoCapture` — familiar, ubiquitous.
2. **PyAV** — thin binding over libav; exposes `frame.pts` and `stream.time_base`.
3. GStreamer via `gst-python` — full control, heavy dependency.
4. DeepStream — requires NVIDIA hardware.

## Evaluation
`VideoCapture` exposes only `CAP_PROP_POS_MSEC` (documented unreliable) and
`CAP_PROP_FPS` (documented wrong). Correct timing is **unreachable** through it.
GStreamer is correct but not installable on the dev machine. DeepStream needs
hardware we do not have.

## Decision
PyAV, with GStreamer/DeepStream behind `InferenceBackend` for the GPU profile.

## Trade-offs accepted
PyAV bundles its own FFmpeg shared libraries, which collide with the copies
inside `opencv-python` (observed: one `recursive_mutex` crash at shutdown).
Mitigation: keep decode and inference in separate processes — which is also the
correct scaling boundary.

## Revisit when
We deploy on NVIDIA hardware and DeepStream's `nvurisrcbin` becomes available.
