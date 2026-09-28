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

SYNTHETIC_ROUTE = (
    "SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage"
)
# Capture dates verified against the supplied assets and film take. Keep these
# explicit: filesystem mtimes change when historical images are copied.
SHOT_DATES = {
    "gov_live_grid.png": "28 Sep 2026",
    "gov_live_dense_2026-09-28.png": "28 Sep 2026",
    "own_intel.png": "24 Sep 2026",
    "own_find.png": "24 Sep 2026",
    "gov_find_lookalike.jpg": "15 Sep 2026",
    "gov_alerts_film.jpg": "24 Sep 2026",
    "own_alerts.png": "24 Sep 2026",
    "own_trace_report.png": "24 Sep 2026",
    "own_evidence.png": "24 Sep 2026",
    "gov_cameras_film.jpg": "28 Sep 2026",
    "gov_map_film.jpg": "28 Sep 2026",
    "gov_copilot_refuse.jpg": "15 Sep 2026",
    "gov_copilot_timebase.jpg": "15 Sep 2026",
}


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
    paste_c(img, _open(path), (ML - 8, ty + 6, W - 36, H - 146))
    dated = f"Historical capture: {SHOT_DATES[path.name]}. "
    footer(d, dated + caption + f" Source: var/demo/ui_shots_final/{path.name}", y=H - 120)
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
        ("18", "CONTROL SLOTS", "REGISTRY ONLY · NO VIDEO"),
        ("50", "REGISTRY BASELINE", "32 VIDEO SOURCES + 18 SLOTS"),
    ]
    x = ML
    for num, lab, tag in kpis:
        d.text((x, 568), num, font=SANS_B(52), fill=WHITE)
        _text(d, (x, 638), lab, SANS(13), (168, 172, 178), spacing=2.2)
        d.text((x, 662), tag, font=SANS(13), fill=GOLD)
        x += 420
    d.text((ML, 742), "30 government + 2 own feeds with video; 18 control slots are registry rows without video.",
           font=SANS(25), fill=WHITE)
    footer(d,
           "Source: src/saakshya/command/domain.py::enforce_evaluation_50; var/live.db cameras (28 Sep 2026). Additional operator-onboarded cameras are retained. Screenshots are dated captures, not current totals.",
           dark=True)
    return img


def framing() -> Image.Image:
    img, d = canvas(True, tags=('VERIFIED', 'DEMO'))
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
    d.text((W - MR - 492, card_t + 148), "Synthetic rendered test corpus", font=SANS_B(22), fill=WHITE)
    d.text((W - MR - 492, card_t + 180), "GJ18JX7786  ·  C-014 → C-021", font=MONO(20), fill=GOLD)
    d.text((W - MR - 492, card_t + 232), "Team stand-in; no real multi-camera evidence.", font=SANS(16), fill=(168, 172, 178))
    footer(d,
           "Sources: var/live.db; var/demo.db; tools/sandbox/make_media.py. GJ11S7924 is a team-chosen stand-in. "
           + SYNTHETIC_ROUTE + ". Pre-28 Sep 11:15 IST stills may show another vehicle; a hash verifies bytes only.",
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
            "26 departments; the sandbox samples five: Home/Police, Health, GSRTC, Panchayat and Municipal bodies. Cameras differ in geometry, light and connectivity; plate-reading capability has to be measured.",
            intro, W - ML - MR):
        d.text((ML, y), line, font=intro, fill=INK)
        y += 32
    cards = [
        ("1", "Video cannot be centralised",
         "80,000 cameras × 2 Mbps is 160 Gbps sustained. Thirty days is ~52 PB. MODELLED arithmetic; not a load test."),
        ("2", "Capability is unknown and unequal",
         "Capability is assessed from each camera’s stream. Poor geometry and light constrain ANPR. UNKNOWN remains an explicit result."),
        ("3", "Connectivity is unreliable",
         "District-local processing can continue during uplink loss; queued metadata is replayed when the link returns."),
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
    footer(d, "Sources: organiser FAQ Q1/Q3/Q39; MODELLED arithmetic: docs/HLD.md §1 and §20.9; assumes 2 Mbps per camera and 30-day central video retention.")
    return img


def hybrid() -> Image.Image:
    return table_page(
        "Proposed model, with justification",
        "Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics.",
        ["MODEL", "ROLE / SOURCE PATH", "IMPLEMENTATION / BOUNDARY"],
        [
            [("M1 — Registry & GIS  (mandatory, kept)", None),
             ("Control plane, not a side deliverable. Identity, geometry, transport, health, measured capability.", None),
             ("Registry, GIS, governance and gap analysis. Cameras without coordinates remain listed; location provenance is retained.", None)],
            [("M2 — Direct unified viewing + selective analytics", None),
             ("Direct integration with reachable cameras/NVRs over RTSP/ONVIF or departmental APIs. No federation middleware on this path.", None),
             ("Government streams and own-feed MediaMTX use direct access. Both register in Model 1. Wall policies are described separately.", None)],
            [("M3 — VMS federation middleware", None),
             ("Departmental VMS → vendor API/SDK adapters → federation layer → unified platform. Both paths share the Model 1 registry.", None),
             ("Adapter contract and DEMO/TEST connectors built; no vendor SDK client or ONVIF discovery yet. Deployment is DESIGNED.", None)],
            [("M4 — Central analytics  (kept, selected cameras)", None),
             ("Selected streams through one controlled gateway into central analytics, events, watchlist, evidence, GIS.", None),
             ("Intelligence view. Detection, tracking, ANPR, alerts on own and selected feeds.", None)],
            [("M4 — Statewide central recording  (declined)", "red"),
             ("The transport, not the capability. Central ingest of all video refused on cost and on the Core Goal.", "red"),
             ("Not built, and not deferred. 80,000 × 2 Mbps ≈ 160 Gbps. 30-day retention ≈ 52 PB.", "red")],
        ],
        "Sources: organiser FAQ Q12–Q23 (Model 2 direct; Model 3 middleware; hybrid allowed); docs/HLD.md §10; docs/SCALE_MODEL.md. Federation deployment is DESIGNED.",
        "04",
        col_w=[ML, ML + 430, ML + 1100],
        tags=('VERIFIED', 'MODELLED', 'DESIGNED'),
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
    paste_c(img, _open(path), (RAIL, 0, W, H - 84))
    footer(d, caption)
    return img


def scenario() -> Image.Image:
    return table_page(
        "Evaluation  ·  requirement to evidence",
        "Test scenario, answered",
        ["BRIEF REQUIREMENT", "WHERE TO LOOK", "EVIDENCE AND BOUNDARY"],
        [
            [
                ("~50-feed requirement / registry baseline", None),
                ("Cameras / registry · Live wall", None),
                (
                    (
                        "30 government + 2 own feeds with video; 18 control slots are "
                        "registry rows without video (capacity placeholders). "
                        "Additional onboarded cameras are retained."
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
                        "GJ18JX7786: C-014 → C-021. " + SYNTHETIC_ROUTE +
                        ". Government stand-in GJ11S7924: cam06 only. "
                        "No real multi-camera evidence is established."
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
            [("Cell compute", None), ("Per full cell: 2,500 cameras at 1 Hz, ANPR-grade 20% (ASSUMED) at 5 fps; S=10 ASSUMED over the 5.6 fps CPU sizing baseline. 81 GPUs + 2 spares in 21 four-GPU servers (12 if all at 1 Hz); 10 ingest/decode servers. HLD §20.2–20.3.", None)],
            [("Hardware classes", None), ("Inference: 256 GB RAM per server. Decode: 64 cores / 256 GB. Database: primary + synchronous standby, 32 TB NVMe per copy. HLD §20.3; MODELLED, target GPU unmeasured.", None)],
            [("Metadata bandwidth", None), ("1,331.7 B/observation MEASURED (bandwidth.json); batches compress 8.0× (measure_compression.json). At 3,000 observations/camera-hour (ASSUMED): 3.83 Mbps per full cell, 82 Mbps statewide — MODELLED, HLD §20.4.", None)],
            [("Hot / warm / cold", None), ("MODELLED: 30-day hot metadata 14.4 TB per full cell (4.3 TB at the measured mean rate); lake 324 TB/year, 1.5 PB usable for 3 years plus a DR copy; evidence 100 TB write-once, assumed. HLD §20.5.", None)],
            [("Low connectivity", None), ("Video remains at departmental NVRs. Optional site inference ships metadata only; durable queues replay after reconnect (a week is 194 GB per cell). Viewing and evidence retrieval add traffic. HLD §20.1 / §20.4.", None)],
        ],
        "Sources: docs/HLD.md §20.1–20.5; reports/capacity_model.json; var/reports/bandwidth.json. Retention and target hardware require departmental agreement.",
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
                        "Own film: form onboarding and admin → officer handoff. "
                        "Government film: onboarded registry, viewing and analytics; no onboarding action."
                    ),
                ),
                (
                    "05 Analytics output quality",
                    (
                        "Person/vehicle detection; cam12 restricted-zone entries under an "
                        "administrator DEMONSTRATION rule in the film. Intrusion accuracy unmeasured."
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
                        "00_SUBMISSION_INDEX.md indexes docs, films and "
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
                        "C-014 → C-021: " + SYNTHETIC_ROUTE + "."
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
             ("T0–T2 analytic stages. RT-DETRv2 + ByteTrack + voted ANPR. Live worker samples at a fixed interval; FRS is DESIGNED.", None)],
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
    img, d = canvas(False, tags=("VERIFIED", "DESIGNED", "DEMO"))
    rail(img, d, "ANALYTICS", "11")
    kicker(d, "AI-powered video analytics")
    title(d, "Detection, recognition, and event analytics", y=84, size=34)
    cards = [
        ("T0  ·  presence",
         "Motion differencing per colour channel. A camera that cannot read a plate can still prove something passed."),
        ("T1  ·  detection + track",
         "RT-DETRv2 vehicles and persons. ByteTrack reimplemented for real PTS and scene cuts. Person box is presence, not identity."),
        ("T2  ·  recognition",
         "Plate found inside the vehicle box. OCR on sampled crops → per-track vote → one string, or no string. No face identification."),
        ("Events",
         "Watchlist match, motion presence, long-stay duration, and restricted-zone entries. The government film shows the cam12 administrator DEMONSTRATION rule; intrusion accuracy is unmeasured."),
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
    for i, line in enumerate(wrap(d,
            "FRS is DESIGNED and gated, not shipped: authorised gallery and legal basis, suitable camera grade, "
            "case/purpose and audit, human verification of candidates (HLD §11.2).",
            SANS(22), W - ML - MR)):
        d.text((ML, 732 + i * 30), line, font=SANS(22), fill=INK)
    footer(d, "Sources: docs/HLD.md §4.2; runtime/inference_scheduler.py; runtime/budget.py. Tier selection and priority cadence are built and tested in harnesses; live-worker wiring is DESIGNED. Live sampling uses a fixed interval.")
    return img


def watchlist_method() -> Image.Image:
    img, d = canvas(False, tags=('VERIFIED', 'DEMO', 'DESIGNED'))
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
        ("7", "Edge", "The district cell keeps matching if the uplink is down. Watchlist bundles fail closed on integrity."),
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
    for i, line in enumerate(wrap(d,
            "VAHAN, SARATHI, eGujCop (CCTNS), AFIS and NAFIS: adapters refuse with SourceUnavailable. "
            "Departmental access is required (DESIGNED); no live database integration is claimed.",
            SANS(22), W - ML - MR)):
        d.text((ML, 790 + i * 30), line, font=SANS(22), fill=INK)
    footer(d, "Sources: docs/HLD.md §10–11; src/saakshya/watchlist/government.py; watchlist/alerts.py. Local representative entries are separate from government database access.")
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
    img, d = canvas(False, tags=('VERIFIED', 'DEMO', 'MEASURED'))
    rail(img, d, "CREDIBILITY", "22")
    kicker(d, "What we will not claim")
    title(d, "A proposal that lists only strengths cannot be checked", y=88, size=40)
    d.rectangle((ML, 210, ML + 64, 214), fill=SEAL)
    points = [
        "Prototype scope: operational deployment, evidentiary acceptance and statewide live-video scale still require validation.",
        "ANPR yield depends on camera geometry and light. A camera being viewable does not mean it is under deep inference.",
        "GJ11S7924 on cam06 is a SINGLE-CAMERA GOVERNMENT OBSERVATION; no government route is established.",
        "GJ18JX7786 on C-014 → C-021: SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage.",
        "Person boxes are presence. There is no face identification on government data.",
        "Own-feed footage is published with heads blurred from the person detector's boxes. A person it never found is not blurred.",
        "The GPU speed-up is measured on a laptop's integrated GPU. The target accelerator's is not quoted until it is run.",
        "Copilot is read-only. It will not enhance a still, invent a plate, or join clocks the timebase refuses.",
        "No government plate spans two cameras; no government appearance embeddings were stored. Pre-28 Sep 11:15 IST stills may show another vehicle; hashes verify bytes only.",
        "The government store includes an active representative stolen_vehicle entry, GJ07XZ4409, with no government reads; its listing is not a verified theft record.",
    ]
    y = 240
    for p in points:
        d.text((ML, y), "■", font=SANS(16), fill=SEAL)
        yy = y
        for i, line in enumerate(wrap(d, p, SANS(22), W - ML - MR - 28)):
            d.text((ML + 28, yy), line, font=SANS(22), fill=INK)
            yy += 30
        y = yy + 14
    footer(d, "Sources: docs/HLD.md §19; var/demo/SUBMIT/06_*trace_report.html; var/live.db observations/watchlist (read-only check); analytics/worker.py evidence sealing.")
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
        # Nearest second, halves down: 339.97 s is 5:40 (truncation said
        # 5:39); halves round down, as the documents do.
        whole = math.ceil(secs - 0.5)
        return (f"{whole // 60}:{whole % 60:02d}  ·  {v['width']}×{v['height']}"
                f"  ·  {'audio present' if audio else 'silent'}")
    except Exception:
        return "not rendered on this host"


def films() -> Image.Image:
    img, d = canvas(True, tags=('MEASURED', 'DEMO'))
    rail(img, d, "FILMS", "23", dark=True)
    kicker(d, "What to play, in this pack", dark=True, y=64)
    tour = ROOT / "var/demo/government_tour.mp4"
    cards = [
        ("own_feed.mp4  ·  controlled own feed", _film_meta(ROOT / "var/demo/own_feed.mp4"),
         "Licensed Mumbai street footage, heads blurred. Masked sign-in; a camera onboarded through "
         "the registry form, validated before write; the administrator → officer handoff; the "
         "production pipeline's per-frame boxes replayed on the video clock, plates drawn only when "
         "the vote holds; a plate searched; a fictional watchlist alert, its route and trace report "
         "(synthetic corpus, labelled); the evidence chain."),
        ("government_feed.mp4 + ANPR report CSV", _film_meta(ROOT / "var/demo/government_feed.mp4"),
         "The government grid, recorded live 28 Sep 12:41–12:47 IST: onboarded registry (no onboarding action), "
         "30 control-room tiles with varying live availability, a focused camera, person "
         "detections and the demonstration zone rule, the ANPR gallery, the single-camera trace, "
         "GIS and the trace report. The CSV holds every government read: 901 to the 24 Sep "
         "snapshot and 200 during the 28 Sep recording session (11:15–12:53 IST). Only 21 reads fall inside the filmed take."),
    ]
    if tour.exists():
        cards.append((
            "government_tour.mp4  ·  every feature, from sign-in", _film_meta(tour),
            "RECORDED GOVERNMENT FOOTAGE (captured 15 Sep, replayed, never called live) on the wall "
            "and in focus, with the pipeline's per-frame boxes; then alerts, searches, evidence "
            "verification, cases and export, the Gemini copilot, the audit chain, Model 1 grades, "
            "gaps and validation, Model 3 systems, Model 4 analytics, the administrator refusal "
            "and the handoff."))
    title(d, f"{'Three' if len(cards) == 3 else 'Two'} films. One plate report. No mock-ups.",
          dark=True, y=108, size=44)
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
           "Sources: var/demo/*.mp4 (ffprobe at render). Own-feed plates come from the final pipeline's sidecars (Indian-trained recogniser); "
           "government session reads are the current recogniser's (docs/FINAL_SUBMISSION.md).",
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
            "Model 2: direct RTSP/ONVIF access; no federation middleware.",
            "Model 3: departmental VMS via federation adapters. Both register in Model 1.",
        ]),
        ("DISTRICT CELL / REGION", "Analytics and local continuity", [
            "Ingest → detect → track → ANPR on selected cameras.",
            "Local watchlist, alerts, evidence, store and durable queue.",
            "40 cells of ≤ 2,500 cameras; worker pools and failover are deployment design.",
        ]),
        ("STATE + DR SITE", "Metadata services", [
            "Registry, GIS, governance and cross-district investigation.",
            "PostgreSQL / PostGIS, evidence index and hash-chained audit.",
            "Watchlist bundles return to cells with integrity checks.",
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
    footer(d, "Sources: organiser FAQ Q16–Q19, Q23; docs/HLD.md §3, §6, §10, §15, §21. DESIGNED topology; VERIFIED component contracts. Departmental retention stays in place.")
    return img


def system_architecture() -> Image.Image:
    return table_page(
        "System architecture · component interactions",
        "Ingest → analytics → edge → store → investigation",
        ["COMPONENT", "INTERFACE / RESPONSIBILITY", "BOUNDARY"],
        [
            [("Ingest and timebase", None), ("PTS-aware frames, reconnect/backoff and discontinuity checks feed camera pipelines.", None), ("A shared timeline requires reliable clocks.", None)],
            [("Detection, tracking and ANPR", None), ("Vehicle/person boxes → track → plate crop → voted registration or no read.", None), ("Selected-camera inference at a fixed interval. Priority cadence and tier selection: tested in harnesses; live-worker wiring DESIGNED.", None)],
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


def government_evidence() -> Image.Image:
    """Read-only store snapshot verified on 28 Sep 2026; not unique people/vehicles."""
    return table_page(
        "Government feed · measured store snapshot · 28 Sep 2026",
        "Vehicle and person detection ran on the government feed",
        ["EVIDENCE", "RESULT AND BOUNDARY"],
        [
            [("Observations · cam01–cam30", None), ("1,155,325 rows; 2 Sep 06:54 – 24 Sep 16:10 2026 IST. Counts are observations, not unique vehicles or people.", None)],
            [("Vehicle detections", None), ("Car 529,966 (29 cameras); truck 184,600 (29); motorcycle 58,423 (25); bus 49,403 (28); bicycle 13,312 (25).", None)],
            [("Person and other detections", None), ("Person 307,290 (all 30 cameras); truck_bus 5,819; van 5,049; unknown 1,463. Vehicle AND person detection are measured.", None)],
            [("ANPR · 24 Sep snapshot", None), ("901 reads; 178 distinct plates; 97 confirmed registrations; 9 cameras. Confirmed = at least one read with ≥2 agreeing frames. Reads: 2–21 Sep 2026 IST.", None)],
            [("Live session · 28 Sep 11:15–12:53 IST", None), ("4,465 observations on the 4 deep-inference cameras; 200 plate reads (124 plates) on cam06 during the recording session; 21 fall inside the 12:41–12:47 film. Delivered CSV: 1,101 reads, 264 plates, 9 cameras.", None)],
            [("Government tracking finding", None), ("No plate was read on two government cameras: every government vehicle history is SINGLE-CAMERA. No appearance embeddings were stored; no government appearance re-identification ran.", None)],
            [("Restricted-zone rule · DEMO", None), ("cam12: ‘No pedestrians on the toll-lane carriageway’. Person-class polygon rule set by the estate administrator for this evaluation; not a measured intrusion-detection accuracy result.", None)],
        ],
        "Sources: var/live.db observations and zone_rules (read-only SQL, 28 Sep 2026); var/demo/government_feed_anpr_report.csv; src/saakshya/reports/anpr.py::CONFIRM_VOTES.",
        "22", col_w=[ML, ML + 450], tags=("MEASURED", "DEMO"),
    )


def government_designated() -> Image.Image:
    return table_page(
        "Designated vehicle · separate evidence boundaries",
        "Government stand-in and synthetic route logic",
        ["SOURCE", "REGISTRATION / LOCATIONS", "WHAT IT ESTABLISHES"],
        [
            [("Government stand-in", None), ("GJ11S7924 · 57 reads · cam06 only", None), ("Team-chosen from cam06 reads on 20 Sep, not organiser-issued. 52 snapshot + 5 session reads; all 5 precede the filmed take. No multi-camera route.", None)],
            [("All government plate histories", None), ("1,101 reads · 264 distinct plates · 9 cameras", None), ("No plate appears on two government cameras. No appearance embeddings were stored; no appearance re-identification ran.", None)],
            [("Synthetic route-logic report", None), ("GJ18JX7786 · C-014 → C-021", None), (SYNTHETIC_ROUTE + ". Seven single-frame leads, zero confirmed reads. No real multi-camera evidence.", None)],
            [("Older sealed stills", None), ("Before 28 Sep 2026 11:15 IST", None), ("May show another vehicle. A verified hash proves the bytes only; verify the crop/read pairing. These stills do not establish vehicle identity.", "red")],
        ],
        "Sources: var/live.db observations/watchlist; var/demo.db; tools/sandbox/make_media.py; var/demo/government_feed_anpr_report.csv. Read-only verification: 28 Sep 2026.",
        "25", col_w=[ML, ML + 410, ML + 880], tags=("VERIFIED", "DEMO"),
    )


def evaluation_day() -> Image.Image:
    return table_page(
        "Evaluation day · organiser-issued number",
        "Enter the issued plate, then search the whole estate",
        ["STEP", "OFFICER PROCEDURE"],
        [
            [("1 · Record the request", None), ("Enter the organiser-issued plate under a case and purpose. GJ11S7924 was a team-chosen rehearsal stand-in, not that issued number.", None)],
            [("2 · Search retrospectively", None), ("Search the whole authorised estate and available history. Review timestamped camera locations and any supported trajectory legs; keep absent coverage explicit.", None)],
            [("3 · Watch for new sightings", None), ("File the plate on the watchlist with its evaluation category, authority, scope and expiry so subsequent matching reads raise live alerts.", None)],
            [("4 · Open the trace report", None), ("Review reads, camera locations, timestamps and evidence cautions, then export the trace report. A single-camera history is not a complete multi-camera route.", None)],
        ],
        "Sources: organiser FAQ Q27–28; docs/HLD.md §11; src/saakshya/reports/vehicle_trace.py. Procedure for evaluation day; no successful real multi-camera trace is claimed.",
        "25a", col_w=[ML, ML + 440], tags=("DESIGNED",),
    )


def gallery_path(value: str, directory: Path) -> Path:
    """Exporter display_image is relative to its output directory, not ROOT."""
    path = Path(value)
    if path.is_absolute():
        return path
    # Keep explicitly repo-relative legacy paths, without allowing a coincident
    # ROOT/display file to shadow the exporter's gallery-relative display/ file.
    return ROOT / path if path.parts[:2] == ("var", "demo") else directory / path


def _ist(value: str, with_time: bool = True) -> str:
    """An exporter ISO timestamp as a reader would say it: 21 Sep 2026 · 02:13:45 IST.

    Converted to IST, not relabelled: a UTC input printed with its own clock
    and an "IST" suffix would be five and a half hours wrong. A timestamp with
    no zone cannot be converted, so it is shown as given.
    """
    from datetime import datetime, timedelta, timezone
    try:
        t = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    if t.tzinfo is None:
        return str(value)
    t = t.astimezone(timezone(timedelta(hours=5, minutes=30)))
    day = f"{t.day} {t:%b %Y}"
    return f"{day}  ·  {t:%H:%M:%S} IST" if with_time else day


def _reads(value: object) -> str:
    """Agreeing reads as the voter means them: one read is a lead, not a confirmation."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return "reads not recorded"
    return "single read — a lead, verify" if n <= 1 else f"{n} agreeing reads"


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
        for key in ("total_reads", "distinct_plates", "confirmed_registrations", "cameras_with_reads"):
            if not isinstance(stats[key], int) or isinstance(stats[key], bool) or stats[key] < 0:
                raise ValueError("statistics must be nonnegative integer counts")
        # Preflight every displayed crop before drawing any purported evidence.
        rows = selected[:8] if len(selected) >= 8 else selected[:6]
        # The plate alone, enlarged, reads at slide size; the full card's own
        # text does not. Fall back to the card for an older exporter.
        images = [_open(gallery_path(row.get("plate_image") or row["display_image"], directory))
                  for row in rows]
    except (OSError, ValueError, KeyError, TypeError):
        print("WARNING: GOVERNMENT ANPR GALLERY OMITTED — missing or invalid "
              "var/demo/plate_gallery/{selected.json,stats.json,display_image} inputs.", file=sys.stderr)
        return None
    fixture = any(row["provenance"] == "RENDER_TEST_FIXTURE" for row in rows)
    img, d = canvas(True, tags=("DEMO",) if fixture else ("MEASURED",))
    rail(img, d, "GOVERNMENT ANPR", "22a", dark=True)
    kicker(d, "RENDER TEST FIXTURE — NOT SUBMISSION EVIDENCE" if fixture else "Government feed · historical selected crops", dark=True)
    title(d, "Historical ANPR gallery · 24 Sep snapshot", dark=True, size=42)
    camera_count = stats["cameras_with_reads"]
    band = (f"{stats['total_reads']:,} total reads   ·   {stats['distinct_plates']:,} distinct plates   ·   "
            f"{stats['confirmed_registrations']:,} confirmed registrations   ·   {camera_count} cameras")
    d.text((ML, 160), band, font=SANS_B(24), fill=GOLD)
    d.text((ML, 202), f"Read window: {_ist(stats['window_start'], False)} – {_ist(stats['window_end'], False)} (IST)",
           font=SANS(20), fill=WHITE)
    d.text((ML, 240), "Selected examples below; statistics cover every government read in the stated window.", font=SANS(20), fill=WHITE)
    columns = 4 if len(rows) == 8 else 3
    gap = 22
    cw = (W - ML - MR - gap * (columns - 1)) // columns
    for i, (row, crop) in enumerate(zip(rows, images)):
        x, y = ML + i % columns * (cw + gap), 294 + i // columns * 316
        d.rounded_rectangle((x, y, x + cw, y + 296), radius=8, fill=DARK_2)
        paste_c(img, crop, (x + 12, y + 12, x + cw - 12, y + 150))
        d.text((x + 18, y + 160), str(row["plate_text"]), font=SANS_B(26), fill=WHITE)
        d.text((x + 18, y + 196), f"{row['camera']}  ·  OCR confidence {float(row['confidence']):.1%}",
               font=SANS(19), fill=GOLD)
        d.text((x + 18, y + 226), _reads(row["agreeing_reads"]), font=SANS(18), fill=WHITE)
        d.text((x + 18, y + 256), _ist(row["timestamp"]), font=SANS(18), fill=MUTED)
    footer(d, "Sources: var/demo/plate_gallery/selected.json (plate_image, nearest-neighbour enlargement "
           "of the sealed frame); stats.json (stated window only). "
           + str(stats["source"]) + ". Delivered CSV adds 200 reads from the 28 Sep session: 1,101 reads / 264 plates. "
           "Pre-28 Sep 11:15 IST stills may show another vehicle; hashes verify bytes only; check crop/read pairing.", dark=True, y=944)
    return img


def ai_coverage() -> Image.Image:
    pipe, det = report("pipeline_device"), report("detector_device")
    cluster, load = report("live_cluster"), report("camera_load")
    stage = cluster["stages"][0]
    n = sum(row.get("frames_analysed", 0) > 0 for row in stage["per_camera"])
    basis = f"Historical cohort: {n} cameras analysed in live_cluster.json; not current concurrency."
    sweep = ROOT / "var/reports/ai_concurrency_sweep.json"
    if sweep.exists():
        # No sweep schema is mandated by the export contract. Accept explicit
        # measured concurrency only; never infer it from decode session counts.
        try:
            data = json.loads(sweep.read_text())
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        measured_n = data.get("deep_inference_concurrency")
        if isinstance(measured_n, int) and not isinstance(measured_n, bool) and measured_n > 0:
            basis = f"Sweep: {measured_n} concurrent cameras reported in ai_concurrency_sweep.json; separate test configuration."
        else:
            print("WARNING: AI sweep lacks explicit deep_inference_concurrency; "
                  "using the named historical live_cluster cohort, not current concurrency.", file=sys.stderr)
    img, d = canvas(False, tags=("VERIFIED", "MEASURED", "MODELLED", "DESIGNED"))
    rail(img, d, "AI COVERAGE", "36a")
    kicker(d, "Measured workload · modelled hardware · designed deployment")
    title(d, "AI coverage and hardware scaling", size=46)
    coverage = ("Every integrated camera viewable on the wall, subject to availability; "
                "4 deep-inference slots by default, prioritised by measured capability; the live worker samples at a fixed interval.")
    yy = 170
    for line in wrap(d, coverage, SANS_B(25), W - ML - MR):
        d.text((ML, yy), line, font=SANS_B(25), fill=INK)
        yy += 34
    d.text((ML, yy + 4), "VERIFIED default: analytics/worker.py::AI_CAMERA_LIMIT; assigned at boot, not rotated. " + basis, font=SANS(16), fill=MUTED)
    cols = [
        ("CURRENT DEMO MACHINE", "MEASURED", [
            f"Historical live_cluster.json cohort: {n} cameras with analysed frames. This is not the current slot count or a hardware maximum.",
            f"Device pipeline: {pipe['mps']['fps']:.2f} fps; {pipe['mps']['ms_median']:.1f} ms median / {pipe['mps']['ms_p95']:.1f} ms p95. pipeline_device.json.",
            f"Detector only: {det['mps']['fps']:.1f} fps; {det['mps']['ms_median']:.1f} ms median. detector_device.json.",
            f"Decode/load: {load['aggregate']['cameras_streaming']}/{load['aggregate']['cameras_total']} streaming at end. camera_load.json. Separate workload.",
            "Earlier OCR pipeline; current recogniser needs a fresh benchmark. Slots are assigned GOOD > DEGRADED > UNKNOWN > UNSUITABLE at worker boot.",
        ]),
        ("CELL GPU POOL", "MODELLED", [
            "SIZED: 2,500 cameras per full cell at 1 Hz, ANPR-grade 20% at 5 fps (ASSUMED); 5.6 fps CPU sizing baseline. S=10 speedup ASSUMED, not measured on target GPUs.",
            "83 GPUs / full cell in 21 four-GPU servers. 80,000 cameras in 40 cells → 2,652 GPUs / 663 servers (1 Hz for all: 1,509 / 378).",
            "Decode is sized separately. Benchmark tendered hardware, including OCR and memory, before procurement.",
            "docs/HLD.md §17.6, §20.2–20.3. Planning input differs from the device workload at left.",
        ]),
        ("STATEWIDE", "DESIGNED", [
            "Regional ingest; horizontal worker pools; metadata event bus and district-local queues.",
            "AdaptiveInferenceScheduler (built; tested in the certification harness) sets cadence by priority mode; live-worker wiring is DESIGNED.",
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
    footer(d, "Sources: var/reports/{live_cluster,pipeline_device,detector_device,camera_load}.json; docs/HLD.md §20; src/saakshya/{analytics/worker,runtime/inference_scheduler}.py.", y=991)
    return img


def cost_benefit() -> Image.Image:
    table = capacity()["cost_table"]
    cell, state = table["one_full_cell_2500"], table["statewide_planning"]

    def crore(pair: list[float]) -> str:
        lo, hi = pair
        digits = 0 if lo >= 10 else 1
        return f"INR {lo:,.{digits}f}–{hi:,.{digits}f} crore"

    return table_page(
        "MODELLED cost  ·  assumed unit rates and accelerator speedup",
        "Indicative cost and avoided central-video spend",
        ["SCOPE", "IMPLEMENTATION", "ANNUAL OPERATIONS"],
        [
            [("PoC · approximately 50 cameras", None), ("INR 29–63 lakh", None), ("INR 18–50 lakh", None)],
            [("Full district cell · 2,500 cameras", None), (crore(cell["implementation_crore"]), None), (crore(cell["operations_crore_per_year"]), None)],
            [("Statewide · 40 cells + 6 regions + state/DR", None), (crore(state["implementation_crore"]), None), (crore(state["operations_crore_per_year"]), None)],
            [("Avoided central video storage", None), ("INR 52–156 crore · disks only", None), ("52 PB; one copy, before DR / replication", None)],
            [("Avoided central video transport", None), ("160 Gbps continuous ingest", None), ("INR 58–154 crore / year", None)],
            [("Operational benefit", None), ("Searchable history, incident grouping, sealed evidence", None), ("Investigation time savings remain estimates; measure in the district pilot.", None)],
        ],
        "Source: docs/HLD.md §20.8–20.9; reports/capacity_model.json. MODELLED on ASSUMED S=10, 20% ANPR-grade at 5 fps and unit prices, before taxes; not quotes. VMS spend continues.",
        "11b", col_w=[ML, ML + 580, ML + 1130], tags=("MODELLED",),
    )


def resilience_rollout() -> Image.Image:
    return table_page(
        "Deployment path  ·  cybersecurity and DR",
        "District cell pilot, regional rollout, metadata state tier",
        ["DESIGN / PHASE", "TARGET AND VALIDATION"],
        [
            [("Cybersecurity", None), ("Segment camera, analytics, data and operator zones. TLS in transit; encrypted stores and backups; keys held apart. RBAC, jurisdiction and purpose gates; audit exported for review. HLD §18.", None)],
            [("Cell continuity", None), ("Watchlist, evidence and queues continue locally during uplink loss. Cell metadata targets: RPO 0 in the cell, ≤5 min off it; RTO ≤60 s failover, ≤8 h rebuild. Assumed targets; restore/replay must be drilled. HLD §15.", None)],
            [("State HA and DR", None), ("Synchronous standbys, event bus mirrored to DR, erasure-coded lake. Plate index and registry: RPO ≤1 min to DR, RTO ≤1 h at DR; lake reads ≤4 h. Multi-node failover remains untested. HLD §15.", None)],
            [("Pilot → cell → region → state", None), ("Survey cameras, obtain catalogue and watchlist authority; each phase passes measured gates first (S on the tendered GPU, observation rate, compression ≥4×, WAN-cut drill). HLD §13–16.", None)],
            [("Inputs from each department", None), ("Inventory, mount, codec, resolution and surveyed coordinates; NVR/VMS vendor, version and authorised API/stream access; network path/bandwidth; retention/evidence policy and watchlist authority. HLD §13.", None)],
            [("Operations and acceptance", None), ("Health/readiness probes, metrics, structured logs and hash-chained audit exist. Deployment adds load balancing, log retention, alerts, camera assignment and failover. HLD §20.6.", None)],
        ],
        "Sources: docs/HLD.md §13–16, §18, §20.6; docs/STATEWIDE_ARCHITECTURE.md §8. RPO/RTO are ASSUMED targets, not measured recovery. Government integrations require authority.",
        "11c", col_w=[ML, ML + 430], tags=("DESIGNED", "VERIFIED"),
    )

# ---------------------------------------------------------------- statewide
# The three statewide pages read reports/capacity_model.json, written by
# tools/sizing/capacity_model.py, so a re-run of the model cannot leave the
# deck quoting last week's numbers.

def capacity() -> dict[str, Any]:
    return json.loads((ROOT / "reports/capacity_model.json").read_text())


def _row(model: dict[str, Any], prefix: str) -> dict[str, Any]:
    rows = [r for r in model["rows"] if r["resource"].startswith(prefix)]
    if len(rows) != 1:
        raise KeyError(f"capacity_model.json: {len(rows)} rows start with {prefix!r}")
    return rows[0]


def _num(v: float) -> str:
    if float(v).is_integer() or v >= 100:
        return f"{v:,.0f}"
    return f"{v:.1f}" if v >= 10 else f"{v:.2f}".rstrip("0").rstrip(".")


def _bullets(d: ImageDraw.ImageDraw, points: list[str], y: int, *, size: int = 21) -> int:
    for point in points:
        d.text((ML, y + 2), "■", font=SANS(14), fill=SEAL)
        for line in wrap(d, point, SANS(size), W - ML - MR - 28):
            d.text((ML + 28, y), line, font=SANS(size), fill=INK)
            y += int(size * 1.36)
        y += 10
    return y


def _grid(d: ImageDraw.ImageDraw, y: int, columns: list[str], rows: list[list[tuple[str, str | None]]],
          xs: list[int], *, size: int = 20, gap: int = 12) -> int:
    for i, col in enumerate(columns):
        _text(d, (xs[i], y), col.upper(), SANS(13), MUTED, spacing=2.2)
    d.line([(ML, y + 24), (W - MR, y + 24)], fill=RULE, width=1)
    y += 38
    tones = {"green": GREEN, "red": RED, "gold": (146, 97, 10)}
    for row in rows:
        rh = 0
        for i, (text, tone) in enumerate(row):
            face = SANS_B(size) if i == 0 else SANS(size)
            width = (xs[i + 1] if i + 1 < len(xs) else W - MR) - xs[i] - 14
            lines = wrap(d, text, face, max(60, width))
            for li, line in enumerate(lines):
                d.text((xs[i], y + li * (size + 6)), line, font=face, fill=tones.get(tone or "", INK))
            rh = max(rh, len(lines) * (size + 6))
        y += rh + gap
        d.line([(ML, y - gap // 2 - 2), (W - MR, y - gap // 2 - 2)], fill=(236, 236, 232), width=1)
    return y


def statewide_compute() -> Image.Image:
    m = capacity()
    comp, wan, rates = m["compute"], m["wan_cell"], m["rates"]
    ratio = m["inputs"]["obs_zlib_ratio_batch100"]["value"]
    img, d = canvas(False, tags=("MEASURED", "MODELLED", "DESIGNED"))
    rail(img, d, "STATEWIDE", "11a")
    kicker(d, "Statewide target architecture  ·  sized, not tested at 80,000")
    ty = title(d, "80,000 cameras: only compute grows with cameras analysed", y=84, size=40)
    y = _bullets(d, [
        f"Video stays with the department. Only metadata crosses the WAN: {rates['state_metadata_mbps_z_pess']:.0f} Mbps "
        f"statewide compressed at a pessimistic 3,000 observations per camera-hour (ASSUMED), against "
        f"{rates['central_video_gbps_2mbps']:.0f} Gbps for central video. MODELLED.",
        "A district cell holds at most 2,500 cameras or 4,000 observations/s, and runs detection, ANPR, alerts and "
        "evidence locally. Plates are partitioned by plate: a designated-vehicle route reads one shard. DESIGNED.",
        "Camera-driven non-compute resources keep ≥ 5× headroom on throughput and ≥ 2.2× on hot storage at 100% "
        "analysed; the 3-year lake (1.5×) is bought per retention year. MODELLED.",
        f"Unit costs measured on this project: {m['inputs']['obs_wire_bytes']['value']:,} B per observation, "
        f"{ratio:.1f}× batch compression, {m['inputs']['pg_write_rows_per_s_one_stream']['value']:,} rows/s PostgreSQL, "
        f"{m['inputs']['postgis_viewport_p50_ms_80k']['value']} ms PostGIS viewport on 80,000 cameras. "
        f"GPU speed-up S = 10 is ASSUMED.",
    ], ty + 22, size=24)
    rows = [[(f"{r['analysed']:,}", None), (f"{r['gpus']:,}", "gold"), (_num(r["avg_cell_wan_mbps"]), None),
             (_num(r["state_bus_MBps"]), None), (_num(r["cell_db_rows_s"]), None), (_num(r["lake_TB_yr"]), None)]
            for r in m["sweep"]]
    xs = [ML + i * 285 for i in range(6)]
    _grid(d, y + 14, ["Analysed cameras", "GPUs incl. spares", "Cell WAN, Mbps", "State bus, MB/s",
                      "Cell DB rows/s", "Lake TB / year"], rows, xs, size=28, gap=20)
    footer(d, f"Growth at pessimistic rates, average cell of 80,000 / 40 cameras. {comp['gpus_with_spares']:,} GPUs = {comp['servers_4gpu']} servers; "
              f"a full cell sends {wan['total_mbps']} Mbps. Source: reports/capacity_model.json; HLD §21.")
    return img


def statewide_tiers() -> Image.Image:
    img, d = canvas(False, tags=("DESIGNED", "VERIFIED", "MODELLED"))
    rail(img, d, "STATEWIDE", "11b")
    kicker(d, "Statewide tiers  ·  DESIGNED; the cell's offline half is built and tested")
    ty = title(d, "Three tiers, and what survives each failure", y=84, size=40)
    y = _bullets(d, [
        "Camera / site: nothing new at most sites; an edge box only where the site's link cannot carry its streams.",
        "District cell (40): GPU pool, event bus, PostgreSQL + PostGIS, media gateway, federation adapters. It keeps "
        "detecting, matching, alerting and sealing evidence with the WAN down.",
        "Region (6): viewing fan-out, backups, forensic GPUs. State + DR: registry and GIS, plate index, lake, identity.",
        "Model 1 everywhere; Model 2 direct; Model 3 for departments with a VMS; Model 4 on selected cameras only.",
    ], ty + 22, size=24)
    rows = [
        [("Cell WAN", None), ("Detection, local watchlist match, alerts, evidence sealing, district control room", "green"),
         ("Statewide search stale for that cell; catches up by priority lane", None)],
        [("Region", None), ("Cells and state", "green"), ("Remote viewing moves to a neighbour region; backups queue", None)],
        [("State event bus", None), ("Cells", "green"), ("Plate and alert lanes queue in the cell (7 days: 194 GB per cell, MODELLED)", None)],
        [("State database", None), ("Cells; the bus keeps 7 days", "green"), ("Statewide routes pause, then replay", None)],
        [("Whole state DC", None), ("Everything local", "green"), ("DR takes over; cells keep the last valid watchlist, fail-closed", None)],
        [("GPU saturation", None), ("ALERT and HIGH_PRIORITY cadence first", "green"), ("NORMAL frames shed", None)],
    ]
    _grid(d, y + 14, ["What fails", "What keeps working", "What degrades"], rows,
          [ML, ML + 300, ML + 1050], size=24, gap=18)
    footer(d, "Sources: docs/STATEWIDE_ARCHITECTURE.md §2, §8; HLD §3, §6, §15; tests/e2e/test_offline_mode.py. RPO/RTO targets ASSUMED; multi-node failover untested.")
    return img


def statewide_binding() -> Image.Image:
    m = capacity()
    hostile = m["hostile"]["b_all_highway_cell_at_peak_hour"]
    img, d = canvas(False, tags=("MEASURED", "MODELLED", "DESIGNED"))
    rail(img, d, "STATEWIDE", "11c")
    kicker(d, "Binding-constraint check  ·  pessimistic, 80,000 cameras all analysed")
    ty = title(d, "Every resource against its capacity: compute binds first", y=84, size=40)
    wan_raw = _row(m, "Cell WAN uplink, raw")
    kafka_raw = _row(m, "State event bus IF all observations")
    y = _bullets(d, [
        f"Would-be bottlenecks found and designed out: uncompressed metadata on a 20 Mbps link ({wan_raw['headroom']}×), "
        f"every observation through the state bus ({kafka_raw['headroom']}×), a cell of highway cameras "
        f"({hostile['db_headroom_half_measured']}× on the database at half the measured write rate; cells now split at 4,000 observations/s).",
        "Inference compute binds first by construction: GPUs are bought to demand, S is measured on tendered hardware before purchase.",
        "Bus, gateway, TURN and object-store capacities are ASSUMED and are Phase 1 measurement gates (HLD §16).",
    ], ty + 20, size=22)
    picks = [
        ("Cell WAN, compressed", "Cell WAN uplink (metadata, compressed)", "cameras", "Mbps"),
        ("Cell WAN, uncompressed (rejected)", "Cell WAN uplink, raw", "cameras", "Mbps"),
        ("State bus, real-time lanes", "State event bus (Kafka), real-time lanes only", "cameras", "MB/s"),
        ("State bus, all observations (rejected)", "State event bus IF all observations", "cameras", "MB/s"),
        ("Cell database writes", "Cell DB write rate", "cameras", "rows/s"),
        ("Cell hot store, 30 days", "Cell hot store", "cameras", "TB"),
        ("State lake, 3 years", "State object store, 3 years", "cameras", "TB"),
        ("Media gateway sessions / cell", "Media gateway sessions", "viewers", "sessions"),
        ("State API", "API request rate", "users", "req/s"),
        ("Watchlist bootstrap, one cell", "Watchlist bootstrap", "list size", "s"),
    ]
    rows = []
    for label, prefix, driver, unit in picks:
        r = _row(m, prefix)
        h = r["headroom"]
        tone = "red" if h < 1.2 else ("gold" if h < 5 else "green")
        rows.append([(label, None), (driver, None), (f"{_num(r['demand'])} {unit}", None),
                     (f"{_num(r['capacity'])} {unit}", None), (f"{h:.2f}×" if h < 3 else f"{h:.1f}×", tone)])
    _grid(d, y + 12, ["Resource", "Driven by", "Demand", "Capacity", "Headroom"], rows,
          [ML, ML + 560, ML + 820, ML + 1180, ML + 1520], size=23, gap=13)
    footer(d, "Headroom = capacity ÷ demand. Storage is policy-elastic; viewers and users have their own admission control. "
              "Source: reports/capacity_model.json; HLD §21.")
    return img


def live_integration_story() -> Image.Image:
    img, d = canvas(False, tags=("MEASURED", "VERIFIED"))
    rail(img, d, "Government integration", "")
    kicker(d, "Government grid · integration timeline")
    title(d, "What it took to integrate the live grid", size=48)
    columns = [
        ("19 SEP · REPORTED TO SENTINEL", [
            "MEASURED in the retained 16 Sep UTC reports: 30/30 IDs yielded RTSP frames; 15 direct WHEP, 15 bridge candidates.",
            "VideoToolbox reached 15 preview bridges in the scale test. The mixed wall held 19 browser-visible cameras for 60 s: 15 direct + 4 bridged; 0 NO_SIGNAL.",
            "That wall classified 8 LIVE + 11 PREVIEW. Fan-in failures did not establish a bridge maximum or a sandbox quota.",
        ]),
        ("SENTINEL · GUIDANCE", [
            "We asked about concurrency, long-lived sessions, the 30-camera pattern, a catalogue and connection pacing.",
            "No fixed participant-facing session limit; availability varies with shared load. Open only needed streams; design independently of camera count.",
            "Isolate cameras, stagger opens and back off. No separate /api/ingest catalogue. Fan-in variation is not a local-bridge limit.",
        ]),
        ("VERIFIED · IMPLEMENTATION", [
            "Direct WHEP via authenticated signalling; credentials stay server-side. CONTROL ROOM / OPTIMIZED VIEW state the local session policy.",
            "On-demand hub; 4 deep-inference slots, prioritised by measured capability. Viewing is separate from AI coverage.",
            "Playback progress governs LIVE; preflight gates and stall hand-over constrain recording. The ANPR export filters GOVERNMENT.",
        ]),
    ]
    for i, (heading, paragraphs) in enumerate(columns):
        x = ML + i * 578
        d.line((x, 205, x + 536, 205), fill=GREEN, width=3)
        d.text((x, 224), heading, font=SANS_B(19), fill=INK)
        y = 272
        for paragraph in paragraphs:
            for line in wrap(d, paragraph, SANS(23), 526):
                d.text((x, y), line, font=SANS(23), fill=INK)
                y += 30
            y += 22
    d.rounded_rectangle((ML, 755, W - MR, 956), radius=8, fill=NAVY)
    d.text((ML + 24, 774), "28 SEP · RECORDED GOVERNMENT DEMONSTRATION", font=SANS_B(21), fill=GOLD)
    lines = [
        "Eight attempts (team-reported). MEASURED: 6–13 of 30 advancing; submitted take 5:40, 12:41–12:47 IST.",
        "200 live cam06 reads in the 11:15–12:53 IST session; 21 within the filmed take. Single-camera evidence.",
        "401 refusals from 12:57 IST prevented further recording. Cause unestablished; no fixed quota inferred.",
    ]
    for i, line in enumerate(lines):
        d.text((ML + 24, 817 + i * 39), line, font=SANS(23), fill=WHITE)
    footer(d, "Sources: docs/LIVE_INTEGRATION_STORY.md (claim-by-claim references); reports/PHASE14_REAL_CAMERA_SOURCE_CENSUS.md; "
           "reports/PHASE16_30_CAMERA_BROWSER_COVERAGE.md; docs/SENTINEL_SUPPORT_CLARIFICATION.md; "
           "reports/FINAL_SUBMISSION_CERTIFICATION.md; var/demo/gov_take7/beats.json.", y=993)
    return img


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
        bleed(DIAG / "05_statewide_architecture.png", "Architecture", "Statewide target architecture",
              "DESIGNED · Source: var/demo/diagrams/05_statewide_architecture.png; docs/HLD.md §21. Analog via encoder; private CCTV consented, view-only.", "08a"),
        system_architecture(),
        scenario(),
        infrastructure(),
        statewide_compute(),
        statewide_tiers(),
        statewide_binding(),
        cost_benefit(),
        resilience_rollout(),
        pipeline(),
        analytics(),
        watchlist_method(),
        stack(),
        scale_security(),
        benefits(),
        media_policies(),
        live_integration_story(),
        shot_page(SHOTS / "gov_live_grid.png",
                  "Live wall  ·  Model 2  ·  a frame of the government film",
                  "Wall viewing and AI coverage are separate",
                  "CONTROL ROOM up to 30 WHEP sessions; OPTIMIZED VIEW ≤12. Policies: ui/app.js. Live availability varies by test window; this filmed frame shows 8 live cameras.",
                  "18"),
        shot_page(SHOTS / "gov_live_dense_2026-09-28.png",
                  "Live · CONTROL ROOM · 28 Sep government film",
                  "12 of 30 government cameras live in this recording",
                  "12 of 30 government cameras live in this recording. Measured in the 28 Sep 2026 film; availability varies with the test window.",
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
            "Source: var/demo/detect_stills/gov_overlay_t*.jpg. Historical capture: 15 Sep 2026; government detections; these selected frames do not establish plate-reading accuracy.",
            "20"),
        government_evidence(),
        *([gallery] if gallery is not None else []),
        shot_page(SHOTS / "own_intel.png",
                  "Own feed  ·  controlled demonstration",
                  "Every box is this platform's pipeline, on that exact frame",
                  "Heads blurred from the person detector's boxes — no face detector exists. Live AI plane figures are measured, on the GPU.",
                  "16"),
        shot_page(SHOTS / "own_find.png",
                  "Investigate  ·  designated vehicle (fictional plate)",
                  "GJ18JX7786: on the watchlist, said first. Then where it went.",
                  SYNTHETIC_ROUTE + ". UI ‘PLATE-CONFIRMED 2 of 2’ counts plate-bearing route observations; ‘TRAJECTORY CONFIRMED’ is a route score. The trace report has 7 single-frame leads, 0 confirmed reads (var/demo.db; intelligence/trajectory.py).",
                  "17"),
        government_designated(),
        evaluation_day(),
        shot_page(SHOTS / "gov_find_lookalike.jpg",
                  "Investigate  ·  lookalike, not a match",
                  "6J1VV0119 is an OCR lookalike of GJ1VV0119",
                  "Historical lookalike example, separate from the designated vehicle. The platform does not infer another camera or a route from OCR similarity.",
                  "19"),
        shot_page(SHOTS / "gov_alerts_film.jpg",
                  "Watchlist  ·  government grid",
                  "Government evaluation marks, grouped into incidents",
                  "Shown entries are evaluation marks. Pre-28 Sep 11:15 IST stills may show another vehicle; hashes verify bytes only. The store also has a representative stolen_vehicle entry (var/live.db).",
                  "20"),
        shot_page(SHOTS / "own_alerts.png",
                  "Watchlist  ·  one decision per vehicle",
                  "Repeated reads are grouped into a vehicle incident",
                  SYNTHETIC_ROUTE + ". Fictional plates and listings demonstrate incident grouping, not a government theft record (var/demo.db; tools/sandbox/make_media.py).",
                  "20b"),
        shot_page(SHOTS / "own_trace_report.png",
                  "Investigate  ·  vehicle trace report",
                  "The route leaves the screen as a page an officer can sign",
                  "SYNTHETIC RENDERED TEST CORPUS — route-logic demonstration, not camera footage. Fictional plate/listing; the displayed police attribution is part of the demonstration. Seven single-frame leads, zero confirmed reads (var/demo.db).",
                  "20c"),
        shot_page(SHOTS / "own_evidence.png",
                  "Evidence  ·  hash-chained records",
                  "What each sealed record is, and the link that binds it",
                  SYNTHETIC_ROUTE + ". Records: var/demo.db. Hashes establish file integrity only. Pre-28 Sep 11:15 IST stills may show another vehicle; verify crop/read pairing.",
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
