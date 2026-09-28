"""Render the HLD architecture diagrams.

`docs/HLD.md` carries these as ASCII, which is right for a file that must stay
readable in a terminal and diffable in review. It is not right for a submission
that is read on a projector. These are the same structures, drawn.

Each diagram is declared as nodes and edges and laid out on an explicit grid.
Nothing is auto-arranged: a diagram whose boxes move when a label grows is a
diagram nobody can point at in a meeting.

    python tools/demo/render_diagrams.py --out var/demo/diagrams

Palette and type match the console, the deck and the demonstration video, so a
reader who has seen one recognises the others.
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from render_demo_video import MONO, SANS, SANS_B, SEAL, _text, display

W, H = 1920, 1080
# Searchable PDF text follows the exact strings drawn on each page.
PAGE_TEXT: list[str] = []
PAPER = (247, 248, 250)
INK = (17, 24, 33)
INK_2 = (74, 85, 101)
INK_3 = (128, 138, 152)
NAVY = (12, 33, 55)
RULE = (200, 207, 216)

#: Node kinds. The fill says what a thing *is*, so an estate box and a trust
#: boundary never have to be told apart by reading them.
KIND = {
    "estate":  ((233, 237, 243), (150, 163, 180), INK),
    "edge":    ((12, 33, 55), (12, 33, 55), (238, 242, 247)),
    "centre":  ((255, 255, 255), (120, 133, 150), INK),
    "store":   ((214, 239, 236), (15, 118, 110), (11, 74, 69)),
    "gate":    ((250, 238, 208), (146, 97, 10), (92, 61, 6)),
    "refuse":  ((246, 220, 220), (154, 44, 44), (110, 30, 30)),
    "note":    ((247, 248, 250), (208, 214, 222), INK_2),
}


@dataclass
class Node:
    id: str
    x: int
    y: int
    w: int
    h: int
    title: str
    lines: list[str] = field(default_factory=list)
    kind: str = "centre"

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclass
class Edge:
    a: str
    b: str
    label: str = ""
    #: "h" horizontal, "v" vertical, "down" below both boxes, "elbow" out then
    #: across then in. Two "h" edges leaving one box overlap exactly, because
    #: both are drawn at that box's centre line — so neither visibly reaches its
    #: target. "elbow" is what a fan-out needs.
    route: str = "h"
    dashed: bool = False
    drop: int = 0


def _dash_line(d: ImageDraw.ImageDraw, pts: list[tuple[int, int]],
               colour, width: int = 2, dash: int = 12) -> None:
    for (x1, y1), (x2, y2) in pairwise(pts):
        if x1 == x2:
            step = dash * 2 * (1 if y2 > y1 else -1)
            for y in range(y1, y2, step or 1):
                d.line([(x1, y), (x1, y + (dash if y2 > y1 else -dash))],
                       fill=colour, width=width)
        else:
            step = dash * 2 * (1 if x2 > x1 else -1)
            for x in range(x1, x2, step or 1):
                d.line([(x, y1), (x + (dash if x2 > x1 else -dash), y1)],
                       fill=colour, width=width)


def _arrow(d: ImageDraw.ImageDraw, at: tuple[int, int], facing: str,
           colour) -> None:
    x, y = at
    s = 9
    tip = {"right": [(x, y), (x - s, y - s), (x - s, y + s)],
           "left": [(x, y), (x + s, y - s), (x + s, y + s)],
           "down": [(x, y), (x - s, y - s), (x + s, y - s)],
           "up": [(x, y), (x - s, y + s), (x + s, y + s)]}[facing]
    d.polygon(tip, fill=colour)


def draw(title: str, subtitle: str, nodes: list[Node], edges: list[Edge],
         footer: str = "") -> Image.Image:
    PAGE_TEXT.append("\n".join([title, subtitle,
        *[text for node in nodes for text in [node.title, *node.lines]],
        *[edge.label for edge in edges if edge.label], footer]))
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    by = {n.id: n for n in nodes}

    d.rectangle([0, 0, W, 92], fill=NAVY)
    d.ellipse([70, 28, 106, 64], outline=SEAL, width=2)
    _text(d, (124, 31), "SAAKSHYA", SANS_B(20), (238, 242, 247), spacing=2.8)
    _text(d, (124, 58), "HIGH-LEVEL DESIGN", SANS(11), (157, 178, 201), spacing=1.4)
    mark = "OFFICIAL · SENSITIVE"
    mw = d.textlength(mark, font=SANS_B(12))
    _text(d, (int(W - mw - 90), 40), mark, SANS_B(12), SEAL, spacing=1.4)

    d.text((70, 132), title, font=SANS_B(44), fill=INK)
    if subtitle:
        d.text((70, 190), subtitle, font=SANS(23), fill=INK_2)
    d.line([(70, 240), (W - 70, 240)], fill=RULE, width=1)

    # ── edges first, so a box always sits on top of its own connectors ──────
    for e in edges:
        a, b = by[e.a], by[e.b]
        col = INK_3 if e.dashed else (90, 102, 118)
        if e.route == "h":
            y = a.cy
            x1, x2 = (a.x + a.w, b.x) if b.x > a.x else (a.x, b.x + b.w)
            pts = [(x1, y), (x2, y)]
            face = "right" if b.x > a.x else "left"
        elif e.route == "v":
            x = a.cx
            y1, y2 = (a.y + a.h, b.y) if b.y > a.y else (a.y, b.y + b.h)
            pts = [(x, y1), (x, y2)]
            face = "down" if b.y > a.y else "up"
        elif e.route == "elbow":
            x1 = a.x + a.w if b.x > a.x else a.x
            x2 = b.x if b.x > a.x else b.x + b.w
            mx = (x1 + x2) // 2
            pts = [(x1, a.cy), (mx, a.cy), (mx, b.cy), (x2, b.cy)]
            face = "right" if b.x > a.x else "left"
        else:  # "down" — route under both boxes and come back up
            yb = max(a.y + a.h, b.y + b.h) + e.drop
            pts = [(a.cx, a.y + a.h), (a.cx, yb), (b.cx, yb), (b.cx, b.y + b.h)]
            face = "up"

        if e.dashed:
            _dash_line(d, pts, col)
        else:
            d.line(pts, fill=col, width=2)
        _arrow(d, pts[-1], face, col)

        if e.label:
            mid = pts[len(pts) // 2]
            lx = (pts[0][0] + pts[-1][0]) // 2 if e.route != "down" else mid[0]
            ly = (pts[0][1] + pts[-1][1]) // 2 if e.route != "down" else mid[1]
            f = SANS(17)
            tw = d.textlength(e.label, font=f)
            d.rectangle([lx - tw / 2 - 8, ly - 13, lx + tw / 2 + 8, ly + 13],
                        fill=PAPER)
            d.text((lx - tw / 2, ly - 10), e.label, font=f, fill=INK_2)

    # ── nodes ──────────────────────────────────────────────────────────────
    for n in nodes:
        fill, border, ink = KIND[n.kind]
        d.rounded_rectangle([n.x, n.y, n.x + n.w, n.y + n.h], 5,
                            fill=fill, outline=border, width=2)
        ty = n.y + 18
        for line in n.title.split("\n"):
            d.text((n.x + 20, ty), line, font=SANS_B(22), fill=ink)
            ty += 28
        ty += 6
        sub = ink if n.kind == "edge" else INK_2
        for line in n.lines:
            f = MONO(16) if line.startswith("·") else SANS(17)
            d.text((n.x + 20, ty), line, font=f, fill=sub)
            ty += 24

    if footer:
        d.line([(70, H - 92), (W - 70, H - 92)], fill=RULE, width=1)
        for k, line in enumerate(footer.split("\n")):
            d.text((70, H - 74 + k * 26), line, font=SANS(19), fill=INK_2)
    return img


def d_logical() -> Image.Image:
    """The federation. Video stays where it is; metadata is what moves."""
    n = [
        Node("estate", 70, 320, 400, 300, "Camera estate", [
            "26 departments; five in sandbox", "Model 2: direct RTSP / ONVIF",
            "Model 3: departmental VMS", "via federation middleware",
            "· both register in Model 1"], "estate"),
        Node("edge", 610, 300, 430, 340, "District edge node", [
            "Decode · detect · track · ANPR",
            "Local store and queue",
            "Watchlist match · alerts",
            "Evidence sealing", "",
            "· departmental recording retained"], "edge"),
        Node("centre", 1180, 320, 400, 300, "Centre", [
            "Cross-district aggregation", "Search · camera graph · trajectory",
            "Evidence register · audit", "GIS and command picture", "",
            "· metadata only"], "centre"),
        Node("fallback", 610, 720, 430, 130, "Model 4 — selected central\nanalytics", [
            "Selected feeds through one gateway.",
            "The same pipeline, against a pulled stream."], "note"),
    ]
    e = [
        Edge("estate", "edge", "RTSP / HLS"),
        Edge("edge", "centre", "metadata"),
        # Routed below the fallback box, not through it: nodes are drawn after
        # edges, so a return path at the obvious height was hidden behind Model
        # 4 along with its label.
        Edge("centre", "edge", "watchlist bundles · fail closed", "down", drop=270),
        Edge("edge", "fallback", "", "v", dashed=True),
    ]
    return draw(
        "Logical architecture",
        "Compulsory Model 1 registry / GIS · Model 2 direct viewing · Model 3 VMS federation · Model 4 selected analytics",
        n, e,
        "Statewide central recording is declined: 80,000 × 2 Mbps = 160 Gbps (MODELLED, docs/SCALE_MODEL.md).\nDistrict deployment is DESIGNED; VMS connectors are DEMO/TEST pending departmental access (docs/ADAPTERS.md).")


def d_search() -> Image.Image:
    """Every search crosses four gates, and any one of them can refuse."""
    n = [
        Node("officer", 70, 400, 300, 180, "Officer", [
            "A registration mark,", "a case, and a stated purpose."], "estate"),
        Node("authn", 470, 300, 250, 150, "1 · Authentication", [
            "Who is asking?"], "gate"),
        Node("authz", 470, 500, 250, 150, "2 · Role", [
            "May they do this", "at all?"], "gate"),
        Node("juris", 800, 300, 250, 150, "3 · Jurisdiction", [
            "These cameras,", "in their scope?"], "gate"),
        Node("purpose", 800, 500, 250, 150, "4 · Purpose", [
            "Bound to a case,", "recorded verbatim."], "gate"),
        Node("query", 1150, 380, 300, 200, "Retrieval", [
            "Metadata index", "Camera graph", "Trajectory hypotheses"], "store"),
        Node("audit", 1150, 680, 300, 150, "Audit", [
            "Actor · role · purpose", "Hash-chained, append only"], "store"),
        Node("refuse", 470, 730, 580, 130, "Refusal is an answer", [
            "A gate that fails returns the reason, and the refusal is "
            "audited too."], "refuse"),
    ]
    e = [
        Edge("officer", "authn", route="elbow"),
        Edge("officer", "authz", route="elbow"),
        Edge("authn", "juris"), Edge("authz", "purpose"),
        Edge("juris", "query", route="elbow"),
        Edge("purpose", "query", route="elbow"),
        Edge("query", "audit", "", "v"),
        Edge("authz", "refuse", "", "v", dashed=True),
    ]
    return draw(
        "A search, end to end",
        "Four gates. Authentication, role, jurisdiction, and the purpose the "
        "search is bound to.",
        n, e,
        "Purpose binding is not a dialog dismissed once — it is standing "
        "furniture in the interface,\nand it is written into every audit "
        "record the search produces (VERIFIED, tests/security/).")


def d_evidence() -> Image.Image:
    """What makes a stored observation something to stand behind."""
    n = [
        Node("obs", 70, 340, 340, 240, "Observation", [
            "Camera · PTS · normalised time",
            "Box · class · confidence",
            "Mark, where one was read", "",
            "· one vehicle, seen once"], "centre"),
        Node("frame", 480, 340, 320, 240, "Retained frame", [
            "SHA-256 of the image",
            "Capture method recorded", "",
            "· kept only where retention",
            "  was actually performed"], "store"),
        Node("entry", 880, 300, 380, 320, "Chain entry", [
            "prev_hash", "entry_hash", "pipeline version",
            "model versions", "device · source quality", "",
            "· each entry seals the last"], "store"),
        Node("bsa", 1330, 340, 320, 240, "BSA s.63 certificate", [
            "Generated as", "DRAFT_PENDING_SIGNATURE.", "",
            "A signature is a human act;", "the system prepares, it does",
            "not certify."], "gate"),
        Node("verify", 480, 700, 780, 150, "Verification", [
            "Re-hash every entry and compare against its successor. A broken "
            "link is reported as broken —",
            "the interface never renders an unverified chain as a verified one."],
             "note"),
    ]
    e = [
        Edge("obs", "frame"), Edge("frame", "entry"), Edge("entry", "bsa"),
        Edge("entry", "verify", "", "down", drop=60),
    ]
    return draw(
        "Evidence chain",
        "Hash-chained, append-only, and honest about what it is not",
        n, e,
        "A hash verifies unchanged bytes, not plate-to-image identity: older track-close stills can show a different vehicle.\n"
        "Verify against source footage (docs/HLD.md §4.6). The certificate remains a draft, not a court determination.")


def d_capability() -> Image.Image:
    """Why the platform grades cameras instead of assuming they are equal."""
    n = [
        Node("stream", 70, 360, 330, 220, "The camera's own stream", [
            "Not the catalogue's claim.", "",
            "· plate pixel width", "· sharpness · luminance",
            "· channel spread"], "estate"),
        Node("grade", 470, 320, 360, 300, "Graded per band", [
            "ALL · DAY · LOW LIGHT · NIGHT", "",
            "GOOD — will carry a claim",
            "DEGRADED — will, with care",
            "UNSUITABLE — will not", "",
            "UNKNOWN — not yet enough", "evidence to say"], "centre"),
        Node("good", 900, 300, 330, 150, "Search uses it", [
            "The camera can support", "the claim being made."], "store"),
        Node("unsuit", 900, 490, 330, 150, "Search says why not", [
            "Absence of a result is", "reported, not implied."], "gate"),
        Node("unknown", 1300, 380, 340, 230, "UNKNOWN is first class", [
            "Source availability can change",
            "between measurement windows.", "",
            "A single sample is not a verdict."], "note"),
    ]
    e = [
        Edge("stream", "grade", "measured"),
        Edge("grade", "good", route="elbow"),
        Edge("grade", "unsuit", route="elbow"),
        Edge("grade", "unknown", "", "h"),
    ]
    return draw(
        "Camera capability",
        "Measured from the stream, per camera, per time band",
        n, e,
        "Grades describe the sampled camera and time band, not an estate-wide guarantee.\n"
        "Historical capability results: docs/MEASURED_RESULTS.md; current policy: docs/HLD.md.")


DIAGRAMS = {
    "01_logical_architecture": d_logical,
    "02_search_path": d_search,
    "03_evidence_chain": d_evidence,
    "04_camera_capability": d_capability,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="var/demo/diagrams")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    PAGE_TEXT.clear()
    pages = []
    for name, fn in DIAGRAMS.items():
        img = fn()
        img.save(out / f"{name}.png")
        pages.append(img)
        print(f"  {name}.png")

    pdf = out / "HLD_diagrams.pdf"
    # Same PDF dependency used by the submission-deck renderer. The visible
    # page remains the approved raster; an invisible text layer makes its
    # labels searchable and independently extractable for pack consistency.
    import pymupdf as fitz

    document = fitz.open()
    for img, page_text in zip(pages, PAGE_TEXT, strict=True):
        page = document.new_page(width=W, height=H)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
        font_path = SANS(17).path
        page.insert_font(fontname="DiagramText", fontfile=font_path)
        remaining = page.insert_textbox(
            fitz.Rect(70, 100, W - 70, H - 70), page_text,
            fontname="DiagramText", fontsize=17, render_mode=3)
        if remaining < 0:
            raise ValueError("PDF text layer overflow")
    # Without these the PDF stored each page raster as an uncompressed pixmap
    # and the whole font four times: 25.7 MB for four pages that were 465 KB.
    document.subset_fonts()
    document.save(pdf, garbage=3, deflate=True)
    document.close()
    print(f"\ndiagrams: {display(out)}/*.png")
    print(f"combined: {display(pdf)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
