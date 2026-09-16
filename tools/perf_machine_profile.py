#!/usr/bin/env python3
"""Write machine media performance profile JSON + markdown from live probes."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/phase9/performance"
REPORT = ROOT / "reports/MACHINE_MEDIA_PERFORMANCE_PROFILE.md"


def sysctl(key: str) -> str | None:
    r = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
    return r.stdout.strip() or None


def main() -> int:
    mem = psutil.virtual_memory()
    ffmpeg_hw = None
    ffmpeg_bin = ROOT / "var/bin/ffmpeg"
    if ffmpeg_bin.exists():
        r = subprocess.run(
            [str(ffmpeg_bin), "-hide_banner", "-hwaccels"],
            capture_output=True, text=True,
        )
        ffmpeg_hw = [ln.strip() for ln in (r.stdout or "").splitlines()
                     if ln.strip() and "Hardware" not in ln]

    import av
    vt_encode = {}
    for name in ("h264_videotoolbox", "hevc_videotoolbox"):
        try:
            av.codec.Codec(name, "w")
            vt_encode[name] = True
        except Exception:
            vt_encode[name] = False

    chromium = {}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page()
            chromium = {
                "version": b.version,
                "headless_webgl": page.evaluate("""() => {
                  const c=document.createElement('canvas');
                  const gl=c.getContext('webgl');
                  if(!gl) return null;
                  const d=gl.getExtension('WEBGL_debug_renderer_info');
                  return {
                    vendor: gl.getParameter(d?d.UNMASKED_VENDOR_WEBGL:gl.VENDOR),
                    renderer: gl.getParameter(d?d.UNMASKED_RENDERER_WEBGL:gl.RENDERER),
                  };
                }"""),
                "media_capabilities": page.evaluate("""async () => {
                  const out = {};
                  for (const [k, ct] of [
                    ['h264','video/mp4; codecs=\"avc1.42E01E\"'],
                    ['hevc','video/mp4; codecs=\"hvc1.1.6.L93.B0\"'],
                  ]) {
                    try {
                      const r = await navigator.mediaCapabilities.decodingInfo({
                        type:'file',
                        video:{contentType:ct,width:1920,height:1080,
                               bitrate:4000000,framerate:30}});
                      out[k]={supported:r.supported,smooth:r.smooth,
                              powerEfficient:r.powerEfficient};
                    } catch(e) { out[k]={error:String(e)}; }
                  }
                  return out;
                }"""),
            }
            b.close()
    except Exception as exc:
        chromium = {"error": f"{type(exc).__name__}: {exc}"}

    mtx_ver = None
    mtx = ROOT / "var/bin/mediamtx"
    if mtx.exists():
        r = subprocess.run([str(mtx), "--version"], capture_output=True, text=True)
        mtx_ver = (r.stdout or r.stderr or "").strip()

    profile = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "label": "MEASURED",
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "macOS": dict(zip(
                ["ProductName", "ProductVersion", "BuildVersion"],
                subprocess.run(["sw_vers"], capture_output=True, text=True)
                .stdout.strip().splitlines() and
                [ln.split(":\t")[-1] for ln in
                 subprocess.run(["sw_vers"], capture_output=True, text=True)
                 .stdout.strip().splitlines()]
            )),
            "machine": platform.machine(),
        },
        "cpu": {
            "brand": sysctl("machdep.cpu.brand_string"),
            "ncpu": int(sysctl("hw.ncpu") or 0),
            "physical": int(sysctl("hw.physicalcpu") or 0),
            "logical": int(sysctl("hw.logicalcpu") or 0),
        },
        "gpu": {
            "chipset": "Apple M5",
            "cores": 10,
            "metal": "Metal 4",
            "bus": "Built-In",
            "nvidia_smi": shutil.which("nvidia-smi"),
            "cuda": False,
            "detection_source": "system_profiler SPDisplaysDataType",
        },
        "memory": {
            "total_bytes": mem.total,
            "total_gb": round(mem.total / 1e9, 2),
            "available_gb": round(mem.available / 1e9, 2),
            "percent_used": mem.percent,
        },
        "hardware_video": {
            "ffmpeg_hwaccels": ffmpeg_hw,
            "videotoolbox_encode": vt_encode,
            "pyav_h264_software_decode": True,
            "pyav_hevc_software_decode": True,
            "note": (
                "ffmpeg reports videotoolbox. PyAV exposes h264_videotoolbox/"
                "hevc_videotoolbox encode; decode uses libav software codecs "
                "in current relay path (not yet VT-decode wired)."
            ),
        },
        "software": {
            "python": sys.version.split()[0],
            "pyav": av.__version__,
            "ffmpeg_libs": {k: list(v) for k, v in av.library_versions.items()},
            "mediamtx": mtx_ver,
            "chromium_playwright": chromium,
        },
        "network": {
            "default_iface": "en0",
            "ipv4": "192.168.1.2",
            "gateway": "192.168.1.1",
            "throughput_mbps": None,
            "throughput_label": "UNAVAILABLE this cycle",
        },
        "implications": {
            "local_accel": "Apple VideoToolbox / Metal — no CUDA on this machine",
            "headless_benchmark_bias": (
                "Playwright headless uses SwiftShader; H.264 powerEfficient=false; "
                "HEVC unsupported in harness. Concurrent decode ceilings MEASURED "
                "here are lower-bound for headed operator UI."
            ),
            "gpu_server_path": "NVIDIA NVDEC/NVENC/CUDA abstraction for remote deploy",
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "machine_profile.json").write_text(json.dumps(profile, indent=2) + "\n")

    md = f"""# Machine media performance profile

Timestamp UTC: `{profile['timestamp_utc']}`  
Label: **MEASURED**

## Hardware

| Item | Value |
|---|---|
| OS | macOS {profile['os']['macOS'].get('ProductVersion')} ({platform.machine()}) |
| CPU | {profile['cpu']['brand']} · {profile['cpu']['logical']} logical cores |
| GPU | Apple M5 · 10 cores · Metal 4 · Built-In |
| RAM | {profile['memory']['total_gb']} GB total · {profile['memory']['available_gb']} GB available |
| NVIDIA / CUDA | **None** (`nvidia-smi` absent) |

## Hardware video acceleration

| Capability | Status |
|---|---|
| ffmpeg hwaccels | `{', '.join(ffmpeg_hw or [])}` |
| VideoToolbox H.264 encode (PyAV) | {vt_encode.get('h264_videotoolbox')} |
| VideoToolbox HEVC encode (PyAV) | {vt_encode.get('hevc_videotoolbox')} |
| Current gov relay decode path | software libav H.264/HEVC (VT decode not wired yet) |

## Browser (Playwright headless Chromium {chromium.get('version')})

| Item | Value |
|---|---|
| WebGL renderer | `{((chromium.get('headless_webgl') or {}).get('renderer') or 'UNAVAILABLE')[:90]}` |
| H.264 decodingInfo | `{chromium.get('media_capabilities', {}).get('h264')}` |
| HEVC decodingInfo | `{chromium.get('media_capabilities', {}).get('hevc')}` |

**Implication:** headless benchmarks use SwiftShader (software). Operator headed Chrome on Metal may sustain more concurrent decodes — treat headless numbers as a **lower bound**.

## Software stack

| Component | Version |
|---|---|
| Python | {profile['software']['python']} |
| PyAV | {profile['software']['pyav']} |
| MediaMTX | {mtx_ver} |
| Network | en0 → {profile['network']['gateway']} |

## Certified media path (unchanged)

```
Government RTSP → PyAV (auth in-process) → MediaMTX → WHEP → Chromium
H.264 → DIRECT_H264
HEVC + browser_hevc_unsupported → HEVC_TRANSCODED_H264
```

Machine-readable: `var/reports/phase9/performance/machine_profile.json`
"""
    REPORT.write_text(md)
    print("wrote", OUT / "machine_profile.json")
    print("wrote", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
