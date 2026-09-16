#!/usr/bin/env python3
"""Measure one WHEP camera in a real browser.

This is deliberately browser-facing: it performs the SDP POST, ICE connection,
media decode, screenshot, and WebRTC statistics collection. It does not accept
or persist upstream credentials. The endpoint must already be a safe gateway
URL, not a credential-bearing RTSP URL.
"""
from __future__ import annotations

import argparse
import base64
import json
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

PAGE = """<!doctype html><video id="video" autoplay muted playsinline
style="width:1280px;height:720px;background:#000"></video>"""


def _origin_root(endpoint: str) -> str:
    """Same-origin document root for the WHEP host (avoids null-origin CORS)."""
    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        return "about:blank"
    return f"{parsed.scheme}://{parsed.netloc}/"


def _safe_sdp(sdp: str) -> str:
    """Keep codec/format lines while removing ICE and host identity material."""
    lines = []
    for line in sdp.splitlines():
        if line.startswith(("a=ice-", "a=fingerprint:", "a=candidate:",
                            "o=")):
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    """Compact soak metrics from inbound-rtp samples (no secrets)."""
    first = None
    last = None
    peak_fps = None
    for sample in result.get("stats") or []:
        for report in sample.get("reports") or []:
            if report.get("type") != "inbound-rtp" or report.get("kind") != "video":
                continue
            row = {
                "at": sample.get("at"),
                "framesDecoded": report.get("framesDecoded"),
                "framesDropped": report.get("framesDropped"),
                "packetsReceived": report.get("packetsReceived"),
                "packetsLost": report.get("packetsLost"),
                "fps": report.get("framesPerSecond"),
            }
            if first is None:
                first = row
            last = row
            if row["fps"]:
                peak_fps = max(peak_fps or 0, row["fps"])
    video = result.get("video") or {}
    soak = result.get("soak") or {}
    decoded_delta = None
    if first and last and first.get("framesDecoded") is not None \
            and last.get("framesDecoded") is not None:
        decoded_delta = last["framesDecoded"] - first["framesDecoded"]
    return {
        "first_frame_ms": result.get("first_frame_ms"),
        "negotiation_ms": result.get("negotiation_ms"),
        "currentTime": video.get("currentTime"),
        "resolution": (
            f"{video.get('width')}x{video.get('height')}"
            if video.get("width") and video.get("height") else None
        ),
        "canvasMeanLuma": video.get("canvasMeanLuma"),
        "framesDecoded_delta": decoded_delta,
        "framesDropped_end": (last or {}).get("framesDropped"),
        "packetsLost_end": (last or {}).get("packetsLost"),
        "packetsReceived_end": (last or {}).get("packetsReceived"),
        "peak_fps": peak_fps,
        "freezes": soak.get("freezes"),
        "reconnects": soak.get("reconnects"),
        "ice_state": result.get("ice_state"),
    }


def measure(endpoint: str, *, seconds: float, screenshot: Path | None) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "endpoint": endpoint,
        "status": "UNAVAILABLE",
        "negotiation_ms": None,
        "ice_state": None,
        "first_frame_ms": None,
        "video": {},
        "stats": {},
        "sdp": {},
        "events": [],
        "error": None,
    }
    if "@" in endpoint:
        result["error"] = "credential-bearing endpoint is refused"
        return result
    with sync_playwright() as playwright:
        try:
            # Local certification only. Production UI uses the same-origin
            # /cameras/<id>/whep signaling proxy and never needs this flag.
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-web-security",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--allow-running-insecure-content",
                ],
            )
        except Exception as exc:
            result["error"] = f"browser unavailable: {type(exc).__name__}"
            return result
        page = browser.new_page()
        page.set_content(PAGE, wait_until="domcontentloaded")
        try:
            state = page.evaluate(
                """async ({endpoint, seconds}) => {
                  const video = document.querySelector("#video");
                  const pc = new RTCPeerConnection();
                  pc.addTransceiver("video", {direction: "recvonly"});
                  const state = {started: performance.now(), first: null,
                    negotiation: null, ice: null, dtls: null, stats: [],
                    events: [], offer: "", answer: ""};
                  video.srcObject = new MediaStream();
                  for (const name of ["loadedmetadata", "loadeddata", "canplay",
                    "playing", "waiting", "stalled", "error"]) {
                    video.addEventListener(name, () => state.events.push({
                      type: name, at: performance.now() - state.started}));
                  }
                  pc.ontrack = event => {
                    state.events.push({type: "track", at: performance.now() - state.started,
                      kind: event.track.kind, streams: event.streams.length});
                    video.srcObject.addTrack(event.track);
                  };
                  const offer = await pc.createOffer();
                  await pc.setLocalDescription(offer);
                  state.offer = pc.localDescription.sdp;
                  await new Promise(resolve => {
                    const timeout = setTimeout(resolve, 5000);
                    if (pc.iceGatheringState === "complete") resolve();
                    else pc.addEventListener("icegatheringstatechange", () => {
                      if (pc.iceGatheringState === "complete") {
                        clearTimeout(timeout); resolve();
                      }
                    });
                  });
                  const response = await fetch(endpoint, {
                    method: "POST", headers: {"Content-Type": "application/sdp",
                    "Accept": "application/sdp"}, body: pc.localDescription.sdp,
                    signal: AbortSignal.timeout(15000)
                  });
                  if (!response.ok) throw new Error(`WHEP ${response.status}`);
                  state.answer = await response.text();
                  await pc.setRemoteDescription({type: "answer", sdp: state.answer});
                  state.negotiation = performance.now() - state.started;
                  await video.play().catch(error => state.events.push({
                    type: "play-error", message: error.name}));
                  const deadline = performance.now() + seconds * 1000;
                  let lastTime = 0, stallMs = 0, freezes = 0, inStall = false;
                  let lastIce = pc.iceConnectionState, reconnects = 0;
                  while (performance.now() < deadline) {
                    if (state.first === null && video.readyState >= 2 &&
                        video.videoWidth > 0) state.first = performance.now() - state.started;
                    state.ice = pc.iceConnectionState;
                    state.dtls = pc.connectionState;
                    if (state.ice !== lastIce) {
                      if (["disconnected", "failed", "closed"].includes(lastIce)
                          && state.ice === "connected") reconnects += 1;
                      lastIce = state.ice;
                    }
                    const t = video.currentTime || 0;
                    if (state.first !== null) {
                      if (t <= lastTime + 0.01) {
                        stallMs += 500;
                        if (!inStall && stallMs >= 1500) { freezes += 1; inStall = true; }
                      } else {
                        stallMs = 0; inStall = false; lastTime = t;
                      }
                    }
                    const reports = [];
                    for (const report of (await pc.getStats()).values()) {
                      if (report.type === "inbound-rtp" || report.type === "codec" ||
                          report.type === "candidate-pair" || report.type === "transport") {
                        const keep = ["type", "kind", "mediaType", "mimeType",
                          "packetsReceived", "bytesReceived", "framesReceived",
                          "framesDecoded", "framesDropped", "framesPerSecond",
                          "codecId", "jitter", "jitterBufferDelay", "packetsLost",
                          "state", "dtlsState", "selectedCandidatePairId"];
                        const item = {};
                        for (const key of keep)
                          if (report[key] !== undefined) item[key] = report[key];
                        reports.push(item);
                      }
                    }
                    state.stats.push({at: performance.now() - state.started,
                      ice: state.ice, currentTime: t, reports});
                    await new Promise(resolve => setTimeout(resolve, 500));
                  }
                  state.soak = {freezes, reconnects, stallMs};
                  state.video = {readyState: video.readyState,
                    width: video.videoWidth, height: video.videoHeight,
                    paused: video.paused, currentTime: video.currentTime};
                  // Avoid hang/throw when the track never produced pixels.
                  if (video.videoWidth > 0 && video.videoHeight > 0) {
                    const canvas = document.createElement("canvas");
                    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
                    const context = canvas.getContext("2d");
                    context.drawImage(video, 0, 0);
                    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
                    let sum = 0;
                    for (let i = 0; i < pixels.length; i += 4)
                      sum += (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3;
                    state.video.canvasMeanLuma = sum / (pixels.length / 4);
                    // Headless Chromium compositor screenshots are often black
                    // even when the video element has pixels; persist the canvas.
                    state.video.canvasPngDataUrl = canvas.toDataURL("image/png");
                  } else {
                    state.video.canvasMeanLuma = null;
                  }
                  pc.close();
                  return state;
                }""",
                {"endpoint": endpoint, "seconds": seconds},
            )
            result["negotiation_ms"] = state.get("negotiation")
            result["first_frame_ms"] = state.get("first")
            result["ice_state"] = state.get("ice")
            result["video"] = state.get("video", {})
            result["stats"] = state.get("stats", [])
            result["events"] = state.get("events", [])
            result["soak"] = state.get("soak", {})
            result["sdp"] = {"offer": _safe_sdp(state.get("offer", "")),
                             "answer": _safe_sdp(state.get("answer", ""))}
            result["summary"] = _summarize(result)
            result["status"] = "MEASURED" if result["first_frame_ms"] is not None else "NO_FRAME"
            canvas_url = (result.get("video") or {}).pop("canvasPngDataUrl", None)
            if screenshot and canvas_url and canvas_url.startswith("data:image/png;base64,"):
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(base64.b64decode(canvas_url.split(",", 1)[1]))
                result["video"]["canvasPng"] = str(screenshot)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        finally:
            if screenshot and not (result.get("video") or {}).get("canvasPng"):
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                with suppress(Exception):
                    page.screenshot(path=str(screenshot))
            browser.close()
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="safe HTTP(S) WHEP endpoint")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = measure(args.endpoint, seconds=args.seconds, screenshot=args.screenshot)
    text = json.dumps(report, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text)
    print(text, end="")
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
