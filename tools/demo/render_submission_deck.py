"""Final Gujarat Police Innovation Challenge 2026 submission deck.

Editorial 16:9 pages (WhatsApp-deck layout language) with SAAKSHYA honesty:
measured numbers from docs/MEASURED_RESULTS.md, latest workspace screenshots,
detection overlays, and the two architecture diagrams supplied for this pack.

    python tools/demo/render_submission_deck.py
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from render_demo_video import MONO, SANS, SANS_B, SEAL, _font, _text  # noqa: E402
from saakshya.common.paths import display  # noqa: E402

DEVA = lambda size: _font(  # noqa: E731
    ("Devanagari Sangam MN.ttc", "DevanagariMT.ttc",
     "ITFDevanagari.ttc", "Kohinoor.ttc"), size)

W, H = 1920, 1080
RAIL = 54
ML = 108
MR = 88
INK = (26, 26, 28)
MUTED = (110, 110, 114)
RULE = (226, 226, 222)
PAPER = (247, 247, 245)
DARK = (27, 30, 34)
DARK_2 = (18, 20, 23)
GOLD = (232, 197, 71)
GREEN = (46, 125, 79)
RED = (176, 53, 42)
WHITE = (248, 249, 251)
NAVY = (12, 33, 55)

SHOTS = ROOT / "var/demo/ui_shots_final"
DETECT = ROOT / "var/demo/detect_stills"
DIAG = ROOT / "var/demo/diagrams"


def _open(path: Path) -> Image.Image:
    if not path.exists():
        raise FileNotFoundError(path)
    return Image.open(path).convert("RGB")


def wrap(d: ImageDraw.ImageDraw, text: str, font: Any, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def fit(im: Image.Image, box: tuple[int, int], *, fill: bool = False) -> Image.Image:
    bw, bh = box
    r = max(bw / im.width, bh / im.height) if fill else min(bw / im.width, bh / im.height)
    nw, nh = max(1, int(im.width * r)), max(1, int(im.height * r))
    out = im.resize((nw, nh), Image.Resampling.LANCZOS)
    if fill and (nw != bw or nh != bh):
        x = max(0, (nw - bw) // 2)
        y = max(0, (nh - bh) // 2)
        out = out.crop((x, y, x + bw, y + bh))
    return out


def paste_c(canvas: Image.Image, im: Image.Image, box: tuple[int, int, int, int],
            *, fill: bool = False, vtrim: float = 1.0) -> None:
    if vtrim < 1:
        im = im.crop((0, 0, im.width, max(1, int(im.height * vtrim))))
    x1, y1, x2, y2 = box
    fitted = fit(im, (x2 - x1, y2 - y1), fill=fill)
    x = x1 + (x2 - x1 - fitted.width) // 2
    y = y1 + (y2 - y1 - fitted.height) // 2
    canvas.paste(fitted, (x, y))


def canvas(dark: bool = False, *, tags: tuple[str, ...] = ("VERIFIED",)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), DARK if dark else PAPER)
    img.info["truth_tags"] = tags
    return img, ImageDraw.Draw(img)


def rail(img: Image.Image, d: ImageDraw.ImageDraw, label: str, page: str,
         *, dark: bool = False) -> None:
    fill = DARK_2 if dark else (238, 238, 236)
    ink = (160, 160, 164) if dark else MUTED
    d.rectangle((0, 0, RAIL, H), fill=fill)
    d.line([(RAIL, 36), (RAIL, H - 36)],
           fill=(70, 70, 74) if dark else (210, 210, 206), width=1)
    tmp = Image.new("RGBA", (H, RAIL), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)
    _text(td, (64, 18), label.upper(), SANS(13), ink, spacing=3.2)
    rotated = tmp.rotate(90, expand=True)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.paste(rotated, (0, 0), rotated)
    composed = Image.alpha_composite(img.convert("RGBA"), overlay)
    img.paste(composed.convert("RGB"))
    d.text((14, H - 46), page, font=MONO(15), fill=ink)


def footer(d: ImageDraw.ImageDraw, text: str, *, dark: bool = False, y: int = H - 64) -> None:
    d.line([(ML, y - 18), (W - MR, y - 18)],
           fill=(58, 62, 68) if dark else RULE, width=1)
    face = SANS(17)
    fill = (168, 172, 178) if dark else MUTED
    for i, line in enumerate(wrap(d, text, face, W - ML - MR)):
        d.text((ML, y + i * 22), line, font=face, fill=fill)


def kicker(d: ImageDraw.ImageDraw, text: str, *, dark: bool = False, y: int = 56) -> None:
    fill = GOLD if dark else MUTED
    _text(d, (ML, y), text.upper(), SANS(15), fill, spacing=3.4)


def title(d: ImageDraw.ImageDraw, text: str, *, dark: bool = False, y: int = 92, size: int = 54) -> int:
    face = SANS_B(size)
    fill = WHITE if dark else INK
    yy = y
    for line in wrap(d, text, face, W - ML - MR):
        d.text((ML, yy), line, font=face, fill=fill)
        yy += int(size * 1.12)
    return yy


def shot_page(path: Path, kicker_s: str, heading: str, caption: str, page: str) -> Image.Image:
    img, d = canvas(False, tags=("DEMO",) if path.name.startswith("own_") else ("MEASURED",))
    rail(img, d, kicker_s.split()[0] if kicker_s else "WORKSPACE", page)
    kicker(d, kicker_s, y=28)
    ty = title(d, heading, y=48, size=32)
    paste_c(img, _open(path), (ML - 8, ty + 6, W - 36, H - 104))
    footer(d, caption + f" Source: var/demo/ui_shots_final/{path.name}", y=H - 76)
    return img


def two_shot(left: Path, right: Path, kicker_s: str, heading: str,
             cap_l: str, cap_r: str, foot: str, page: str, *,
             fill: bool = False, vtrim: float = 1.0) -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "WORKSPACE", page)
    kicker(d, kicker_s, y=28)
    ty = title(d, heading, y=48, size=32)
    mid = (W + ML - 36) // 2
    gap = 16
    top = ty + 8
    bot = H - 78
    paste_c(img, _open(left), (ML - 8, top, mid - gap // 2, bot - 24),
            fill=fill, vtrim=vtrim)
    paste_c(img, _open(right), (mid + gap // 2, top, W - 36, bot - 24),
            fill=fill, vtrim=vtrim)
    d.text((ML - 8, bot - 20), cap_l, font=SANS(15), fill=MUTED)
    rw = d.textlength(cap_r, font=SANS(15))
    d.text((W - 36 - rw, bot - 20), cap_r, font=SANS(15), fill=MUTED)
    footer(d, foot, y=H - 52)
    return img


def four_shot(paths: list[Path], labels: list[str], kicker_s: str,
              heading: str, foot: str, page: str) -> Image.Image:
    img, d = canvas(False, tags=('MEASURED',))
    rail(img, d, "DETECT", page)
    kicker(d, kicker_s, y=24)
    ty = title(d, heading, y=44, size=30)
    gap = 12
    left, right = ML - 8, W - 36
    top, bot = ty + 6, H - 72
    cw = (right - left - gap) // 2
    ch = (bot - top - gap) // 2
    boxes = [
        (left, top, left + cw, top + ch),
        (left + cw + gap, top, right, top + ch),
        (left, top + ch + gap, left + cw, bot),
        (left + cw + gap, top + ch + gap, right, bot),
    ]
    for path, lab, (x1, y1, x2, y2) in zip(paths, labels, boxes):
        paste_c(img, _open(path), (x1, y1, x2, y2 - 22), fill=True)
        d.text((x1, y2 - 20), lab, font=SANS(14), fill=MUTED)
    footer(d, foot, y=H - 50)
    return img


def table_page(kicker_s: str, heading: str, columns: list[str],
               rows: list[list[tuple[str, str | None]]], foot: str,
               page: str, *, dark: bool = False, col_w: list[int] | None = None,
               tags: tuple[str, ...] = ("VERIFIED",)) -> Image.Image:
    img, d = canvas(dark, tags=tags)
    rail(img, d, kicker_s.split()[0] if kicker_s else "TABLE", page, dark=dark)
    kicker(d, kicker_s, dark=dark, y=48)
    ty = title(d, heading, dark=dark, y=84, size=48)
    xs = col_w or []
    if not xs:
        usable = W - ML - MR
        xs = [ML]
        wcol = usable // max(1, len(columns))
        for i in range(1, len(columns)):
            xs.append(ML + i * wcol)
    head_y = ty + 28
    hf = SANS(14)
    head_fill = (150, 154, 160) if dark else MUTED
    for i, col in enumerate(columns):
        _text(d, (xs[i], head_y), col.upper(), hf, head_fill, spacing=2.4)
    d.line([(ML, head_y + 28), (W - MR, head_y + 28)],
           fill=(58, 62, 68) if dark else RULE, width=1)
    y = head_y + 48
    body = SANS(22)
    body_b = SANS_B(22)
    ink = WHITE if dark else INK
    for row in rows:
        rh = 0
        drawn: list[tuple[int, list[str], str, Any]] = []
        for i, cell in enumerate(row):
            text, tone = cell
            face = body_b if i == 0 else body
            width = (xs[i + 1] if i + 1 < len(xs) else W - MR) - xs[i] - 16
            lines = wrap(d, text, face, max(80, width))
            drawn.append((i, lines, tone or "", face))
            rh = max(rh, len(lines) * 28)
        for i, lines, tone, face in drawn:
            fill = ink
            if tone == "green":
                fill = (110, 190, 140) if dark else GREEN
            elif tone == "red":
                fill = (220, 110, 100) if dark else RED
            elif tone == "gold":
                fill = GOLD if dark else (146, 97, 10)
            for li, line in enumerate(lines):
                d.text((xs[i], y + li * 28), line, font=face, fill=fill)
        y += rh + 18
        d.line([(ML, y - 8), (W - MR, y - 8)],
               fill=(48, 52, 58) if dark else (236, 236, 232), width=1)
    footer(d, foot, dark=dark)
    return img


def cover() -> Image.Image:
    img, d = canvas(True, tags=('VERIFIED', 'DEMO'))
    rail(img, d, "TITLE", "01", dark=True)
    kicker(d, "Gujarat Police Innovation Challenge 2026", dark=True, y=72)
    d.ellipse((ML, 128, ML + 54, 182), outline=SEAL, width=3)
    d.text((ML + 74, 126), "SAAKSHYA", font=SANS_B(64), fill=WHITE)
    d.text((ML + 74, 198), "साक्ष्य", font=DEVA(22), fill=GOLD)
    dx = int(d.textlength("साक्ष्य", font=DEVA(22)))
    d.text((ML + 74 + dx + 16, 202), "·  EVIDENCE", font=SANS(20), fill=GOLD)
    d.text((ML, 268), "Federated CCTV Intelligence", font=SANS_B(58), fill=WHITE)
    d.text((ML, 338), "and Evidence Fabric", font=SANS_B(58), fill=WHITE)
    sub = SANS(24)
    for i, line in enumerate(wrap(d,
            "Hybrid of Models 1 + 2 + 3, with Model 4's central analytics on selected cameras. Model 4's statewide central recording is declined on arithmetic, not deferred.",
            sub, W - ML - MR)):
        d.text((ML, 430 + i * 34), line, font=sub, fill=(176, 180, 186))
    d.line([(ML, 530), (W - MR, 530)], fill=(58, 62, 68), width=1)
    kpis = [
        ("30", "GOVERNMENT", "VERIFIED BASELINE"),
        ("2", "OWN FEED", "DEMO"),
        ("18", "SYNTHETIC CONTROL", "DEMO"),
        ("50", "EVALUATION BASELINE", "VERIFIED"),
    ]
    x = ML
    for num, lab, tag in kpis:
        d.text((x, 568), num, font=SANS_B(52), fill=WHITE)
        _text(d, (x, 638), lab, SANS(13), (168, 172, 178), spacing=2.2)
        d.text((x, 662), tag, font=SANS(13), fill=GOLD)
        x += 420
    footer(d,
           "Source: src/saakshya/command/domain.py::enforce_evaluation_50. Additional operator-onboarded cameras are retained. Screenshots are dated captures, not current totals.",
           dark=True)
    return img


def framing() -> Image.Image:
    img, d = canvas(True, tags=('MEASURED', 'DEMO'))
    rail(img, d, "FRAMING", "02", dark=True)
    kicker(d, "The constraint that shapes everything", dark=True, y=64)
    ty = title(d, "“Participants will be provided with a designated vehicle registration number.”",
               dark=True, y=108, size=42)
    body = SANS(26)
    y = ty + 40
    body_w = W - ML - MR - 560
    for para in (
        "By the time that number is handed over, the vehicle has already driven past the cameras.",
        "There is no opportunity to go and look for it.",
        "The only thing that can answer is an index of every plate already read — including the ones nobody asked for yet.",
    ):
        for line in wrap(d, para, body, body_w):
            d.text((ML, y), line, font=body, fill=(196, 200, 206))
            y += 38
        y += 14
    card_t = ty + 40
    d.rounded_rectangle((W - MR - 520, card_t, W - MR, card_t + 300), radius=8,
                        outline=(58, 62, 68), width=1)
    _text(d, (W - MR - 492, card_t + 24), "WHAT WE REHEARSED", SANS(13), GOLD, spacing=2.6)
    d.text((W - MR - 492, card_t + 60), "Government grid", font=SANS_B(22), fill=WHITE)
    d.text((W - MR - 492, card_t + 92), "GJ11S7924  ·  cam06 only", font=MONO(20), fill=GOLD)
    d.text((W - MR - 492, card_t + 148), "Controlled own-feed demonstration", font=SANS_B(22), fill=WHITE)
    d.text((W - MR - 492, card_t + 180), "GJ18JX7786  ·  C-014 → C-021", font=MONO(20), fill=GOLD)
    d.text((W - MR - 492, card_t + 232), "A looping single camera is not a route.", font=SANS(16), fill=(168, 172, 178))
    footer(d,
           "Sources: var/demo/SUBMIT/06_designated_vehicle_trace_report.html; 06_own_feed_trace_report.html. Government: single-camera observation. Own feed: controlled multi-camera demonstration.",
           dark=True)
    return img


def problem() -> Image.Image:
    img, d = canvas(False, tags=('MODELLED', 'VERIFIED'))
    rail(img, d, "PROBLEM", "03")
    kicker(d, "Problem statement")
    ty = title(d, "Gujarat’s cameras are not one system", y=88, size=50)
    d.rectangle((ML, ty + 8, ML + 64, ty + 12), fill=SEAL)
    intro = SANS(22)
    y = ty + 36
    for line in wrap(d,
            "A heterogeneous camera estate installed by Home, Health, GSRTC, Panchayat and Municipal bodies for local supervision. Cameras differ in geometry, light and connectivity; plate-reading capability has to be measured.",
            intro, W - ML - MR):
        d.text((ML, y), line, font=intro, fill=INK)
        y += 32
    cards = [
        ("1", "Video cannot be centralised",
         "80,000 cameras × 2 Mbps is 160 Gbps sustained. Thirty days is ~52 PB. MODELLED arithmetic; not a load test."),
        ("2", "Capability is unknown and unequal",
         "Capability is assessed from each camera’s stream. Poor geometry and light constrain ANPR. UNKNOWN remains an explicit result."),
        ("3", "Connectivity is unreliable",
         "Outages correlate with incidents. The edge continues with the uplink down. Nothing is lost on a queue."),
    ]
    top = y + 28
    cw = (W - ML - MR - 40) // 3
    for i, (n, head, body) in enumerate(cards):
        x = ML + i * (cw + 20)
        d.rounded_rectangle((x, top, x + cw, top + 248), radius=8, outline=RULE, width=1)
        d.text((x + 24, top + 24), n, font=SANS_B(36), fill=SEAL)
        d.text((x + 24, top + 80), head, font=SANS_B(22), fill=INK)
        yy = top + 128
        for line in wrap(d, body, SANS(18), cw - 48):
            d.text((x + 24, yy), line, font=SANS(18), fill=MUTED)
            yy += 26
    footer(d, "MODELLED arithmetic: docs/HLD.md §1 and §20.9; assumes 2 Mbps per camera and 30-day central video retention.")
    return img


def hybrid() -> Image.Image:
    return table_page(
        "Proposed model, with justification",
        "Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics.",
        ["MODEL", "ROLE IN THE HYBRID", "DEMONSTRATED BY"],
        [
            [("M1 — Registry & GIS  (mandatory, kept)", None),
             ("Control plane, not a side deliverable. Identity, geometry, transport, health, measured capability.", None),
             ("Registry, GIS, governance and gap analysis. Cameras without coordinates remain listed; location provenance is retained.", None)],
            [("M2 — Unified viewing + metadata analytics", None),
             ("CONTROL ROOM: up to 30 direct WHEP tile sessions. OPTIMIZED VIEW: at most 12 sessions near the viewport.", None),
             ("Authenticated signalling proxy; browser holds no Sentinel credentials. AI workers use selected RTSP/TCP streams separately.", None)],
            [("M3 — Federation & metadata  (kept)", None),
             ("Government RTSP + local MediaMTX. Observation store is the metadata bus.", None),
             ("Search, trajectory, watchlist, alerts, evidence. Adapters, not a replacement VMS.", None)],
            [("M4 — Central analytics  (kept, selected cameras)", None),
             ("Selected streams through one controlled gateway into central analytics, events, watchlist, evidence, GIS.", None),
             ("Intelligence view. Detection, tracking, ANPR, alerts on own and selected feeds.", None)],
            [("M4 — Statewide central recording  (declined)", "red"),
             ("The transport, not the capability. Central ingest of all video refused on cost and on the Core Goal.", "red"),
             ("Not built, and not deferred. 80,000 × 2 Mbps ≈ 160 Gbps. 30-day retention ≈ 52 PB.", "red")],
        ],
        "Sources: docs/HLD.md §3; ui/app.js media-policy / TILE_WHEP_BUDGET; docs/SCALE_MODEL.md central-recording arithmetic.",
        "04",
        col_w=[ML, ML + 430, ML + 1100],
        tags=('VERIFIED', 'MODELLED'),
    )


def model4() -> Image.Image:
    b = report("bandwidth")
    return table_page(
        "Central recording  ·  arithmetic and a separate link measurement",
        "Why statewide central recording is declined",
        ["BASIS", "RESULT", "STATUS"],
        [
            [("80,000 cameras × 2 Mbps", None), ("160 Gbps sustained video ingest", None), ("MODELLED · HLD §1", "gold")],
            [("160 Gbps × 30 days ÷ 8", None), ("≈52 PB of central video", None), ("MODELLED · HLD §1", "gold")],
            [(f"Video demux from {len(b['cameras'])} cameras", None), (f"{b['video_mbps']:.3f} Mbps", None), ("MEASURED · bandwidth.json", "green")],
            [("Serialised observation row", None), (f"{b['observation_bytes_each']:,.1f} B", None), ("MEASURED · bandwidth.json", "green")],
            [("Peak stored event rate × row size", None), (f"{b['event_mbps']:.3f} Mbps · {b['ratio']:.1f}× smaller", None), ("Report comparison · bandwidth.json", "green")],
            [("Compact observation assumption", None), ("~400 B per observation", None), ("MODELLED · SCALE_MODEL.md", "gold")],
        ],
        "Sources: docs/HLD.md §1; docs/SCALE_MODEL.md; var/reports/bandwidth.json. Selected-camera Model 4 analytics remain part of the hybrid; statewide central recording is declined.",
        "07", col_w=[ML, ML + 600, ML + 1160], tags=("MEASURED", "MODELLED"),
    )

def bleed(path: Path, kicker_s: str, heading: str, caption: str, page: str) -> Image.Image:
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    rail(img, d, "DIAGRAM", page)
    paste_c(img, _open(path), (RAIL, 0, W, H - 44))
    d.rectangle((RAIL, H - 44, W, H), fill=(255, 255, 255))
    d.text((ML, H - 32), caption, font=SANS(16), fill=MUTED)
    return img


def scenario() -> Image.Image:
    return table_page(
        "Evaluation  ·  requirement to evidence",
        "Test scenario, answered",
        ["BRIEF REQUIREMENT", "WHERE TO LOOK", "EVIDENCE AND BOUNDARY"],
        [
            [
                ("~50 heterogeneous cameras onboarded", None),
                ("Cameras / registry · Live wall", None),
                (
                    (
                        "Evaluation baseline: 30 government + 2 own feeds + 18 synthetic "
                        "controls. Controls are not live government cameras; additional "
                        "onboarded cameras are retained."
                    ),
                    None,
                ),
            ],
            [
                ("Centralised monitoring + AI", None),
                ("Overview · Live wall · Intelligence", None),
                (
                    (
                        "Government RTSP / WebRTC and own feeds in one workspace; "
                        "vehicle/person boxes and plate reads. Departmental systems remain "
                        "in place."
                    ),
                    None,
                ),
            ],
            [
                ("Designated vehicle → route", None),
                ("Investigate · Trajectory legs", None),
                (
                    (
                        "Controlled own-feed GJ18JX7786: C-014 → C-021 "
                        "(fictional plate). Government GJ11S7924: cam06 only, a single-camera observation, not a "
                        "cross-camera route."
                    ),
                    None,
                ),
            ],
            [
                ("Timestamped, location-wise history", None),
                ("Vehicle trace report · 06_* reports", None),
                (
                    (
                        "Camera/location, timestamped reads, timed legs, sealed stills and "
                        "row digest. Coverage gaps stay explicit; unreliable shared clocks "
                        "are REFUSED."
                    ),
                    None,
                ),
            ],
            [
                ("Continuous watchlist cross-reference", None),
                ("Alerts · own/government films", None),
                (
                    (
                        "Each ingested sighting is matched; hit and sighting commit "
                        "together. Automated alerts show the read, priority and evidence; "
                        "repeated reads form incidents."
                    ),
                    None,
                ),
            ],
        ],
        (
            "Sources: src/saakshya/command/domain.py::enforce_evaluation_50; var/demo/SUBMIT/06_*trace_report.html. View names "
            "identify evidence; film chapter timestamps are not recorded here."
        ),
        "10",
        col_w=[ML, ML + 460, ML + 870],
        tags=('VERIFIED', 'DEMO', 'MEASURED'),
    )


def infrastructure() -> Image.Image:
    return table_page(
        "Infrastructure  ·  HLD planning assumptions",
        "Compute, bandwidth and retention",
        ["RESOURCE", "PLANNING BASIS — NOT A PROCUREMENT BENCHMARK"],
        [
            [("Regional compute", None), ("Per district: 2,500 cameras at 1 Hz, assumed S=10 over the 5.6 fps CPU sizing baseline. 45 inference units in 12 four-GPU servers; 10 ingest/decode servers. HLD §20.2–20.3.", None)],
            [("Hardware classes", None), ("Inference: 256 GB RAM per server. Decode: 64 cores / 256 GB. Database: primary + synchronous standby, 32–64 cores / 256–512 GB each. HLD §20.3; MODELLED, target GPU unmeasured.", None)],
            [("Metadata bandwidth", None), ("1,331.7 B/observation MEASURED (bandwidth.json); ~400 B MODELLED (SCALE_MODEL.md). At the measured row size: 10–20 GB/day per district gated, ≤8.9 Mbps ungated — MODELLED, HLD §20.4.", None)],
            [("Hot / warm / cold", None), ("MODELLED central metadata with indexes: ~36 TB hot for 30 days, ~438 TB warm for a year. Cold provision: 500 TB; policy sets retention. Evidence provision: 50 TB, assumed. HLD §20.5.", None)],
            [("Low connectivity", None), ("Video remains at departmental NVRs. Optional site inference ships metadata only; durable queues replay after reconnect. Viewing and evidence retrieval add traffic. HLD §20.1 / §20.4.", None)],
        ],
        "Sources: docs/HLD.md §20.1–20.5; docs/SCALE_MODEL.md; var/reports/bandwidth.json. Retention and target hardware require departmental agreement.",
        "11", col_w=[ML, ML + 410], tags=("MEASURED", "MODELLED", "DESIGNED"),
    )

def evaluation() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "EVALUATION", "38")
    kicker(d, "Judging criteria  ·  evidence index")
    title(d, "Evaluation framework, mapped", y=84, size=48)
    groups = [
        (
            "SEVEN COMMON AREAS",
            [
                (
                    "01 Government test case",
                    (
                        "Government film + ANPR CSV: camera and timestamp; no proven "
                        "multi-camera government route."
                    ),
                ),
                (
                    "02 Presentation clarity / completeness",
                    ("This deck: model, workflow, scenario, sizing, evidence and explicit limits."),
                ),
                (
                    "03 Architecture / feasibility / security",
                    "HLD diagrams + §10 adapters, §17 sizing, §18 security; SECURITY.md.",
                ),
                (
                    "04 Working platform maturity",
                    (
                        "Own-feed and government films: onboarding, viewing, search, "
                        "alerts and evidence."
                    ),
                ),
                (
                    "05 Analytics output quality",
                    (
                        "Intelligence overlays + plate CSV + trace reports. Person/vehicle "
                        "detection; FRS gated, intrusion not established by these films."
                    ),
                ),
                (
                    "06 ~80k scale / PoC readiness",
                    (
                        "05_SCALE_80K_LOAD_TEST.md + HLD §17: registry load evidence; "
                        "statewide live AI remains modelled."
                    ),
                ),
                (
                    "07 Accessible, consistent submission",
                    (
                        "FINAL_SUBMISSION.md + 00_CHECKLIST.md index docs, films and "
                        "reports; public links/access need final verification."
                    ),
                ),
            ],
        ),
        (
            "SIX BONUS AREAS",
            [
                (
                    "Hybrid architecture",
                    (
                        "Models 1 + 2 + 3 and selected-camera M4 analytics; HLD "
                        "architecture diagrams."
                    ),
                ),
                (
                    "Cross-camera vehicle tracking",
                    (
                        "Investigate + own trace report, C-014 → C-021; controlled "
                        "own-store route, not government proof."
                    ),
                ),
                (
                    "Reliable analytics beyond ANPR",
                    (
                        "Government detection overlays, person/vehicle boxes, tracking and "
                        "measured capability grades; no face identity claim."
                    ),
                ),
                (
                    "Edge / bandwidth / low connectivity",
                    (
                        "HLD §6, §12 + SCALE_MODEL: durable queue, offline replay, "
                        "metadata aggregation."
                    ),
                ),
                (
                    "Cybersecurity / privacy / audit / RBAC",
                    (
                        "SECURITY.md + Evidence and Audit views: hash chains, jurisdiction "
                        "gates, blurred heads in own film."
                    ),
                ),
                (
                    "Dashboards / alerts / health / APIs",
                    (
                        "Overview, Alerts and Cameras views; 05_* registry API and "
                        "gap-analysis material; HLD §10 adapters."
                    ),
                ),
            ],
        ),
    ]
    cw = (W - ML - MR - 48) // 2
    for col, (heading, rows) in enumerate(groups):
        x = ML + col * (cw + 48)
        _text(d, (x, 180), heading, SANS(14), MUTED, spacing=2.4)
        y = 220
        for label, evidence in rows:
            d.text((x, y), label, font=SANS_B(20), fill=INK)
            y += 29
            for line in wrap(d, evidence, SANS(18), cw):
                d.text((x, y), line, font=SANS(18), fill=MUTED)
                y += 24
            y += 18
            d.line([(x, y - 8), (x + cw, y - 8)], fill=RULE, width=1)
    footer(
        d,
        (
            "Evidence index, not a score claim. Film/report descriptions "
            "follow docs/FINAL_SUBMISSION.md; delivery links are verified at "
            "submission."
        ),
    )
    return img


def pipeline() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "PIPELINE", "09")
    kicker(d, "End-to-end workflow")
    title(d, "A vehicle passes a camera. Only metadata moves.", y=88, size=42)
    steps = [
        "Registry already knows the camera, its position, and its adapter.",
        "Stream opened — timing from the video’s own PTS, never from arrival.",
        "Motion / vehicle / person detected and tracked. Plate located inside the vehicle box.",
        "OCR on each sampled crop → per-track vote → one plate string, or no string.",
        "Sighting written always. Watchlist match, if any, commits in the same transaction.",
        "Operator sees the alert with its evidence pointers. Video stays where it is.",
        "Later, a plate is typed. Graph-first retrieval returns what the cameras actually saw.",
    ]
    y = 220
    for i, step in enumerate(steps, start=1):
        d.ellipse((ML, y + 2, ML + 28, y + 30), outline=SEAL, width=2)
        d.text((ML + 7, y + 4), str(i), font=SANS_B(16), fill=SEAL)
        d.text((ML + 44, y), step, font=SANS(22), fill=INK)
        y += 52
    d.rounded_rectangle((ML, y + 8, W - MR, y + 148), radius=8, outline=RULE, width=1)
    d.rectangle((ML, y + 8, ML + 6, y + 148), fill=SEAL)
    d.text((ML + 28, y + 28), "Two answers we will not invent", font=SANS_B(20), fill=INK)
    d.text((ML + 28, y + 64), "A face is presence, not identity. A shared timeline is REFUSED unless both cameras’ clocks are sound.",
           font=SANS(18), fill=MUTED)
    d.text((ML + 28, y + 96), "UNKNOWN is a correct grade. A guessed colour is worse than no colour.",
           font=SANS(18), fill=MUTED)
    footer(d, "Source: docs/HLD.md §4 — pipeline, graph-first retrieval and timebase checks.")
    return img


def agenda() -> Image.Image:
    return table_page(
        "Solution presentation  ·  portal checklist",
        "What this deck is required to answer",
        ["PORTAL ASKS", "THIS DECK"],
        [
            [("1. Proposed solution model, with justification", None),
             ("Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics. Central VMS recording declined on 160 Gbps / 52 PB arithmetic.", None)],
            [("2. Overview, objectives, and key innovations", None),
             ("Find → Trace → Verify → Act. Capability measured. Metadata moves. Video stays.", None)],
            [("3. High-level architecture and end-to-end workflow", None),
             ("HLD-derived architecture and component interactions, then the pipeline from camera to search.", None)],
            [("4. AI video analytics — detection, recognition, events", None),
             ("T0–T2 adaptive tiers. RT-DETRv2 + ByteTrack + voted ANPR. No face identification.", None)],
            [("5. Watchlist correlation and real-time alerts", None),
             ("Match at ingest, same transaction as the sighting. Representative watchlist, labelled.", None)],
            [("6. Key technologies, frameworks, and tools", None),
             ("PyAV, PyTorch + ONNX Runtime, FastAPI, SQLite and PostgreSQL + PostGIS, vanilla ES. Licences pinned.", None)],
            [("7. Scale, interoperability, security, deployment", None),
             ("District edge + metadata centre. Four auth gates. Continues with the uplink down.", None)],
            [("8. Operational benefits and impact on policing", None),
             ("An index answers a plate that nobody had asked for yet. Honest grades, not a fake wall.", None)],
        ],
        "Sources: docs/HLD.md; docs/SCALE_MODEL.md. Screenshots retain their capture-time state; report measurements identify their own source.",
        "02",
        col_w=[ML, ML + 820],
        tags=('VERIFIED', 'MODELLED'),
    )


def objectives() -> Image.Image:
    img, d = canvas(False, tags=('MEASURED', 'MODELLED', 'VERIFIED'))
    rail(img, d, "OBJECTIVES", "05")
    kicker(d, "Solution overview, objectives, and key innovations")
    ty = title(d, "Answer “where did this vehicle go?” without moving the video", y=84, size=36)
    d.rectangle((ML, ty + 6, ML + 64, ty + 10), fill=SEAL)
    objs = [
        ("Onboard", "One registry for a heterogeneous estate. Codec, department and capability are data, not assumptions."),
        ("Find", "An index of every plate already read — including the ones nobody had asked for yet."),
        ("Trace", "Typed legs. Clocks ALLOWED or REFUSED. A looping camera is not a journey."),
        ("Act", "A watchlist hit is a row with a camera and evidence pointers. Video stays where it is."),
    ]
    y = ty + 28
    for name, body in objs:
        d.text((ML, y), name.upper(), font=SANS(14), fill=SEAL)
        for i, line in enumerate(wrap(d, body, SANS(20), W - ML - MR - 160)):
            d.text((ML + 160, y + i * 26), line, font=SANS(20), fill=INK)
        y += 58
        d.line([(ML, y - 12), (W - MR, y - 12)], fill=(236, 236, 232), width=1)
    y += 8
    _text(d, (ML, y), "KEY INNOVATIONS", SANS(13), MUTED, spacing=2.8)
    y += 28
    innos = [
        ("Measure, never assume", "Three grades per camera per time band. UNKNOWN is a correct answer."),
        ("Metadata, not video", "1,331.7 B/observation MEASURED; ~400 B MODELLED. The measured comparison is 19.3× smaller than video."),
        ("Match in one transaction", "Watchlist hit and sighting commit together, or neither does."),
        ("Graph before appearance", "Appearance ranking is not used as the lead. Graph and timebase checks come first."),
    ]
    cw = (W - ML - MR - 28) // 2
    for i, (head, body) in enumerate(innos):
        x = ML + (i % 2) * (cw + 28)
        yy = y + (i // 2) * 110
        d.rounded_rectangle((x, yy, x + cw, yy + 96), radius=8, outline=RULE, width=1)
        d.text((x + 20, yy + 16), head, font=SANS_B(18), fill=INK)
        for j, line in enumerate(wrap(d, body, SANS(16), cw - 40)):
            d.text((x + 20, yy + 48 + j * 22), line, font=SANS(16), fill=MUTED)
    footer(d, "Sources: var/reports/bandwidth.json; docs/SCALE_MODEL.md (~400 B model). Copilot tools are read-only; src/saakshya/copilot/tools.py.")
    return img


def analytics() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "ANALYTICS", "11")
    kicker(d, "AI-powered video analytics")
    title(d, "Detection, recognition, and event analytics — adaptive by camera", y=84, size=34)
    cards = [
        ("T0  ·  presence",
         "Motion differencing per colour channel. A camera that cannot read a plate can still prove something passed."),
        ("T1  ·  detection + track",
         "RT-DETRv2 vehicles and persons. ByteTrack reimplemented for real PTS and scene cuts. Person box is presence, not identity."),
        ("T2  ·  recognition",
         "Plate found inside the vehicle box. OCR on sampled crops → per-track vote → one string, or no string. No face identification."),
        ("Events",
         "Watchlist match, motion presence, long-stay as duration (not intrusion). Priority never overrides a capability ceiling."),
    ]
    top = 240
    cw = (W - ML - MR - 28) // 2
    ch = 200
    for i, (head, body) in enumerate(cards):
        x = ML + (i % 2) * (cw + 28)
        y = top + (i // 2) * (ch + 20)
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=8, outline=RULE, width=1)
        d.rectangle((x, y, x + 6, y + ch), fill=SEAL)
        d.text((x + 28, y + 24), head, font=SANS_B(22), fill=INK)
        yy = y + 72
        for line in wrap(d, body, SANS(18), cw - 56):
            d.text((x + 28, yy), line, font=SANS(18), fill=MUTED)
            yy += 26
    footer(d, "Source: docs/HLD.md §4.2; src/saakshya/runtime/inference_scheduler.py. Priority adapts inference cadence; it does not rotate camera selection.")
    return img


def watchlist_method() -> Image.Image:
    img, d = canvas(False, tags=('VERIFIED', 'DEMO'))
    rail(img, d, "WATCHLIST", "12")
    kicker(d, "Correlation with watchlist databases and automated alerts")
    title(d, "Every plate read is checked. A hit is a row, not a toast.", y=84, size=36)
    steps = [
        ("1", "Post", "Plate, category, authority and reason. An entry with no stated authority cannot be created."),
        ("2", "Scope", "Versioned, jurisdiction-scoped, with expiry. Labelled REPRESENTATIVE — not a live government record."),
        ("3", "Match", "Ingest compares every voted plate to the active local watchlist. Continuous while cameras are open."),
        ("4", "Commit", "Alert and sighting write in the same transaction, or neither does. There is no “alert without evidence”."),
        ("5", "Alert", "OPEN, with decomposed confidence (plate × quality × category), recommended action, observation ids."),
        ("6", "Hold", "Acknowledge → investigate → clear (with a reason). No delete. Every transition is in the hash-chained audit log."),
        ("7", "Edge", "The district node keeps matching if the uplink is down. Watchlist bundles fail closed on integrity."),
    ]
    y = 220
    for n, verb, body in steps:
        d.ellipse((ML, y + 2, ML + 28, y + 30), outline=SEAL, width=2)
        d.text((ML + 7, y + 4), n, font=SANS_B(16), fill=SEAL)
        d.text((ML + 44, y), verb.upper(), font=SANS_B(18), fill=SEAL)
        for i, line in enumerate(wrap(d, body, SANS(20), W - ML - MR - 160)):
            d.text((ML + 160, y + i * 26), line, font=SANS(20), fill=INK)
        y += 52 if len(wrap(d, body, SANS(20), W - ML - MR - 160)) == 1 else 72
        d.line([(ML + 44, y - 14), (W - MR, y - 14)], fill=(236, 236, 232), width=1)
    footer(d, "var/live.db (read-only check): GJ38BH5815 = evaluation_designated, HIGH. Own-feed route: GJ18JX7786, C-014 → C-021 (controlled DEMO). Transitions: src/saakshya/watchlist/alerts.py.")
    return img


def stack() -> Image.Image:
    return table_page(
        "Key technologies, frameworks, and tools",
        "What actually runs — licences pinned in code",
        ["LAYER", "CHOICE", "WHY THIS, NOT THE ALTERNATIVE"],
        [
            [("Decode / ingest", None),
             ("PyAV (FFmpeg)", None),
             ("Only practical option that exposes real PTS. cv2.VideoCapture does not.", None)],
            [("Detection", None),
             ("RT-DETRv2-R18 · PyTorch on the GPU", None),
             ("Apache-2.0. Vehicles, persons, two-wheelers. Ultralytics refused (AGPL).", None)],
            [("Tracking", None),
             ("ByteTrack, own implementation", None),
             ("Upstream is neither PTS-aware nor scene-cut-aware. Both matter here.", None)],
            [("Recognition (ANPR)", None),
             ("YOLO-v9-t plate + Indian-trained OCR", None),
             ("Awiros-ANPR-OCR (Apache-2.0), ported to PyTorch. Per-track voting; recogniser evaluation is separate from the older films.", None)],
            [("Store", None),
             ("SQLAlchemy · SQLite and PostgreSQL 18 + PostGIS", None),
             ("Both exercised; hash chains verified in the store migration report. ST_DWithin for cameras near a point.", None)],
            [("API", None),
             ("FastAPI + Uvicorn", None),
             ("OpenAPI generated from routes. Four authorisation gates on every call.", None)],
            [("Workspace", None),
             ("Vanilla ES modules, canvas map", None),
             ("No third-party asset. Runs with no internet route. Strict CSP is enforceable.", None)],
            [("Local replica", None),
             ("MediaMTX", None),
             ("Mirrors the organiser sandbox. Own-feed demonstration store.", None)],
        ],
        "Sources: docs/HLD.md §5; var/reports/store_engines.json; var/reports/ocr_indian_eval.json. No frozen API or test counts.",
        "13",
        col_w=[ML, ML + 380, ML + 860],
    )


def scale_security() -> Image.Image:
    img, d = canvas(False, tags=('VERIFIED', 'DESIGNED'))
    rail(img, d, "DEPLOY", "14")
    kicker(d, "Scalability, interoperability, security, and deployment")
    title(d, "District edge does the work. The centre holds the index.", y=84, size=36)
    cards = [
        ("Scalability",
         "The 80,000 figure is a registry/GIS metadata load test with synthetic camera rows plus architecture sizing. Regional worker pools are DESIGNED; statewide live inference has not been tested."),
        ("Interoperability",
         "RTSP/TCP, HLS and WHEP. Mixed h264/hevc, colour and IR. Adapters, not a replacement VMS. Government grid plus local MediaMTX. ONVIF-style metadata-first onboarding. Edge bundle export for disconnected nodes."),
        ("Security",
         "Four gates: authentication, role, jurisdiction, purpose. ADMIN cannot search. AUDITOR sees cameras, not what they saw. Watchlist read is purpose-bound. Evidence and audit are hash-chained. No face identification. Stream URLs never returned to investigators."),
        ("Deployment",
         "One codebase, three profiles (DEV_CPU, CLOUD_GPU, TARGET_GPU). Edge: ingest, analytics, local store, queue, watchlist, alerts, evidence. Centre: aggregation, cross-district search, GIS, audit. Continues with the uplink down. PostgreSQL + PostGIS store migration was measured; NATS at scale is designed; the films ran on SQLite + HTTP."),
    ]
    top = 228
    cw = (W - ML - MR - 28) // 2
    ch = 268
    for i, (head, body) in enumerate(cards):
        x = ML + (i % 2) * (cw + 28)
        y = top + (i // 2) * (ch + 16)
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=8, outline=RULE, width=1)
        d.text((x + 24, y + 20), head, font=SANS_B(22), fill=INK)
        yy = y + 64
        for line in wrap(d, body, SANS(17), cw - 48):
            d.text((x + 24, yy), line, font=SANS(17), fill=MUTED)
            yy += 24
    footer(d, "Sources: docs/HLD.md §10, §12, §18, §20.6; var/reports/final/model1/registry_80000.json. Vendor adapters are contracts; deployed multi-vendor certification remains a field task.")
    return img


def benefits() -> Image.Image:
    img, d = canvas(True, tags=("DESIGNED", "MODELLED"))
    rail(img, d, "IMPACT", "15", dark=True)
    kicker(d, "Expected operational benefits and impact on policing and public safety", dark=True, y=56)
    title(d, "The shift gets an index, not another video wall", dark=True, y=92, size=40)
    cols = [
        ("For the investigating officer",
         ["Type a plate. See what cameras actually saw.",
          "Know which cameras cannot read a plate before wasting a shift.",
          "A watchlist hit names the camera and the observation.",
          "A lookalike is labelled. A looping pass is not a route."]),
        ("For the organisation",
         ["Uses cameras already installed. No 52 PB central store.",
          "Uplink loss leaves district-local detection running.",
          "Every intrusive query is purpose-bound and hash-chained.",
          "Districts keep matching when the wide-area link is down."]),
        ("For policing and public safety",
         ["A designated mark can be searched the moment it is handed over.",
          "Alerts fire where the camera already is — video does not have to move first.",
          "Honest UNSUITABLE stops false confidence on unreadable mounts.",
          "An audit trail answers who looked, at what, and why."]),
    ]
    cw = (W - ML - MR - 48) // 3
    for i, (head, pts) in enumerate(cols):
        x = ML + i * (cw + 24)
        d.text((x, 250), head, font=SANS_B(20), fill=GOLD)
        yy = 304
        for p in pts:
            d.text((x, yy), "·", font=SANS(20), fill=GOLD)
            extra = 0
            for j, line in enumerate(wrap(d, p, SANS(18), cw - 28)):
                d.text((x + 22, yy + j * 26), line, font=SANS(18), fill=WHITE)
                extra = j
            yy += 36 + extra * 26
    footer(d,
           "Source: docs/HLD.md §20.9. Operational benefits are expected; the avoided central video store is MODELLED. No statewide live-camera test is claimed.",
           dark=True)
    return img


def measured() -> Image.Image:
    load = report("camera_load")
    cluster = report("live_cluster")
    stage = cluster["stages"][0]
    return table_page(
        "Measured performance  ·  separate dated runs",
        "Decode capacity and deep inference have different limits",
        ["RUN / SOURCE", "MEASURED RESULT", "BOUNDARY"],
        [
            [("camera_load.json · " + load["generated_at"][:10], None),
             (f"{load['aggregate']['cameras_total']} requested; {load['aggregate']['cameras_streaming']} streaming and {load['aggregate']['cameras_down']} down at end", None),
             ("Controlled load run; this is not concurrent government deep inference.", None)],
            [("camera_load.json · decoder", None),
             (f"{load['aggregate']['decoder_errors']} decoder errors; {load['aggregate']['open_failures']} open failures", None),
             ("Failed streams did not all recover by the end of the run.", None)],
            [("camera_load.json · analysis", None),
             (f"{load['analysis_fps_per_process']:.1f} fps per process; {load['peak_rss_mb']:,.1f} MB peak RSS", None),
             ("This workload is separate from the device benchmark and the HLD sizing baseline.", None)],
            [("live_cluster.json · " + cluster["generated_at_utc"][:10], None),
             (f"{stage['cameras']} camera cohort; {stage['frames_analysed']:,} frames analysed / {stage['wall_seconds']:,.1f} s", None),
             ("Historical government test window. Decoded fps is not deep-inference fps.", None)],
        ],
        "Sources: var/reports/camera_load.json; var/reports/live_cluster.json. Simultaneously live camera counts are measured during a test window, never a sandbox or bridge limit.",
        "35", col_w=[ML, ML + 520, ML + 1120], tags=("MEASURED", "DEMO"),
    )

def limits() -> Image.Image:
    img, d = canvas(False, tags=('VERIFIED', 'DEMO'))
    rail(img, d, "CREDIBILITY", "22")
    kicker(d, "What we will not claim")
    title(d, "A proposal that lists only strengths cannot be checked", y=88, size=40)
    d.rectangle((ML, 210, ML + 64, 214), fill=SEAL)
    points = [
        "Prototype scope: operational deployment, evidentiary acceptance and statewide live-video scale still require validation.",
        "ANPR yield depends on camera geometry and light. A camera being viewable does not mean it is under deep inference.",
        "GJ11S7924 on cam06 is a SINGLE-CAMERA GOVERNMENT OBSERVATION; no government route is established.",
        "GJ18JX7786 on C-014 → C-021 is the CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION.",
        "Person boxes are presence. There is no face identification on government data.",
        "Own-feed footage is published with heads blurred from the person detector's boxes. A person it never found is not blurred.",
        "The GPU speed-up is measured on a laptop's integrated GPU. The target accelerator's is not quoted until it is run.",
        "Copilot is read-only. It will not enhance a still, invent a plate, or join clocks the timebase refuses.",
        "DINOv2 appearance ranking is measured unfit to lead. It is not shown as a tracker.",
        "Government-grid watchlist entries are designated evaluation marks, filed as such — never as stolen: nothing is known about those vehicles but a camera read.",
    ]
    y = 240
    for p in points:
        d.text((ML, y), "■", font=SANS(16), fill=SEAL)
        yy = y
        for i, line in enumerate(wrap(d, p, SANS(22), W - ML - MR - 28)):
            d.text((ML + 28, yy), line, font=SANS(22), fill=INK)
            yy += 30
        y = yy + 14
    footer(d, "Sources: docs/HLD.md §19; var/demo/SUBMIT/06_*trace_report.html; var/live.db watchlist (read-only check).")
    return img


def _film_meta(path: Path) -> str:
    """Length and size read off the file, so the slide cannot carry a stale take.

    This slide once described a 1:03 silent 1080p own-feed film two takes after
    it had become a narrated 1440p one.
    """
    import json
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
             "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        j = json.loads(out)
        secs = float(j["format"]["duration"])
        v = next(s for s in j["streams"] if s.get("codec_type") == "video")
        audio = any(s.get("codec_type") == "audio" for s in j["streams"])
        return (f"{int(secs) // 60}:{int(secs) % 60:02d}  ·  {v['width']}×{v['height']}"
                f"  ·  {'audio present' if audio else 'silent'}")
    except Exception:
        return "not rendered on this host"


def films() -> Image.Image:
    img, d = canvas(True, tags=('MEASURED', 'DEMO'))
    rail(img, d, "FILMS", "23", dark=True)
    kicker(d, "What to play, in this pack", dark=True, y=64)
    title(d, "Two films. One plate report. No mock-ups.", dark=True, y=108, size=44)
    cards = [
        ("own_feed.mp4  ·  controlled own feed", _film_meta(ROOT / "var/demo/own_feed.mp4"),
         "Licensed Mumbai street footage, heads blurred. A camera onboarded through the registry "
         "form; live detection on the GPU; a plate read off the footage, searched; a fictional "
         "watchlist hit; the trace report; sealed evidence; the audit log."),
        ("government_feed.mp4 + ANPR report CSV", _film_meta(ROOT / "var/demo/government_feed.mp4"),
         "The government grid: live wall, detections drawn on the frame that produced them, plate "
         "reads with timestamps. The report lists timestamped reads; its window is separate from the film duration."),
    ]
    y = 280
    for head, meta, body in cards:
        d.text((ML, y), head, font=SANS_B(26), fill=WHITE)
        d.text((ML + 720, y + 4), meta, font=MONO(18), fill=GOLD)
        yy = y + 40
        for line in wrap(d, body, SANS(20), W - ML - MR):
            d.text((ML, yy), line, font=SANS(20), fill=(176, 180, 186))
            yy += 28
        y = yy + 28
    footer(d,
           "Sources: var/demo/own_feed.mp4 and government_feed.mp4 (ffprobe at render). The existing films predate the Indian recogniser; the government film may be replaced.",
           dark=True)
    return img


def gpu_measured() -> Image.Image:
    """Historical device comparison; empty plate lists cannot establish OCR parity."""
    det, pipe = report("detector_device"), report("pipeline_device")
    return table_page(
        "Performance  ·  measured on the development laptop's GPU",
        "Measured device throughput, with the sample boundary",
        ["WHAT WAS TIMED", "CPU", "APPLE GPU (MPS)", "SPEED-UP", "SAME OUTPUT?"],
        [
            [("Detector alone, 2560×1440 frame", None),
             (f"{det['cpu']['ms_median']:.0f} ms", None), (f"{det['mps']['ms_median']:.0f} ms", "green"),
             (f"{det['speedup_median']}×", "green"),
             (f"{det['parity']['cpu_detections']:,} of {det['parity']['cpu_detections']:,} boxes at IoU ≥ 0.9"
              if det['parity']['cpu_unmatched_on_gpu'] == 0 else "no", None)],
            [("Whole pipeline: detect, track, plate, OCR", None),
             (f"{pipe['cpu']['ms_median']:.0f} ms", None), (f"{pipe['mps']['ms_median']:.0f} ms", "green"),
             (f"{pipe['speedup_median']}×", "green"),
             ("same observations (no plates in sample)" if not pipe["cpu"]["plates"] and not pipe["mps"]["plates"] and pipe["same_observation_count"]
              else "same observations and plate lists" if pipe["same_plates"] and pipe["same_observation_count"] else "outputs differ", None)],
        ],
        "Sources: var/reports/detector_device.json; pipeline_device.json. Historical integrated-GPU benchmarks; "
        "earlier OCR pipeline with plate models on CPU. Neither a target-accelerator result nor OCR accuracy parity.",
        "21b",
        col_w=[ML, ML + 640, ML + 860, ML + 1120, ML + 1320],
        tags=('MEASURED',),
    )


def close() -> Image.Image:
    img, d = canvas(True)
    rail(img, d, "CLOSE", "24", dark=True)
    d.ellipse((ML, 280, ML + 54, 334), outline=SEAL, width=3)
    d.text((ML + 74, 278), "SAAKSHYA", font=SANS_B(64), fill=WHITE)
    d.text((ML + 74, 350), "साक्ष्य", font=DEVA(22), fill=GOLD)
    dx = int(d.textlength("साक्ष्य", font=DEVA(22)))
    d.text((ML + 74 + dx + 16, 354), "·  EVIDENCE", font=SANS(20), fill=GOLD)
    d.text((ML, 430), "Find  →  Trace  →  Verify  →  Act.", font=SANS_B(36), fill=WHITE)
    d.text((ML, 500), "Analytics at the edge. Metadata to the centre.", font=SANS(26), fill=(176, 180, 186))
    d.text((ML, 548), "Video stays where it is.", font=SANS(26), fill=(176, 180, 186))
    footer(d, "Gujarat Police Innovation Challenge 2026  ·  Official · Sensitive", dark=True)
    return img



TRUTH_COLOURS = {
    "MEASURED": (27, 107, 70),
    "MODELLED": (139, 87, 8),
    "DEMO": (108, 61, 151),
    "DESIGNED": (28, 83, 143),
    "VERIFIED": (75, 82, 90),
}


def badges(d: ImageDraw.ImageDraw, labels: tuple[str, ...], x: int, y: int) -> None:
    """Same colour and literal label everywhere, including mixed-evidence pages."""
    for label in labels:
        width = int(d.textlength(label, font=SANS_B(15))) + 20
        d.rounded_rectangle((x, y, x + width, y + 22), radius=4,
                            fill=TRUTH_COLOURS[label])
        d.text((x + 10, y + 1), label, font=SANS_B(15), fill=WHITE)
        x += width + 10


def report(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "var/reports" / f"{name}.json").read_text())



def architecture() -> Image.Image:
    """HLD topology drawn locally so obsolete raster claims cannot leak in."""
    img, d = canvas(False, tags=("DESIGNED", "VERIFIED"))
    rail(img, d, "ARCHITECTURE", "08")
    kicker(d, "Overall architecture · district deployment design")
    title(d, "Regional analytics; central metadata and governance", size=44)
    blocks = [
        ("CAMERA / DEPARTMENT", "Existing estate", [
            "Cameras, NVRs and departmental VMS remain in place.",
            "RTSP / ONVIF / vendor adapters expose authorised streams and metadata.",
            "Video retention stays with the department.",
        ]),
        ("DISTRICT / REGIONAL", "Analytics and local continuity", [
            "Ingest → detect → track → ANPR on selected cameras.",
            "Local watchlist, alerts, evidence, store and durable queue.",
            "Worker pools and camera failover are deployment design.",
        ]),
        ("CENTRE + DR SITE", "Metadata services", [
            "Registry, GIS, governance and cross-district investigation.",
            "PostgreSQL / PostGIS, evidence index and hash-chained audit.",
            "Watchlist bundles return to district nodes with integrity checks.",
        ]),
    ]
    gap, cw = 95, (W - ML - MR - 190) // 3
    for i, (head, sub, paragraphs) in enumerate(blocks):
        x = ML + i * (cw + gap)
        d.rounded_rectangle((x, 248, x + cw, 708), radius=10, outline=NAVY, width=2)
        d.text((x + 24, 274), head, font=SANS_B(23), fill=NAVY)
        d.text((x + 24, 316), sub, font=SANS_B(21), fill=INK)
        y = 374
        for paragraph in paragraphs:
            for line in wrap(d, paragraph, SANS(22), cw - 48):
                d.text((x + 24, y), line, font=SANS(22), fill=INK)
                y += 30
            y += 20
        if i < 2:
            ax = x + cw + 10
            d.line((ax, 474, ax + gap - 22, 474), fill=NAVY, width=4)
            d.polygon(((ax + gap - 22, 474), (ax + gap - 36, 465), (ax + gap - 36, 483)), fill=NAVY)
    d.text((ML, 754), "Video and metadata at regional ingest; metadata to the centre. Authorised viewing pulls video on demand.", font=SANS(24), fill=INK)
    d.text((ML, 806), "Models 1 + 2 + 3 form the foundation; selected-camera Model 4 analytics are included.", font=SANS_B(24), fill=INK)
    d.text((ML, 854), "Statewide central recording is declined. Multi-node HA and DR require deployment validation.", font=SANS(24), fill=MUTED)
    footer(d, "Source: docs/HLD.md §3, §6, §10, §15, §20.1. DESIGNED topology; component contracts are VERIFIED. The current films run on a single host.")
    return img


def system_architecture() -> Image.Image:
    return table_page(
        "System architecture · component interactions",
        "Ingest → analytics → edge → store → investigation",
        ["COMPONENT", "INTERFACE / RESPONSIBILITY", "BOUNDARY"],
        [
            [("Ingest and timebase", None), ("PTS-aware frames, reconnect/backoff and discontinuity checks feed camera pipelines.", None), ("A shared timeline requires reliable clocks.", None)],
            [("Detection, tracking and ANPR", None), ("Vehicle/person boxes → track → plate crop → voted registration or no read.", None), ("Selected-camera inference; cadence adapts by priority.", None)],
            [("Local edge services", None), ("Sighting + watchlist match commit together; alerts, sealed evidence and durable queue remain local.", None), ("Uplink loss delays aggregation; local processing continues.", None)],
            [("Store and metadata exchange", None), ("Idempotent replay into observation, evidence and audit stores. SQLite locally; PostgreSQL / PostGIS at scale.", None), ("Regional event bus and worker cluster are DESIGNED.", None)],
            [("Investigation and access", None), ("Graph-first search, trajectory, GIS, incident workflow, trace report and read-only copilot.", None), ("Authentication, role, jurisdiction and purpose gates.", None)],
        ],
        "Source: docs/HLD.md §4–6, §10–11, §18, §20.6. Components are VERIFIED in the implementation; distributed deployment remains DESIGNED.",
        "09", col_w=[ML, ML + 450, ML + 1140], tags=("VERIFIED", "DESIGNED"),
    )

def media_policies() -> Image.Image:
    return table_page(
        "Government integration  ·  viewing is separate from inference",
        "Two explicit wall policies",
        ["POLICY / PLANE", "BEHAVIOUR"],
        [
            [("CONTROL ROOM · Dense 6×5", None), ("One direct WHEP session per tile, up to 30; opens staggered 400 ms apart. A tile session is viewing, not deep inference.", None)],
            [("OPTIMIZED VIEW · default", None), ("At most 12 sessions near the viewport; 600 px prefetch. Releases a session 15 s after its tile leaves the viewport.", None)],
            [("Authenticated signalling", None), ("Browser WHEP uses SAAKSHYA’s authenticated signalling proxy. Sentinel credentials stay out of the browser. Selected AI streams use RTSP/TCP separately.", None)],
            [("Shared sandbox availability", None), ("No fixed participant-facing concurrent RTSP limit. Availability varies with shared load: stagger, back off and isolate each camera. Report live counts only for their test window.", None)],
        ],
        "Sources: ui/app.js::applyMediaPolicy, TILE_WHEP_BUDGET, TILE_WHEP_STAGGER_MS, WHEP_PREFETCH_PX, WHEP_KEEPALIVE_MS; docs/SENTINEL_SANDBOX.md support clarification.",
        "18a", col_w=[ML, ML + 520], tags=("VERIFIED",),
    )


def government_designated() -> Image.Image:
    return table_page(
        "Designated vehicle  ·  separate evidence boundaries",
        "Government observation and controlled own-feed route",
        ["SOURCE", "REGISTRATION / LOCATIONS", "WHAT IT ESTABLISHES"],
        [
            [("Government trace report", None), ("GJ11S7924 · cam06", None), ("SINGLE-CAMERA GOVERNMENT OBSERVATION. Timestamped reads on one camera; no government multi-camera route established.", None)],
            [("Controlled own-feed trace report", None), ("GJ18JX7786 · C-014 → C-021", None), ("CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION. Fictional registration in the demonstration store.", None)],
            [("Representative government watchlist", None), ("GJ11S7924 / GJ38BH5815", None), ("evaluation_designated · HIGH. Read-only store verification; these entries do not assert that either vehicle is stolen.", None)],
        ],
        "Sources: var/demo/SUBMIT/06_designated_vehicle_trace_report.html; 06_own_feed_trace_report.html; var/live.db watchlist (read-only verification on 28 Sep 2026).",
        "25", col_w=[ML, ML + 460, ML + 950], tags=("MEASURED", "DEMO", "VERIFIED"),
    )


def gallery_path(value: str, directory: Path) -> Path:
    """Accept exporter paths rooted at the repo or relative to the gallery."""
    path = Path(value)
    if path.is_absolute():
        return path
    rooted = ROOT / path
    return rooted if rooted.is_file() else directory / path


def government_anpr_gallery() -> Image.Image | None:
    """Omit absent/incomplete evidence; never substitute stock or generated crops."""
    directory = ROOT / "var/demo/plate_gallery"
    try:
        selected = json.loads((directory / "selected.json").read_text())
        stats = json.loads((directory / "stats.json").read_text())
        required = {"image", "display_image", "camera", "timestamp", "plate_text",
                    "confidence", "agreeing_reads", "provenance"}
        if not isinstance(selected, list) or not selected:
            raise ValueError("selected.json must be a nonempty list")
        for row in selected:
            if not isinstance(row, dict) or not required <= row.keys():
                raise ValueError("selected.json entry lacks required fields")
            confidence = float(row["confidence"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("confidence must be a finite fraction")
        if not isinstance(stats, dict):
            raise ValueError("stats.json must be an object")
        for key in ("total_reads", "distinct_plates", "confirmed_registrations",
                    "cameras_with_reads", "window_start", "window_end", "source", "note"):
            if key not in stats:
                raise ValueError(f"stats.json lacks {key}")
        for key in ("total_reads", "distinct_plates", "confirmed_registrations"):
            if not isinstance(stats[key], int) or isinstance(stats[key], bool) or stats[key] < 0:
                raise ValueError("statistics must be nonnegative integer counts")
        cameras = stats["cameras_with_reads"]
        if not isinstance(cameras, (int, list)) or isinstance(cameras, bool):
            raise ValueError("cameras_with_reads must be a count or list")
        # Preflight every displayed crop before drawing any purported evidence.
        rows = selected[:8] if len(selected) >= 8 else selected[:6]
        images = [_open(gallery_path(row["display_image"], directory)) for row in rows]
    except (OSError, ValueError, KeyError, TypeError):
        print("WARNING: GOVERNMENT ANPR GALLERY OMITTED — missing or invalid "
              "var/demo/plate_gallery/{selected.json,stats.json,display_image} inputs.", file=sys.stderr)
        return None
    fixture = any(row["provenance"] == "RENDER_TEST_FIXTURE" for row in rows)
    img, d = canvas(True, tags=("DEMO",) if fixture else ("MEASURED",))
    rail(img, d, "GOVERNMENT ANPR", "22a", dark=True)
    kicker(d, "RENDER TEST FIXTURE — NOT SUBMISSION EVIDENCE" if fixture else "Government feed · selected measured crops", dark=True)
    title(d, "Measured government-feed ANPR evidence", dark=True, size=42)
    cameras = stats["cameras_with_reads"]
    camera_count = len(cameras) if isinstance(cameras, list) else cameras
    band = (f"{stats['total_reads']:,} total reads   ·   {stats['distinct_plates']:,} distinct plates   ·   "
            f"{stats['confirmed_registrations']:,} confirmed registrations   ·   {camera_count} cameras")
    d.text((ML, 160), band, font=SANS_B(24), fill=GOLD)
    d.text((ML, 202), f"Test window: {stats['window_start']} → {stats['window_end']}", font=SANS(20), fill=WHITE)
    d.text((ML, 240), "Selected examples below; statistics cover every government read in the stated window.", font=SANS(20), fill=WHITE)
    columns = 4 if len(rows) == 8 else 3
    gap = 22
    cw = (W - ML - MR - gap * (columns - 1)) // columns
    for i, (row, crop) in enumerate(zip(rows, images)):
        x, y = ML + i % columns * (cw + gap), 294 + i // columns * 316
        d.rounded_rectangle((x, y, x + cw, y + 296), radius=8, fill=DARK_2)
        paste_c(img, crop, (x + 12, y + 12, x + cw - 12, y + 162))
        d.text((x + 18, y + 174), str(row["plate_text"]), font=SANS_B(26), fill=WHITE)
        d.text((x + 18, y + 212), f"{row['camera']}  ·  confidence {float(row['confidence']):.1%}", font=SANS(19), fill=GOLD)
        for j, line in enumerate(wrap(d, str(row["timestamp"]), SANS(18), cw - 36)):
            d.text((x + 18, y + 242 + j * 22), line, font=SANS(18), fill=WHITE)
    footer(d, "Sources: var/demo/plate_gallery/selected.json (display_image); stats.json. "
           + str(stats["source"]) + ". " + str(stats["note"]), dark=True, y=960)
    return img


def ai_coverage() -> Image.Image:
    pipe, det = report("pipeline_device"), report("detector_device")
    cluster, load = report("live_cluster"), report("camera_load")
    stage = cluster["stages"][0]
    n = sum(row.get("frames_analysed", 0) > 0 for row in stage["per_camera"])
    basis = "live_cluster.json historical analysed cohort"
    sweep = ROOT / "var/reports/ai_concurrency_sweep.json"
    if sweep.exists():
        # No sweep schema is mandated by the export contract. Accept explicit
        # measured concurrency only; never infer it from decode session counts.
        data = json.loads(sweep.read_text())
        measured_n = data.get("deep_inference_concurrency")
        if isinstance(measured_n, int) and not isinstance(measured_n, bool) and measured_n > 0:
            n, basis = measured_n, "ai_concurrency_sweep.json deep_inference_concurrency"
        else:
            print("WARNING: AI sweep lacks explicit deep_inference_concurrency; "
                  "coverage uses the named historical live_cluster report.", file=sys.stderr)
    img, d = canvas(False, tags=("MEASURED", "MODELLED", "DESIGNED"))
    rail(img, d, "AI COVERAGE", "36a")
    kicker(d, "Measured workload · modelled hardware · designed deployment")
    title(d, "AI coverage and hardware scaling", size=46)
    coverage = (f"Every integrated camera viewable on the wall; deep inference on {n} at a time "
                "on this machine; adaptive cadence")
    yy = 170
    for line in wrap(d, coverage, SANS_B(25), W - ML - MR):
        d.text((ML, yy), line, font=SANS_B(25), fill=INK)
        yy += 34
    d.text((ML, yy + 4), f"Coverage basis: {basis}; a reported workload, not a hardware maximum or a current live census.", font=SANS(18), fill=MUTED)
    cols = [
        ("CURRENT DEMO MACHINE", "MEASURED", [
            f"{n} cameras in the named inference workload. Selected cameras are bounded by this machine’s inference throughput.",
            f"Device pipeline: {pipe['mps']['fps']:.2f} fps; {pipe['mps']['ms_median']:.1f} ms median / {pipe['mps']['ms_p95']:.1f} ms p95. pipeline_device.json.",
            f"Detector only: {det['mps']['fps']:.1f} fps; {det['mps']['ms_median']:.1f} ms median. detector_device.json.",
            f"Decode/load: {load['aggregate']['cameras_streaming']}/{load['aggregate']['cameras_total']} streaming at end. camera_load.json. Separate workload.",
            "Historical reports; earlier OCR pipeline. New recogniser and target hardware require a fresh benchmark.",
        ]),
        ("REGIONAL GPU POOL", "MODELLED", [
            "SIZED: 2,500 cameras at 1 Hz; 5.6 fps CPU sizing baseline. S=10 speedup ASSUMED, not measured on target GPUs.",
            "45 inference units / district; 12 servers with four GPUs each. 33 districts → 1,485 units / 396 servers.",
            "Decode is sized separately. Benchmark tendered hardware, including OCR and memory, before procurement.",
            "docs/HLD.md §20.2–20.3; docs/SCALE_MODEL.md. Planning input differs from the device workload at left.",
        ]),
        ("STATEWIDE", "DESIGNED", [
            "Regional ingest; horizontal worker pools; metadata event bus and district-local queues.",
            "AdaptiveInferenceScheduler changes cadence by priority: NORMAL / HIGH_PRIORITY / ALERT / FORENSIC.",
            "Camera assignment and failover across a worker cluster require deployment validation. No camera-rotation claim.",
            "The 80,000 figure is a registry/GIS metadata load test with synthetic camera rows plus architecture sizing.",
        ]),
    ]
    cw = (W - ML - MR - 40) // 3
    for i, (heading, tag, paragraphs) in enumerate(cols):
        x, y = ML + i * (cw + 20), 296
        d.rounded_rectangle((x, y, x + cw, 953), radius=8, outline=TRUTH_COLOURS[tag], width=2)
        d.text((x + 20, y + 20), heading, font=SANS_B(21), fill=INK)
        badges(d, (tag,), x + 20, y + 60)
        yy = y + 104
        for paragraph in paragraphs:
            for line in wrap(d, paragraph, SANS(20), cw - 40):
                d.text((x + 20, yy), line, font=SANS(20), fill=INK)
                yy += 27
            yy += 16
    footer(d, "Sources: var/reports/{live_cluster,pipeline_device,detector_device,camera_load}.json; docs/HLD.md §20; src/saakshya/runtime/inference_scheduler.py.", y=991)
    return img


def cost_benefit() -> Image.Image:
    return table_page(
        "MODELLED cost  ·  assumed unit rates and accelerator speedup",
        "Indicative cost and avoided central-video spend",
        ["SCOPE", "IMPLEMENTATION", "ANNUAL OPERATIONS"],
        [
            [("PoC · approximately 50 cameras", None), ("INR 29–63 lakh", None), ("INR 18–50 lakh", None)],
            [("District · 2,500 cameras", None), ("INR 5.8–13.1 crore", None), ("INR 0.96–2.5 crore", None)],
            [("Statewide · 33 districts + centre", None), ("INR 197–443 crore", None), ("INR 34–86 crore", None)],
            [("Avoided central video storage", None), ("INR 52–156 crore · disks only", None), ("52 PB; one copy, before DR / replication", None)],
            [("Avoided central video transport", None), ("160 Gbps continuous ingest", None), ("INR 58–154 crore / year", None)],
            [("Operational benefit", None), ("Searchable history, incident grouping, sealed evidence", None), ("Investigation time savings remain estimates; measure in the district pilot.", None)],
        ],
        "Source: docs/HLD.md §20.8–20.9. MODELLED on ASSUMED S=10 and unit prices, before taxes; not vendor quotes or a measured saving. Existing departmental VMS spend continues.",
        "11b", col_w=[ML, ML + 580, ML + 1130], tags=("MODELLED",),
    )


def resilience_rollout() -> Image.Image:
    return table_page(
        "Deployment path  ·  cybersecurity and DR",
        "District pilot, regional rollout, metadata centre",
        ["DESIGN / PHASE", "TARGET AND VALIDATION"],
        [
            [("Cybersecurity", None), ("Segment camera, analytics, data and operator zones. TLS in transit; encrypted stores and backups; keys held apart. RBAC, jurisdiction and purpose gates; audit exported for review. HLD §18.", None)],
            [("District continuity", None), ("Watchlist, evidence and queues continue locally during uplink loss. District metadata targets: RPO ≤5 min, RTO ≤8 h. Assumed targets; restore/replay must be drilled. HLD §20.7.", None)],
            [("Central HA and DR", None), ("Synchronous standby, asynchronous DR replica, nightly base backups and continuous WAL. DR targets: RPO ≤15 min, RTO ≤4 h. Multi-node failover remains untested. HLD §20.7.", None)],
            [("Pilot → district → state", None), ("Survey cameras, obtain authoritative catalogue and watchlist authority, benchmark target GPU; then district integration and phased expansion. Central services aggregate metadata. HLD §13–16.", None)],
            [("Operations and acceptance", None), ("Health/readiness probes, metrics, structured logs and hash-chained audit exist. Deployment adds load balancing, log retention, alerts, camera assignment and failover. HLD §20.6.", None)],
        ],
        "Sources: docs/HLD.md §13–16, §18, §20.6–20.7. RPO/RTO are ASSUMED design targets, not measured recovery results. Government watchlist and identity integrations require authority and access.",
        "11c", col_w=[ML, ML + 430], tags=("DESIGNED", "VERIFIED"),
    )

def build() -> list[Image.Image]:
    gallery = government_anpr_gallery()
    pages = [
        cover(),
        agenda(),
        framing(),
        problem(),
        objectives(),
        hybrid(),
        model4(),
        architecture(),
        system_architecture(),
        scenario(),
        infrastructure(),
        cost_benefit(),
        resilience_rollout(),
        pipeline(),
        analytics(),
        watchlist_method(),
        stack(),
        scale_security(),
        benefits(),
        shot_page(SHOTS / "gov_overview.png",
                  "Workspace  ·  government grid  ·  24 Sep 2026",
                  "Overview is the shift picture, not a video wall",
                  "Historical workspace capture. Registry, frame availability and alert totals belong to this capture only; they are not current test results.",
                  "17"),
        media_policies(),
        shot_page(SHOTS / "gov_live_grid.png",
                  "Live wall  ·  Model 2  ·  a frame of the government film",
                  "Wall viewing and AI coverage are separate",
                  "CONTROL ROOM up to 30 WHEP sessions; OPTIMIZED VIEW ≤12. Policies: ui/app.js. Live availability varies by test window; preview tiles show analysed stills.",
                  "18"),
        shot_page(SHOTS / "gov_live_twoup_boxes.jpg",
                  "Live  ·  two-up with detections",
                  "Detection overlays accompany the wall",
                  "Person and vehicle boxes show presence on analysed frames. Overlay coverage is separate from live viewing availability.",
                  "19"),
        four_shot(
            [DETECT / "gov_overlay_t32.jpg", DETECT / "gov_overlay_t52.jpg",
             DETECT / "gov_overlay_t64.jpg", DETECT / "gov_overlay_t76.jpg"],
            ["cam02 Janpath",
             "cam04 Paldi Circle  ·  bus, cars, people",
             "cam05 Visat teen Rasta",
             "cam12 Adalaj toll"],
            "Analytics overlay  ·  government clips",
            "Detection is drawn on the frame that produced it",
            "Source: var/demo/detect_stills/gov_overlay_t*.jpg. Historical government detections; these selected frames do not establish plate-reading accuracy.",
            "20"),
        *([gallery] if gallery is not None else []),
        shot_page(SHOTS / "own_intel.png",
                  "Own feed  ·  controlled demonstration",
                  "Every box is this platform's pipeline, on that exact frame",
                  "Heads blurred from the person detector's boxes — no face detector exists. Live AI plane figures are measured, on the GPU.",
                  "16"),
        shot_page(SHOTS / "own_find.png",
                  "Investigate  ·  designated vehicle (fictional plate)",
                  "GJ18JX7786: on the watchlist, said first. Then where it went.",
                  "CONTROLLED OWN-FEED MULTI-CAMERA DEMONSTRATION: C-014 → C-021. Single-frame reads remain leads to verify. No government multi-camera route is claimed.",
                  "17"),
        government_designated(),
        shot_page(SHOTS / "gov_find_lookalike.jpg",
                  "Investigate  ·  lookalike, not a match",
                  "6J1VV0119 is an OCR lookalike of GJ1VV0119",
                  "Historical lookalike example, separate from the designated vehicle. The platform does not infer another camera or a route from OCR similarity.",
                  "19"),
        shot_page(SHOTS / "gov_alerts_film.jpg",
                  "Watchlist  ·  government grid",
                  "Government evaluation marks, grouped into incidents",
                  "Designated vehicles of interest (evaluation), filed as such and never as stolen. The read beside the listed plate, the sealed still, single-frame reads flagged to verify.",
                  "20"),
        shot_page(SHOTS / "own_alerts.png",
                  "Watchlist  ·  one decision per vehicle",
                  "Repeated reads are grouped into a vehicle incident",
                  "The read beside the listed plate, character by character; first and last sighting from the reads themselves. Fictional plates only: no real vehicle is put on a watchlist for a demonstration.",
                  "20b"),
        shot_page(SHOTS / "own_trace_report.png",
                  "Investigate  ·  vehicle trace report",
                  "The route leaves the screen as a page an officer can sign",
                  "Every read, each leg timed and checked for an impossible speed, sealed stills re-hashed, case and purpose, a digest over the rows.",
                  "20c"),
        shot_page(SHOTS / "own_evidence.png",
                  "Evidence  ·  hash-chained records",
                  "What each sealed record is, and the link that binds it",
                  "Camera, capture time, still sealed or not, and the previous record's hash. Out-of-jurisdiction content is withheld; integrity is not.",
                  "20d"),
        shot_page(SHOTS / "gov_cameras_film.jpg",
                  "Capability  ·  measured per camera",
                  "Capability grades belong to each camera and capture window",
                  "Grades are computed from each camera’s own stream. UNKNOWN means there is not yet enough evidence to grade.",
                  "21"),
        shot_page(SHOTS / "gov_map_film.jpg",
                  "Model 1  ·  estate map",
                  "Available coordinates on the map; missing coordinates stay listed",
                  "Markers show camera health. Missing coordinates stay in the registry strip; positions derived from camera names retain their provenance.",
                  "23"),
        shot_page(SHOTS / "gov_copilot_refuse.jpg",
                  "Copilot  ·  read-only tools",
                  "It will not enhance a still — that would be fabricated evidence",
                  "refuse_imagery. Detection and ANPR stay on this host. No language model is allowed to invent a plate.",
                  "24"),
        shot_page(SHOTS / "gov_copilot_timebase.jpg",
                  "Copilot  ·  timebase",
                  "cam01 and cam21 may not share a timeline",
                  "REFUSED: cam21 has unreliable timing (PTS regression). Clocks are not joined by narrative.",
                  "25"),
        measured(),
        gpu_measured(),
        ai_coverage(),
        limits(),
        films(),
        evaluation(),
        close(),
    ]
    # Renumber rails after build — close is last; copilot used 21a. Fix page labels
    # by redrawing is painful; stamp sequential numbers on the rail instead.
    labelled: list[Image.Image] = []
    total = len(pages)
    for i, page in enumerate(pages, start=1):
        d = ImageDraw.Draw(page)
        d.rectangle((8, H - 50, RAIL - 4, H - 18), fill=DARK_2 if page.getpixel((60, 40))[0] < 80 else (238, 238, 236))
        ink = (160, 160, 164) if page.getpixel((60, 40))[0] < 80 else MUTED
        d.text((14, H - 46), f"{i:02d}", font=MONO(15), fill=ink)
        labels = page.info.get("truth_tags", ("DESIGNED",))
        d.rectangle((ML, H - 23, W - MR, H), fill=DARK if page.getpixel((60, 40))[0] < 80 else PAPER)
        badges(d, labels, ML, H - 23)
        labelled.append(page)
    print(f"  composed {total} pages")
    return labelled


def write_pptx(pngs: list[Path], out: Path) -> None:
    from pptx import Presentation
    from pptx.util import Emu, Inches
    prs = Presentation()
    prs.slide_width = Inches(13.333333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    w, h = prs.slide_width, prs.slide_height
    for png in pngs:
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(str(png), Emu(0), Emu(0), width=w, height=h)
    out.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="var/demo/SAAKSHYA_deck.pdf")
    a = ap.parse_args()
    pages = build()
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    png_dir = out.with_suffix("")
    png_dir.mkdir(exist_ok=True)
    # A shorter deck used to leave the extra slides of a longer one behind, so
    # the directory held pages that were not in the PDF and looked just as
    # current. Clear our own output before writing it.
    for stale in png_dir.glob("slide_*.png"):
        stale.unlink()
    pngs: list[Path] = []
    for i, p in enumerate(pages):
        dest = png_dir / f"slide_{i:02d}.png"
        p.save(dest, "PNG")
        pngs.append(dest)
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        import fitz  # type: ignore
    doc = fitz.open()
    for p in pages:
        buf = io.BytesIO()
        p.save(buf, format="JPEG", quality=95, optimize=True)
        page = doc.new_page(width=1920, height=1080)
        page.insert_image(fitz.Rect(0, 0, 1920, 1080), stream=buf.getvalue())
    doc.save(str(out), deflate=True, garbage=4)
    doc.close()
    pptx = out.with_suffix(".pptx")
    write_pptx(pngs, pptx)
    print(f"pdf  : {display(out)} ({len(pages)} pages, {out.stat().st_size/1e6:.1f} MB)")
    print(f"pptx : {display(pptx)} ({pptx.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
