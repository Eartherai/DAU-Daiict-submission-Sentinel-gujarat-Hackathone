# Machine media performance profile

Timestamp UTC: `2026-09-16T04:04:04.045566+00:00`  
Label: **MEASURED**

## Hardware

| Item | Value |
|---|---|
| OS | macOS 	26.6.2 (arm64) |
| CPU | Apple M5 · 10 logical cores |
| GPU | Apple M5 · 10 cores · Metal 4 · Built-In |
| RAM | 25.77 GB total · 12.21 GB available |
| NVIDIA / CUDA | **None** (`nvidia-smi` absent) |

## Hardware video acceleration

| Capability | Status |
|---|---|
| ffmpeg hwaccels | `videotoolbox` |
| VideoToolbox H.264 encode (PyAV) | True |
| VideoToolbox HEVC encode (PyAV) | True |
| Current gov relay decode path | software libav H.264/HEVC (VT decode not wired yet) |

## Browser (Playwright headless Chromium 151.0.7922.34)

| Item | Value |
|---|---|
| WebGL renderer | `ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (LLVM 10.0.0) (0x0000C0DE)), SwiftShader d` |
| H.264 decodingInfo | `{'supported': True, 'smooth': True, 'powerEfficient': False}` |
| HEVC decodingInfo | `{'supported': False, 'smooth': False, 'powerEfficient': False}` |

**Implication:** headless benchmarks use SwiftShader (software). Operator headed Chrome on Metal may sustain more concurrent decodes — treat headless numbers as a **lower bound**.

## Software stack

| Component | Version |
|---|---|
| Python | 3.12.13 |
| PyAV | 18.1.0 |
| MediaMTX | v1.20.1 |
| Network | en0 → 192.168.1.1 |

## Certified media path (unchanged)

```
Government RTSP → PyAV (auth in-process) → MediaMTX → WHEP → Chromium
H.264 → DIRECT_H264
HEVC + browser_hevc_unsupported → HEVC_TRANSCODED_H264
```

Machine-readable: `var/reports/phase9/performance/machine_profile.json`
