#!/usr/bin/env python3
"""Prove browser GPU / hardware video decode path on this machine.

Compares headless (SwiftShader) vs headed (Metal) Chromium launches.
Does not invent GPU support — reports MediaCapabilities + WebGL renderer.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var/reports/phase9/performance"


PROBE_JS = """
async () => {
  const out = {
    userAgent: navigator.userAgent,
    webgl: null,
    webgpu: null,
    media: {},
    videoDecoder: typeof VideoDecoder !== 'undefined',
    hardwareConcurrency: navigator.hardwareConcurrency,
  };
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl', {powerPreference: 'high-performance'})
             || c.getContext('experimental-webgl');
    if (gl) {
      const d = gl.getExtension('WEBGL_debug_renderer_info');
      out.webgl = {
        vendor: gl.getParameter(d ? d.UNMASKED_VENDOR_WEBGL : gl.VENDOR),
        renderer: gl.getParameter(d ? d.UNMASKED_RENDERER_WEBGL : gl.RENDERER),
      };
    }
  } catch (e) { out.webgl = {error: String(e)}; }
  try {
    if (navigator.gpu) {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) {
        let info = null;
        try { info = adapter.info || null; } catch (_) {}
        out.webgpu = {
          vendor: info?.vendor || null,
          architecture: info?.architecture || null,
          description: info?.description || null,
        };
      } else {
        out.webgpu = null;
      }
    }
  } catch (e) { out.webgpu = {error: String(e)}; }
  if (navigator.mediaCapabilities) {
    for (const [k, ct, fps] of [
      ['h264_1080p30', 'video/mp4; codecs=\"avc1.42E01E\"', 30],
      ['h264_1080p60', 'video/mp4; codecs=\"avc1.640028\"', 60],
      ['hevc_1080p30', 'video/mp4; codecs=\"hvc1.1.6.L93.B0\"', 30],
    ]) {
      try {
        const r = await navigator.mediaCapabilities.decodingInfo({
          type: 'file',
          video: {contentType: ct, width: 1920, height: 1080,
                  bitrate: 5000000, framerate: fps},
        });
        out.media[k] = {
          supported: r.supported, smooth: r.smooth,
          powerEfficient: r.powerEfficient,
        };
      } catch (e) { out.media[k] = {error: String(e)}; }
    }
  }
  return out;
}
"""


def launch_probe(*, headed: bool) -> dict:
    args = ["--autoplay-policy=no-user-gesture-required"]
    if headed:
        args.extend([
            "--use-angle=metal",
            "--enable-features=PlatformHEVCDecoderSupport",
        ])
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed, args=args)
        page = browser.new_page()
        info = page.evaluate(PROBE_JS)
        version = browser.version
        browser.close()
    renderer = ((info.get("webgl") or {}).get("renderer") or "")
    metal = "Metal" in renderer and "SwiftShader" not in renderer
    h264 = (info.get("media") or {}).get("h264_1080p30") or {}
    return {
        "mode": "headed" if headed else "headless",
        "chromium_version": version,
        "label": "MEASURED",
        "webgl_renderer": renderer,
        "metal_active": metal,
        "swiftshader": "SwiftShader" in renderer,
        "h264_powerEfficient": h264.get("powerEfficient"),
        "h264_smooth": h264.get("smooth"),
        "hevc_powerEfficient": ((info.get("media") or {})
                                .get("hevc_1080p30") or {}).get("powerEfficient"),
        "info": info,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-headed", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    headless = launch_probe(headed=False)
    headed = None if args.skip_headed else launch_probe(headed=True)

    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "command": "python tools/perf_browser_gpu_probe.py",
        "machine": "Apple M5",
        "headless": headless,
        "headed": headed,
        "verdict": {
            "headless_usable_for_perf": False,
            "headed_metal_proven": bool(headed and headed.get("metal_active")),
            "use_for_wall_benchmarks": "headed" if headed and headed.get("metal_active")
            else "UNAVAILABLE",
            "note": (
                "Headless SwiftShader is NOT the product ceiling. "
                "Headed Metal + powerEfficient=true is required for scale tests."
            ),
        },
    }
    (OUT / "browser_gpu_profile.json").write_text(json.dumps(payload, indent=2) + "\n")

    md_lines = [
        "# Headed browser GPU profile",
        "",
        f"Timestamp UTC: `{payload['timestamp_utc']}`",
        "",
        "## Headless vs headed (MEASURED)",
        "",
        "| Mode | WebGL renderer | Metal | H.264 powerEfficient | HEVC powerEfficient |",
        "|---|---|---|---|---|",
        f"| headless | `{headless['webgl_renderer'][:70]}` | {headless['metal_active']} | "
        f"{headless['h264_powerEfficient']} | {headless.get('hevc_powerEfficient')} |",
    ]
    if headed:
        md_lines.append(
            f"| **headed** | `{headed['webgl_renderer'][:70]}` | "
            f"**{headed['metal_active']}** | **{headed['h264_powerEfficient']}** | "
            f"**{headed.get('hevc_powerEfficient')}** |"
        )
    md_lines.extend([
        "",
        "## Verdict",
        "",
        f"- Headed Metal proven: **{payload['verdict']['headed_metal_proven']}**",
        "- 4-stream SwiftShader result is a **harness lower bound**, not the machine limit.",
        "- Wall performance benchmarks MUST use headed Chromium.",
        "",
        "Machine-readable: `var/reports/phase9/performance/browser_gpu_profile.json`",
        "",
    ])
    (ROOT / "reports/HEADED_BROWSER_GPU_PROFILE.md").write_text("\n".join(md_lines))
    (ROOT / "reports/BROWSER_HARDWARE_ACCELERATION.md").write_text("\n".join(md_lines))
    print(json.dumps(payload["verdict"], indent=2))
    return 0 if (headed and headed.get("metal_active")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
