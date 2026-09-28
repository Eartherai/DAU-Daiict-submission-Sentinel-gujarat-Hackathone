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
    #: Smaller type for the dense statewide pages; the renderer refuses any
    #: line that does not fit its box, so a small box cannot silently clip.
    small: bool = False

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
    #: Explicit waypoints, for pages too dense for the four routes above.
    path: list[tuple[int, int]] | None = None
    #: Label centre, when the midpoint of the route would sit on a box.
    at: tuple[int, int] | None = None
    #: Arrowheads at both ends: one line for a flow that runs both ways.
    both: bool = False


@dataclass
class Band:
    """A tier: a tinted column behind its nodes, named at the top."""
    x0: int
    y0: int
    x1: int
    y1: int
    label: str


def _facing(p: tuple[int, int], q: tuple[int, int]) -> str:
    if p[0] == q[0]:
        return "down" if q[1] > p[1] else "up"
    return "right" if q[0] > p[0] else "left"


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
         footer: str = "", bands: list[Band] | None = None) -> Image.Image:
    PAGE_TEXT.append("\n".join([title, subtitle,
        *[band.label for band in bands or []],
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

    for band in bands or []:
        d.rounded_rectangle([band.x0, band.y0, band.x1, band.y1], 8,
                            fill=(238, 241, 245), outline=(222, 227, 234), width=1)
        _text(d, (band.x0 + 12, band.y0 + 8), band.label, SANS_B(13), INK_2, spacing=1.6)

    # ── edges first, so a box always sits on top of its own connectors ──────
    for e in edges:
        a, b = by[e.a], by[e.b]
        col = INK_3 if e.dashed else (90, 102, 118)
        if e.path:
            pts = list(e.path)
            face = _facing(pts[-2], pts[-1])
        elif e.route == "h":
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
        if e.both:
            _arrow(d, pts[0], _facing(pts[1], pts[0]), col)

        if e.label:
            mid = pts[len(pts) // 2]
            lx = (pts[0][0] + pts[-1][0]) // 2 if e.route != "down" else mid[0]
            ly = (pts[0][1] + pts[-1][1]) // 2 if e.route != "down" else mid[1]
            if e.at:
                lx, ly = e.at
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
        pad = 14 if n.small else 20
        ty = n.y + (12 if n.small else 18)
        head = SANS_B(18) if n.small else SANS_B(22)
        for line in n.title.split("\n"):
            _fits(d, n, line, head, pad)
            d.text((n.x + pad, ty), line, font=head, fill=ink)
            ty += 23 if n.small else 28
        ty += 4 if n.small else 6
        sub = ink if n.kind == "edge" else INK_2
        for line in n.lines:
            f = (MONO(14) if n.small else MONO(16)) if line.startswith("·") else (
                SANS(15) if n.small else SANS(17))
            _fits(d, n, line, f, pad)
            d.text((n.x + pad, ty), line, font=f, fill=sub)
            ty += 19 if n.small else 24
        if n.small and ty > n.y + n.h:
            raise ValueError(f"node {n.id!r}: text runs past the bottom of its box")

    if footer:
        d.line([(70, H - 92), (W - 70, H - 92)], fill=RULE, width=1)
        for k, line in enumerate(footer.split("\n")):
            d.text((70, H - 74 + k * 26), line, font=SANS(19), fill=INK_2)
    return img


def _fits(d: ImageDraw.ImageDraw, n: Node, line: str, font, pad: int) -> None:
    if n.small and d.textlength(line, font=font) > n.w - 2 * pad:
        raise ValueError(f"node {n.id!r}: {line!r} is wider than its box")


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


# Statewide pages share one grid: five rows, and columns per tier.
_ROW = [290 + i * 132 for i in range(5)]
_RH = 104
_CW = 210
_COL = {"A": 70, "B1": 410, "B2": 680, "C": 1000, "D1": 1330, "D2": 1600}


def _sn(id_: str, col: str, row: int, title: str, lines: list[str], kind: str,
        rows: int = 1) -> Node:
    return Node(id_, _COL[col], _ROW[row - 1], _CW, _RH + (rows - 1) * 132, title, lines, kind, small=True)


def d_statewide() -> Image.Image:
    """Tiers, and what crosses between them. Video never leaves its tier."""
    cy = [y + _RH // 2 for y in _ROW]
    n = [
        _sn("cam_ip", "A", 1, "IP cameras", ["RTSP / ONVIF, main + sub", "26 departments", "keep recording to NVR"], "estate"),
        _sn("edge", "A", 2, "Site edge box", ["thin links only", "T0/T1, SQLite, queue", "only metadata leaves"], "edge"),
        _sn("cam_an", "A", 3, "Analog cameras", ["ONVIF encoder at site", "turns analog into RTSP"], "estate"),
        _sn("nvr", "A", 4, "NVR / VMS", ["video stays 7/15/30 days", "Profile G / VMS export"], "estate"),
        _sn("pvt", "A", 5, "Private cameras", ["public-facing, view-only", "consent; outbound link"], "estate"),
        _sn("c_ing", "B1", 1, "Ingest + decode", ["one session per camera", "sub-stream; main on", "ANPR-grade cameras"], "edge"),
        _sn("c_gpu", "B1", 2, "GPU pool (Triton)", ["T1 detect + track", "T2 plate, OCR, attributes", "batched"], "edge"),
        _sn("c_bus", "B1", 3, "Cell event bus", ["NATS JetStream, 3 nodes", "priority lanes", "store-and-forward"], "edge"),
        _sn("c_fed", "B1", 4, "VMS adapters", ["Model 3: one per", "departmental VMS"], "edge"),
        _sn("c_api", "B1", 5, "Cell API", ["district control room", "local alerts, evidence"], "edge"),
        _sn("c_note", "B2", 1, "Each cell", ["≤ 2,500 cameras or", "≤ 4,000 observations/s", "",
                                             "keeps detecting, matching,", "alerting and sealing", "with the WAN down"], "note", rows=2),
        _sn("c_db", "B2", 4, "Cell database", ["PostgreSQL + PostGIS", "30-day hot, sync standby", "rollups"], "store"),
        _sn("c_media", "B2", 5, "Media gateway", ["MediaMTX WHEP", "copy or transcode"], "edge"),
        _sn("r_obj", "C", 1, "Backups + mirror", ["WAL, base backups", "image + model mirror"], "store"),
        _sn("r_gpu", "C", 2, "Forensic GPU pool", ["T3 re-processing of", "NVR clips (selected", "Model 4)"], "centre"),
        _sn("r_sfu", "C", 5, "SFU + TURN", ["pulls once per camera,", "fans out to viewers"], "centre"),
        _sn("s_reg", "D1", 1, "Model 1 registry", ["+ GIS: source of truth", "for 80,000 cameras;", "replicated to cells"], "centre"),
        _sn("s_ext", "D1", 2, "Gov. DB adapters", ["VAHAN, SARATHI,", "eGujCop, AFIS, NAFIS", "(stubs refuse today)"], "gate"),
        _sn("s_kafka", "D1", 3, "State event bus", ["Kafka: plate-reads by", "folded plate; alerts,", "health, audit heads"], "centre"),
        _sn("s_lake", "D1", 4, "Observation lake", ["S3-compatible,", "erasure-coded; Trino"], "store"),
        _sn("s_api", "D1", 5, "State API", ["command centre; search,", "routes, designated", "vehicle"], "centre"),
        _sn("s_sec", "D2", 1, "Identity + policy", ["Keycloak OIDC, OPA,", "SPIRE, KMS"], "centre"),
        _sn("s_obs", "D2", 2, "Observability", ["Thanos, logs, SLOs,", "capacity panels"], "centre"),
        _sn("s_plate", "D2", 3, "Plate index", ["64 virtual hash shards", "on 4 PostgreSQL hosts"], "store"),
        _sn("s_worm", "D2", 4, "Evidence WORM", ["object lock; daily", "Merkle root of cell", "audit-chain heads"], "store"),
        _sn("dr", "D2", 5, "DR data centre", ["bus mirror, async", "replicas, lake replica"], "centre"),
    ]
    A, B1, B2, C, D1, D2 = (_COL[k] for k in ("A", "B1", "B2", "C", "D1", "D2"))
    e = [
        Edge("cam_ip", "c_ing", "RTSP pull"),
        Edge("cam_ip", "edge", "", "v"),
        Edge("edge", "c_bus", "metadata only", path=[(A + _CW, cy[1]), (320, cy[1]), (320, cy[2] - 16), (B1, cy[2] - 16)],
             at=(345, (cy[1] + cy[2]) // 2)),
        Edge("cam_an", "c_ing", "via encoder", path=[(A + _CW, cy[2] + 24), (370, cy[2] + 24), (370, cy[0] + 24), (B1, cy[0] + 24)],
             at=(345, cy[2] + 50)),
        Edge("nvr", "c_fed", "VMS API"),
        Edge("nvr", "r_gpu", "clip pull on request",
             path=[(A + _CW, cy[3] + 32), (300, cy[3] + 32), (300, _ROW[4] - 14), (1060, _ROW[4] - 14), (1060, _ROW[1] + _RH)],
             at=(640, _ROW[4] - 14)),
        Edge("pvt", "c_media", "consented view-only",
             path=[(A + _CW // 2, _ROW[4] + _RH), (A + _CW // 2, 946), (B2 + _CW // 2, 946), (B2 + _CW // 2, _ROW[4] + _RH)],
             at=(480, 946)),
        Edge("c_ing", "c_gpu", "frames", "v"),
        Edge("c_gpu", "c_bus", "observations", "v"),
        Edge("c_bus", "c_db", path=[(B1 + _CW, cy[2] + 24), (650, cy[2] + 24), (650, cy[3] - 18), (B2, cy[3] - 18)]),
        Edge("c_ing", "c_media", path=[(B1 + _CW, cy[0] + 38), (665, cy[0] + 38), (665, cy[4] + 10), (B2, cy[4] + 10)]),
        Edge("c_bus", "s_kafka", "plates · alerts · health · audit heads · deltas back",
             path=[(B1 + _CW, cy[2]), (D1, cy[2])], at=(985, cy[2]), both=True),
        Edge("c_db", "s_lake", "compressed micro-batches ≥ 1 min", at=(1110, cy[3])),
        Edge("c_db", "r_obj", "backups", path=[(B2 + _CW, cy[3] - 26), (945, cy[3] - 26), (945, cy[0]), (C, cy[0])],
             at=(945, (cy[0] + cy[1]) // 2 + 30)),
        Edge("c_media", "r_sfu", "viewing"),
        Edge("r_sfu", "s_api", "WebRTC"),
        Edge("s_api", "c_api", "scatter-gather search",
             path=[(D1 + _CW // 2, _ROW[4] + _RH), (D1 + _CW // 2, 968), (B1 + _CW // 2, 968), (B1 + _CW // 2, _ROW[4] + _RH)],
             at=(1180, 968)),
        Edge("s_ext", "s_kafka", "vehicle-keyed", "v"),
        Edge("s_kafka", "s_plate"),
        Edge("s_api", "s_plate", path=[(D1 + _CW, cy[4] - 10), (1570, cy[4] - 10), (1570, cy[2] + 24), (D2, cy[2] + 24)]),
    ]
    bottom = _ROW[4] + _RH + 8
    bands = [
        Band(A - 10, 256, A + _CW + 10, bottom, "CAMERA / SITE"),
        Band(B1 - 10, 256, B2 + _CW + 10, bottom, "DISTRICT CELL × 40"),
        Band(C - 10, 256, C + _CW + 10, bottom, "REGION × 6"),
        Band(D1 - 10, 256, D2 + _CW + 10, bottom, "STATE + DR"),
    ]
    return draw(
        "Statewide target architecture",
        "Video stays where it is recorded; metadata, events, requested clips and viewed streams move",
        n, e,
        "DESIGNED (docs/STATEWIDE_ARCHITECTURE.md §2–§6; HLD §3, §6, §21). Registry and watchlist deltas, DR mirroring and evidence replication are in the boxes.\n"
        "Only inference compute grows in proportion to cameras analysed (MODELLED, reports/capacity_model.json). Nothing here ran at 80,000 cameras.",
        bands)


def d_dataflow() -> Image.Image:
    """One vehicle, one read: from a frame to an alert, a route and the lake."""
    xs = [70 + i * 312 for i in range(6)]
    ys = [300, 500, 700]
    w, h = 220, 120

    def fn(id_: str, c: int, r: int, title: str, lines: list[str], kind: str, rows: int = 1) -> Node:
        return Node(id_, xs[c - 1], ys[r - 1], w, h + (rows - 1) * 200, title, lines, kind, small=True)

    n = [
        fn("f1", 1, 1, "Frame", ["sub-stream, or main on", "ANPR-grade cameras"], "estate"),
        fn("f2", 2, 1, "T0 motion gate", ["cheap, on the CPU"], "edge"),
        fn("f3", 3, 1, "T1 detect + track", ["RT-DETRv2, ByteTrack"], "edge"),
        fn("f4", 4, 1, "T2 plate + OCR", ["plate crop, OCR;", "vote: ≥ 2 frames agree"], "edge"),
        fn("f5", 5, 1, "Observation", ["dedup_key;", "1,331.7 B serialised", "(MEASURED)"], "centre"),
        fn("f14", 6, 1, "Bulk lane", ["compressed micro-batch", "≥ 1 min → state lake;", "154.0 B/row (MEASURED)"], "store"),
        fn("f6", 5, 2, "Cell store + match", ["cell database; local", "hashed-watchlist match"], "store"),
        fn("f7", 4, 2, "Incident", ["grouped per vehicle", "and watchlist entry"], "gate"),
        fn("f8", 3, 2, "Alert", ["district control room;", "p95 ≤ 5 s (target)"], "gate"),
        fn("f9", 2, 2, "Evidence sealed", ["hash chain, before", "acknowledgement"], "store"),
        fn("note", 1, 2, "Crosses the WAN", ["real-time lanes,", "compressed bulk,", "watchlist deltas.", "", "Never video."], "note", rows=2),
        fn("f16", 6, 2, "Hashed delta", ["< 1 min, WAN up;", "last valid bundle", "if the WAN is down"], "centre"),
        fn("f15", 6, 3, "Watchlist entry", ["at the state, e.g.", "DESIGNATED, with", "case and purpose"], "centre"),
        fn("f10", 5, 3, "Plate lane", ["Kafka plate-reads,", "keyed by folded plate"], "centre"),
        fn("f11", 4, 3, "Plate-index shard", ["one shard holds every", "read of that plate"], "store"),
        fn("f12", 3, 3, "Route builder", ["Camera Link Model"], "centre"),
        fn("f13", 2, 3, "Designated route", ["+ vehicle trace report,", "timestamped per place"], "centre"),
    ]
    mid = [y + h // 2 for y in ys]
    gap5 = xs[4] + w + (xs[5] - xs[4] - w) // 2
    e = [
        Edge("f1", "f2"), Edge("f2", "f3", "if motion"), Edge("f3", "f4"),
        Edge("f4", "f5", "at close"), Edge("f5", "f14", "always"),
        Edge("f5", "f6", "", "v"),
        Edge("f6", "f7", "hit"), Edge("f7", "f8"), Edge("f8", "f9"),
        Edge("f15", "f16", "", "v"), Edge("f16", "f6"),
        Edge("f5", "f10", "if plate confirmed",
             path=[(xs[4] + w, mid[0] + 32), (gap5, mid[0] + 32), (gap5, mid[2]), (xs[4] + w, mid[2])],
             at=(gap5, (ys[1] + h + ys[2]) // 2)),
        Edge("f10", "f11"), Edge("f11", "f12"), Edge("f12", "f13", "typed legs"),
    ]
    return draw(
        "Data flow — one vehicle, one read",
        "Detected and matched in the cell; the plate lane builds the route at the state; everything else goes to the lake",
        n, e,
        "Row size and compression MEASURED (var/reports/bandwidth.json, reports/measure_compression.json); two-frame vote VERIFIED (reports/anpr.py).\n"
        "Lanes, lake, plate index and SLOs are DESIGNED (docs/STATEWIDE_ARCHITECTURE.md §5, §6, §9, §18b).")


DIAGRAMS = {
    "01_logical_architecture": d_logical,
    "02_search_path": d_search,
    "03_evidence_chain": d_evidence,
    "04_camera_capability": d_capability,
    "05_statewide_architecture": d_statewide,
    "06_statewide_data_flow": d_dataflow,
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
        # The statewide pages carry several times the text of the others; the
        # layer is invisible, so it steps down in size rather than overflow.
        for size in (17, 12, 9, 7, 6, 5):
            remaining = page.insert_textbox(
                fitz.Rect(70, 100, W - 70, H - 70), page_text,
                fontname="DiagramText", fontsize=size, render_mode=3)
            if remaining >= 0:
                break
        else:
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
