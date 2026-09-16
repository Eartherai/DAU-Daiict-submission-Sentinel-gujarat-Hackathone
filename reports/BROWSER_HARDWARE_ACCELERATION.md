# Headed browser GPU profile

Timestamp UTC: `2026-09-16T13:21:04.538581+00:00`

## Headless vs headed (MEASURED)

| Mode | WebGL renderer | Metal | H.264 powerEfficient | HEVC powerEfficient |
|---|---|---|---|---|
| headless | `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C` | False | False | False |
| **headed** | `ANGLE (Apple, ANGLE Metal Renderer: Apple M5, Unspecified Version)` | **True** | **True** | **True** |

## Verdict

- Headed Metal proven: **True**
- 4-stream SwiftShader result is a **harness lower bound**, not the machine limit.
- Wall performance benchmarks MUST use headed Chromium.

Machine-readable: `var/reports/phase9/performance/browser_gpu_profile.json`
