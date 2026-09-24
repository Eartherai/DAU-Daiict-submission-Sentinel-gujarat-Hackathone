"""Final Gujarat Police Innovation Challenge 2026 submission deck.

Editorial 16:9 pages (WhatsApp-deck layout language) with SAAKSHYA honesty:
measured numbers from docs/MEASURED_RESULTS.md, latest workspace screenshots,
detection overlays, and the two architecture diagrams supplied for this pack.

    python tools/demo/render_submission_deck.py
"""
from __future__ import annotations

import argparse
import io
import shutil
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


def canvas(dark: bool = False) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), DARK if dark else PAPER)
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
    img, d = canvas(False)
    rail(img, d, kicker_s.split()[0] if kicker_s else "WORKSPACE", page)
    kicker(d, kicker_s, y=28)
    ty = title(d, heading, y=48, size=32)
    paste_c(img, _open(path), (ML - 8, ty + 6, W - 36, H - 78))
    footer(d, caption, y=H - 52)
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
    img, d = canvas(False)
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
               page: str, *, dark: bool = False, col_w: list[int] | None = None) -> Image.Image:
    img, d = canvas(dark)
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
    img, d = canvas(True)
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
        ("30", "CAMERAS ONBOARDED", "MEASURED"),
        ("0", "ANPR-GOOD GRADES", "MEASURED"),
        ("0", "CROSS-CAMERA REPEATS", "MEASURED"),
        ("689,502", "OBSERVATIONS", "MEASURED · 6 SEP"),
    ]
    x = ML
    for num, lab, tag in kpis:
        d.text((x, 568), num, font=SANS_B(52), fill=WHITE)
        _text(d, (x, 638), lab, SANS(13), (168, 172, 178), spacing=2.2)
        d.text((x, 662), tag, font=SANS(13), fill=GOLD)
        x += 420
    footer(d,
           "Every headline figure is MEASURED from the 6 Sep 2026 live-store sheet, or MODELLED with the arithmetic shown. Screenshots are the running workspace on 15 Sep 2026.",
           dark=True)
    return img


def framing() -> Image.Image:
    img, d = canvas(True)
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
    d.text((W - MR - 492, card_t + 92), "GJ1VV0119  ·  cam07 only", font=MONO(20), fill=GOLD)
    d.text((W - MR - 492, card_t + 148), "Own feed (synthetic)", font=SANS_B(22), fill=WHITE)
    d.text((W - MR - 492, card_t + 180), "GJ05AB1234  ·  C-014 + C-021", font=MONO(20), fill=GOLD)
    d.text((W - MR - 492, card_t + 232), "A looping single camera is not a route.", font=SANS(16), fill=(168, 172, 178))
    footer(d,
           "A watchlist answers questions asked in advance. An index answers a question nobody had asked yet — which is the evaluation.",
           dark=True)
    return img


def problem() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "PROBLEM", "03")
    kicker(d, "Problem statement")
    ty = title(d, "Gujarat’s cameras are not one system", y=88, size=50)
    d.rectangle((ML, ty + 8, ML + 64, ty + 12), fill=SEAL)
    intro = SANS(22)
    y = ty + 36
    for line in wrap(d,
            "Tens of thousands of cameras, installed over two decades by Home, Health, GSRTC, Panchayat and Municipal bodies, for local supervision. Most were never installed to read a plate — and nobody has a list of which ones can.",
            intro, W - ML - MR):
        d.text((ML, y), line, font=intro, fill=INK)
        y += 32
    cards = [
        ("1", "Video cannot be centralised",
         "80,000 cameras × 2 Mbps is 160 Gbps sustained. Thirty days is ~52 PB. MODELLED arithmetic; not a load test."),
        ("2", "Capability is unknown and unequal",
         "28 of 30 government cameras grade UNSUITABLE for ANPR from their own stream. UNKNOWN is a first-class answer."),
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
    footer(d, "An investigator’s question is “where did this vehicle go?” — not “show me every camera at once.”")
    return img


def hybrid() -> Image.Image:
    return table_page(
        "Proposed model, with justification",
        "Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics.",
        ["MODEL", "ROLE IN THE HYBRID", "DEMONSTRATED BY"],
        [
            [("M1 — Registry & GIS  (mandatory, kept)", None),
             ("Control plane, not a side deliverable. Identity, geometry, transport, health, measured capability.", None),
             ("30 cameras onboarded. 19 placed from names; 11 listed, not invented. Estate map.", None)],
            [("M2 — Unified viewing  (kept as stills)", None),
             ("One JPEG per camera from the decode analytics already paid for. Not thirty extra RTSP copies.", None),
             ("Live wall. LIVE if the frame is under 2.5 s; otherwise STALE. Click-to-play is optional.", None)],
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
        "The organising idea — move analytics to the edge, move only metadata to the centre, move video only on demand.",
        "04",
        col_w=[ML, ML + 430, ML + 1100],
    )


def model4() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "ARITHMETIC", "05")
    kicker(d, "Why central recording is declined")
    title(d, "The sizing number is arithmetic, shown in full", y=88, size=44)
    rows = [
        ("Cameras (issued figure)", "80,000", "MODELLED"),
        ("Assumed bitrate", "2 Mbps each", "MODELLED"),
        ("Sustained ingest", "80,000 × 2 Mbps = 160 Gbps", "MODELLED"),
        ("30-day central store", "160 Gbps × 30 × 86,400 / 8 ≈ 52 PB", "MODELLED"),
        ("What we actually ran", "30 government cameras, one host", "MEASURED"),
        ("Video off the wire (3 cameras)", "1.363 Mbps", "MEASURED"),
        ("Observations at peak event rate", "0.071 Mbps  ·  19.3× smaller than video", "MEASURED"),
    ]
    y = 220
    d.line([(ML, y), (W - MR, y)], fill=RULE, width=1)
    y += 18
    for label, val, tag in rows:
        d.text((ML, y), label, font=SANS(22), fill=INK)
        d.text((ML + 720, y), val, font=SANS_B(22), fill=INK)
        fill = GREEN if tag == "MEASURED" else (146, 97, 10)
        d.text((W - MR - 160, y), tag, font=SANS(16), fill=fill)
        y += 52
        d.line([(ML, y - 14), (W - MR, y - 14)], fill=(236, 236, 232), width=1)
    d.rounded_rectangle((ML, y + 8, W - MR, y + 168), radius=8, outline=RULE, width=1)
    d.rectangle((ML, y + 8, ML + 6, y + 168), fill=SEAL)
    d.text((ML + 28, y + 28), "We decline one implementation choice, not a capability.",
           font=SANS_B(22), fill=INK)
    body = "Every functional outcome Model 4 lists is present: detection, tracking, ANPR where the camera can, search, trajectory, watchlist, alerts, evidence. The transport is what differs. Central ingest is the opposite of cost-effective use of existing infrastructure."
    yy = y + 68
    for line in wrap(d, body, SANS(18), W - ML - MR - 48):
        d.text((ML + 28, yy), line, font=SANS(18), fill=MUTED)
        yy += 24
    footer(d, "Do not read 160 Gbps or 52 PB as a test we ran. They are the reason we did not run that test.")
    return img


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
        "The test scenario, on this platform",
        "What the brief asks, and where it is",
        ["ASKED", "WHERE", "WHAT YOU WILL SEE"],
        [
            [("Onboard heterogeneous cameras", None),
             ("Cameras · Model 1 registry", None),
             ("30 of the issued grid. Mixed codec, resolution, department. Not 50, not 80.", None)],
            [("Centralised monitoring", None),
             ("Live wall · Model 2 stills", None),
             ("Ingest JPEGs ~1 Hz. Extra decode on click. A 30-tile WebRTC wall is 30 extra copies.", None)],
            [("AI-powered analytics", None),
             ("Edge T0–T2 · Analytics", None),
             ("Detection, tracking, ANPR with voting, person presence. No face identification.", None)],
            [("Identify and trace a designated mark", None),
             ("Investigate", None),
             ("GJ1VV0119 on cam07 (one camera). Own-feed GJ05AB1234 on C-014 and C-021.", None)],
            [("Complete route with timestamps", None),
             ("Trajectory legs", None),
             ("OBSERVED / UNOBSERVED / COVERAGE GAP. Timebase ALLOWED or REFUSED — never estimated.", None)],
            [("Watchlist + automated alerts", None),
             ("Alerts", None),
             ("Live: GJ38BH5815 stolen_vehicle HIGH on cam21. Own feed: GJ05AB1234 and GJ15NT6564.", None)],
            [("Scale toward 80,000", None),
             ("MODELLED on district nodes", None),
             ("Never quoted as tested. District edge + metadata to centre is the scale story.", None)],
        ],
        "Output report lives in the portal pack: detections CSV, overlay log, and the two films.",
        "08",
        col_w=[ML, ML + 480, ML + 860],
    )


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
    footer(d, "DINOv2 appearance ranking was measured unfit to lead (decoy 0.941 vs self 0.412). It does not.")
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
             ("Two diagrams as submitted, then the seven-step pipeline from camera to search.", None)],
            [("4. AI video analytics — detection, recognition, events", None),
             ("T0–T2 adaptive tiers. RT-DETRv2 + ByteTrack + voted ANPR. No face identification.", None)],
            [("5. Watchlist correlation and real-time alerts", None),
             ("Match at ingest, same transaction as the sighting. Representative watchlist, labelled.", None)],
            [("6. Key technologies, frameworks, and tools", None),
             ("PyAV, ONNX Runtime, FastAPI, SQLite to PostgreSQL, vanilla ES. Licences pinned.", None)],
            [("7. Scale, interoperability, security, deployment", None),
             ("District edge + metadata centre. Four auth gates. Continues with the uplink down.", None)],
            [("8. Operational benefits and impact on policing", None),
             ("An index answers a plate that nobody had asked for yet. Honest grades, not a fake wall.", None)],
        ],
        "Screenshots after the method slides are the running workspace on 15 Sep 2026. Headline numbers stay on the 6 Sep measured sheet.",
        "02",
        col_w=[ML, ML + 820],
    )


def objectives() -> Image.Image:
    img, d = canvas(False)
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
        ("Metadata, not video", "~400 B per observation to the centre. 19.3x smaller than the video we measured."),
        ("Match in one transaction", "Watchlist hit and sighting commit together, or neither does."),
        ("Graph before appearance", "DINOv2 was measured unfit to lead (margin −0.541). It does not."),
    ]
    cw = (W - ML - MR - 28) // 2
    for i, (head, body) in enumerate(innos):
        x = ML + (i % 2) * (cw + 28)
        yy = y + (i // 2) * 110
        d.rounded_rectangle((x, yy, x + cw, yy + 96), radius=8, outline=RULE, width=1)
        d.text((x + 20, yy + 16), head, font=SANS_B(18), fill=INK)
        for j, line in enumerate(wrap(d, body, SANS(16), cw - 40)):
            d.text((x + 20, yy + 48 + j * 22), line, font=SANS(16), fill=MUTED)
    footer(d, "Copilot is sixteen read-only tools over the same facade. It cannot invent a plate, a coordinate, or a shared timebase.")
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
    footer(d, "Every model passes an eight-check activation gate, including WEIGHTS against the pinned checkpoint. DINOv2 appearance ranks last — measured REJECTED as a lead.")
    return img


def watchlist_method() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "WATCHLIST", "12")
    kicker(d, "Correlation with watchlist databases and automated alerts")
    title(d, "Every plate read is checked. A hit is a row, not a toast.", y=84, size=36)
    steps = [
        ("1", "Post", "Plate, category, authority and reason. An entry with no stated authority cannot be created."),
        ("2", "Scope", "Versioned, jurisdiction-scoped, with expiry. Labelled REPRESENTATIVE — not a live government record."),
        ("3", "Match", "Ingest compares every voted plate to the active local watchlist. Continuous while cameras are open."),
        ("4", "Commit", "Alert and sighting write in the same transaction, or neither does. There is no “alert without evidence”."),
        ("5", "Alert", "OPEN, with decomposed confidence (plate × quality × category), recommended action, observation ids."),
        ("6", "Hold", "Acknowledge or dismiss is a status. No delete. Every transition is in the hash-chained audit log."),
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
    footer(d, "Demonstrated: GJ38BH5815 stolen_vehicle HIGH on cam21 (government grid). GJ05AB1234 and GJ15NT6564 on C-014 (own feed).")
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
             ("RT-DETRv2-R18 · ONNX Runtime", None),
             ("Apache-2.0. Vehicles, persons, two-wheelers. Ultralytics refused (AGPL).", None)],
            [("Tracking", None),
             ("ByteTrack, own implementation", None),
             ("Upstream is neither PTS-aware nor scene-cut-aware. Both matter here.", None)],
            [("Recognition (ANPR)", None),
             ("YOLO-v9-t plate + CCT-s OCR", None),
             ("Per-track vote. No face identification on government data.", None)],
            [("Store", None),
             ("SQLAlchemy · SQLite to PostgreSQL", None),
             ("One interface, two dialects. 18 tables. dedup_key makes offline replay safe.", None)],
            [("API", None),
             ("FastAPI + Uvicorn · 37 endpoints", None),
             ("OpenAPI generated from routes. Four authorisation gates on every call.", None)],
            [("Workspace", None),
             ("Vanilla ES modules, canvas map", None),
             ("No third-party asset. Runs with no internet route. Strict CSP is enforceable.", None)],
            [("Local replica", None),
             ("MediaMTX", None),
             ("Mirrors the organiser sandbox. Own-feed demonstration store.", None)],
        ],
        "Licence policy is enforced: the model router refuses a non-permissive licence. Appearance (DINOv2) is loaded, measured, and not used as a lead.",
        "13",
        col_w=[ML, ML + 380, ML + 860],
    )


def scale_security() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "DEPLOY", "14")
    kicker(d, "Scalability, interoperability, security, and deployment")
    title(d, "District edge does the work. The centre holds the index.", y=84, size=36)
    cards = [
        ("Scalability",
         "MEASURED: 30 government cameras on one host; 50 concurrent streams exercised. MODELLED: ~33 district nodes x 2,000-3,000 cameras. Metadata ~90-180 GB/day statewide with T0 gating — an ordinary database. 80,000-camera video is 160 Gbps / 52 PB and is not the plan."),
        ("Interoperability",
         "RTSP/TCP, HLS and WHEP. Mixed h264/hevc, 640×576 to 2560×1440, colour and IR. Adapters, not a replacement VMS. Government grid plus local MediaMTX. ONVIF-style metadata-first onboarding. Edge bundle export for disconnected nodes."),
        ("Security",
         "Four gates: authentication, role, jurisdiction, purpose. ADMIN cannot search. AUDITOR sees cameras, not what they saw. Watchlist read is purpose-bound. Evidence and audit are hash-chained. No face identification. Stream URLs never returned to investigators."),
        ("Deployment",
         "One codebase, three profiles (DEV_CPU, CLOUD_GPU, TARGET_GPU). Edge: ingest, analytics, local store, queue, watchlist, alerts, evidence. Centre: aggregation, cross-district search, GIS, audit. Continues with the uplink down. NATS/PostgreSQL at scale are designed; SQLite + HTTP is what ran."),
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
    footer(d, "PKI is not claimed. Integrity is content hashes, and every surface that reports them says so.")
    return img


def benefits() -> Image.Image:
    img, d = canvas(True)
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
          "Outage degrades reporting, never detection.",
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
           "Impact is a faster, checkable answer to “where did this vehicle go?”. It is not a claim of production readiness, legal admissibility, or a test at 80,000 cameras.",
           dark=True)
    return img


def measured() -> Image.Image:
    img, d = canvas(True)
    rail(img, d, "EVIDENCE", "21", dark=True)
    kicker(d, "Measured on the live government store  ·  6 Sep 2026 21:02 UTC", dark=True, y=56)
    title(d, "Every number here traces to a dated artefact", dark=True, y=92, size=40)
    rows = [
        ("Cameras onboarded / placed / listed", "30 / 19 / 11"),
        ("ANPR grades (from each camera’s stream)", "0 GOOD · 28 UNSUITABLE · 2 UNKNOWN"),
        ("Observations / person observations", "689,502 / 178,757"),
        ("Distinct marks / confirmed / leads", "69 / 74 / 43"),
        ("Exact cross-camera repeats", "0"),
        ("OCR-lookalike pair", "GJ32K5587 / GJ3ZK5587"),
        ("Cameras that published a mark / OCR attempts", "9 / 3,380"),
        ("Open alert", "GJ38BH5815  ·  cam21  ·  stolen_vehicle HIGH"),
        ("Search / trajectory on the live store", "3.4 ms / 1.5 ms"),
        ("Appearance (DINOv2) as a lead", "REJECTED  ·  margin −0.541"),
    ]
    y = 220
    d.line([(ML, y), (W - MR, y)], fill=(58, 62, 68), width=1)
    y += 20
    for label, val in rows:
        d.text((ML, y), label, font=SANS(20), fill=(176, 180, 186))
        d.text((ML + 820, y), val, font=SANS_B(20), fill=WHITE)
        y += 46
        d.line([(ML, y - 12), (W - MR, y - 12)], fill=(48, 52, 58), width=1)
    footer(d,
           "15 Sep 2026 workspace: store still growing; ANPR remains 0 GOOD. Do not mix the two dates into one headline.",
           dark=True)
    return img


def limits() -> Image.Image:
    img, d = canvas(False)
    rail(img, d, "CREDIBILITY", "22")
    kicker(d, "What we will not claim")
    title(d, "A proposal that lists only strengths cannot be checked", y=88, size=40)
    d.rectangle((ML, 210, ML + 64, 214), fill=SEAL)
    points = [
        "Not production ready. Not legally admissible. Not tested at 80,000 cameras.",
        "All 30 government cameras fall at or below ANPR grade. Yield is a property of geometry and light, not of enthusiasm.",
        "GJ1VV0119 is one camera (cam07), looping. That is not a multi-camera government route.",
        "Cross-camera plates on C-014 and C-021 are the own/synthetic store, labelled as such.",
        "Person boxes are presence. There is no face identification on government data.",
        "Own-feed footage is published with heads blurred from the person detector's boxes. A person it never found is not blurred.",
        "The GPU speed-up is measured on a laptop's integrated GPU. The target accelerator's is not quoted until it is run.",
        "Copilot is read-only. It will not enhance a still, invent a plate, or join clocks the timebase refuses.",
        "DINOv2 appearance ranking is measured unfit to lead. It is not shown as a tracker.",
        "Watchlist on the government grid is representative. One live alert: GJ38BH5815.",
    ]
    y = 240
    for p in points:
        d.text((ML, y), "■", font=SANS(16), fill=SEAL)
        yy = y
        for i, line in enumerate(wrap(d, p, SANS(22), W - ML - MR - 28)):
            d.text((ML + 28, yy), line, font=SANS(22), fill=INK)
            yy += 30
        y = yy + 14
    footer(d, "Saying this first is worth more than being asked. It is also what makes every other number in this deck checkable.")
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
                f"  ·  {'narrated, captioned' if audio else 'silent'}")
    except Exception:
        return "not rendered on this host"


def films() -> Image.Image:
    img, d = canvas(True)
    rail(img, d, "FILMS", "23", dark=True)
    kicker(d, "What to play, in this pack", dark=True, y=64)
    title(d, "Two films. One plate report. No mock-ups.", dark=True, y=108, size=44)
    cards = [
        ("own_feed.mp4  ·  own feed, under three minutes", _film_meta(ROOT / "var/demo/own_feed.mp4"),
         "Licensed Mumbai street footage, heads blurred. A camera onboarded through the registry "
         "form; live detection on the GPU; a plate read off the footage, searched; a fictional "
         "watchlist hit; the trace report; sealed evidence; the audit log."),
        ("government_feed.mp4 + ANPR report CSV", _film_meta(ROOT / "var/demo/government_feed.mp4"),
         "The government grid: live wall, detections drawn on the frame that produced them, plate "
         "reads with timestamps. The CSV lists every read the film shows."),
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
           "Only metadata moves. Video stays where it is. Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics.",
           dark=True)
    return img


def gpu_measured() -> Image.Image:
    """Only the hardware should be the bottleneck; this is the measurement."""
    import json
    det = json.loads((ROOT / "var/reports/detector_device.json").read_text())
    pipe = json.loads((ROOT / "var/reports/pipeline_device.json").read_text())
    return table_page(
        "Performance  ·  measured on the development laptop's GPU",
        "The software is not the bottleneck. The hardware is.",
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
             ("same observations, same plates" if pipe["same_plates"] and pipe["same_observation_count"]
              else "no", None)],
            [("A GPU sync per detected box", None), ("—", None), ("175 ms of 261", "red"),
             ("fixed", "gold"), ("software, not hardware: one copy per tensor now", None)],
        ],
        "tools/bench/detector_device.py · MEASURED · an integrated laptop GPU, not the target accelerator; "
        "the same command gives its row. Plate models stay on CPU (CoreML fails their dynamic shapes).",
        "21b",
        col_w=[ML, ML + 640, ML + 860, ML + 1120, ML + 1320],
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


def build() -> list[Image.Image]:
    pages = [
        cover(),
        agenda(),
        framing(),
        problem(),
        objectives(),
        hybrid(),
        model4(),
        bleed(DIAG / "05_hld_infographic.jpg",
              "Logical architecture",
              "Problem, principles, pipeline, models — one page",
              "Full diagram as submitted. Hybrid of Models 1 + 2 + 3, with selected-camera Model 4 analytics.",
              "08"),
        bleed(DIAG / "06_system_architecture.jpg",
              "System architecture",
              "Ingest → analytics → edge → store → investigation",
              "Code paths are the boxes: ingest/stream.py, analytics/, edge/, store/ (18 tables), intelligence through investigation.",
              "09"),
        pipeline(),
        analytics(),
        watchlist_method(),
        stack(),
        scale_security(),
        benefits(),
        scenario(),
        shot_page(SHOTS / "gov_overview.png",
                  "Workspace  ·  government grid  ·  15 Sep 2026",
                  "Overview is the shift picture, not a video wall",
                  "30 cameras, 0 ANPR-good, 1 open alert GJ38BH5815. Marks gallery is last published stills — not enhanced plates.",
                  "17"),
        shot_page(SHOTS / "gov_live_grid.png",
                  "Live wall  ·  Model 2 ingest stills",
                  "Thirty cameras. Detector boxes on the tiles that have them.",
                  "Each tile is the JPEG analytics already decoded. LIVE if under 2.5 s. ANPR UNSUITABLE is measured, not assumed.",
                  "18"),
        shot_page(SHOTS / "gov_live_twoup_boxes.jpg",
                  "Live  ·  two-up with detections",
                  "The same wall, four moving scenes, boxes drawn on the still",
                  "cam01 / cam02 / cam06 / street. Person and vehicle boxes are presence. ANPR remains UNSUITABLE on these views.",
                  "19"),
        four_shot(
            [DETECT / "gov_overlay_t32.jpg", DETECT / "gov_overlay_t52.jpg",
             DETECT / "gov_overlay_t64.jpg", DETECT / "gov_overlay_t76.jpg"],
            ["cam02 Janpath  ·  23 confirmed",
             "cam04 Paldi Circle  ·  bus, cars, people",
             "cam05 Visat teen Rasta  ·  34 confirmed",
             "cam12 Adalaj toll  ·  4 confirmed  ·  0 marks"],
            "Analytics overlay  ·  government clips",
            "Detection is drawn on the frame that produced it",
            "From government_feed overlay log. Night views publish 0 marks — the ANPR grade predicted that.",
            "20"),
        shot_page(SHOTS / "own_intel.png",
                  "Own feed  ·  licensed Mumbai street footage, 2560×1440",
                  "Every box is this platform's pipeline, on that exact frame",
                  "Heads blurred from the person detector's boxes — no face detector exists. Live AI plane figures are measured, on the GPU.",
                  "16"),
        shot_page(SHOTS / "own_find.png",
                  "Investigate  ·  designated vehicle (fictional plate)",
                  "GJ18JX7786: on the watchlist, said first. Then where it went.",
                  "Read at C-014, then C-021 five minutes later. Every read here is a single-frame lead, and the page says so. Cross-camera routes are claimed only on this store.",
                  "17"),
        shot_page(SHOTS / "gov_find_gj1vv0119.jpg",
                  "Investigate  ·  government grid",
                  "GJ1VV0119 — one camera, cam07, looping",
                  "Confirmed by plate. Two reads on cam07 are a pass, not a journey. Not a multi-camera government route.",
                  "18"),
        shot_page(SHOTS / "gov_find_lookalike.jpg",
                  "Investigate  ·  lookalike, not a match",
                  "6J1VV0119 is an OCR lookalike of GJ1VV0119",
                  "The platform says so instead of inventing a second camera. Exact cross-camera repeats on the 6 Sep sheet: 0.",
                  "19"),
        shot_page(SHOTS / "gov_alerts_film.jpg",
                  "Watchlist  ·  government grid",
                  "GJ38BH5815 on cam21 — stolen_vehicle HIGH",
                  "A hit is a row with a camera, not a video dump. Alert and sighting commit together, or neither does.",
                  "20"),
        shot_page(SHOTS / "own_alerts.png",
                  "Watchlist  ·  one decision per vehicle",
                  "Seven reads of one car are one incident, not seven cards",
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
                  "ANPR 28 UNSUITABLE, 2 UNKNOWN. That is the finding.",
                  "Grades are computed from each camera’s own stream. UNKNOWN means there is not yet enough evidence to grade.",
                  "21"),
        shot_page(SHOTS / "gov_map_film.jpg",
                  "Model 1  ·  estate map",
                  "19 on the map. 11 listed without coordinates. None invented.",
                  "OpenStreetMap tiles. Cameras without a surveyed position stay in the registry strip.",
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
        limits(),
        films(),
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
    pack = ROOT / "var/demo/PORTAL_PACK"
    pack.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, pack / "01_SAAKSHYA_deck.pdf")
    shutil.copy2(pptx, pack / "01_SAAKSHYA_deck.pptx")
    desktop = ROOT.parent
    shutil.copy2(out, desktop / "SAAKSHYA_deck.pdf")
    shutil.copy2(pptx, desktop / "SAAKSHYA_deck.pptx")
    print(f"pdf  : {display(out)} ({len(pages)} pages, {out.stat().st_size/1e6:.1f} MB)")
    print(f"pptx : {display(pptx)} ({pptx.stat().st_size/1e6:.1f} MB)")
    print(f"pack : {display(pack / '01_SAAKSHYA_deck.pptx')}")
    print(f"desk : {desktop / 'SAAKSHYA_deck.pptx'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
