"""Render the submission deck to PDF, from the same source the repository keeps.

The deck is generated from `docs/PPT_CONTENT.md` rather than drawn by hand, so
there is exactly one place a claim lives. A slide edited in a presentation tool
and never written back is how a deck ends up asserting a number the code stopped
producing three commits ago.

The status discipline the repository uses in prose is carried into the deck as
typography: **MEASURED**, **MODELLED**, **SIMULATED**, **DESIGNED** and **NOT
YET RUN** render as coloured chips. A reader can see at a glance which numbers
were observed and which were reasoned, without reading a footnote — and a claim
that carries no marking is visibly a claim that carries no marking.

    python tools/demo/render_deck.py --out var/demo/SAAKSHYA_deck.pdf

No presentation library is used. The pages are composed with the same drawing
code and palette as the demonstration video, which is why the deck, the video
and the console look like one system rather than three.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "demo"))

from render_demo_video import (
    INK,
    INK_2,
    MONO,
    NAVY,
    NAVY_2,
    SANS,
    SANS_B,
    SEAL,
    _font,
    _text,
    display,
)

#: Arial carries no Devanagari, so the script rendered as tofu boxes — on the
#: cover, in the product's own name. macOS ships a Devanagari face; it is asked
#: for by name, and the cover falls back to the Latin transliteration if the
#: deck is ever built on a host without one.
DEVA = lambda size: _font(("Devanagari Sangam MN.ttc", "DevanagariMT.ttc",  # noqa: E731
                           "ITFDevanagari.ttc", "Kohinoor.ttc"), size)


def _has_devanagari() -> bool:
    """Whether a real Devanagari face was found, rather than PIL's fallback."""
    return "path" in dir(DEVA(20))

W, H = 1920, 1080
MARGIN = 96
BODY_TOP = 248

PAPER = (247, 248, 250)
PAPER_INK = (17, 24, 33)
PAPER_INK_2 = (74, 85, 101)
RULE = (208, 214, 222)

#: Status markings, and the colour each is allowed. Measured is the only one
#: that gets the confident colour; everything else reads as provisional,
#: because that is what it is.
STATUS = {
    "MEASURED": ((15, 118, 110), (214, 239, 236)),
    "MODELLED": ((146, 97, 10), (250, 238, 208)),
    "SIMULATED": ((146, 97, 10), (250, 238, 208)),
    "DESIGNED": ((91, 100, 114), (228, 231, 236)),
    "UNTESTED": ((154, 44, 44), (246, 220, 220)),
    "NOT YET RUN": ((154, 44, 44), (246, 220, 220)),
    "NOT RUN": ((154, 44, 44), (246, 220, 220)),
}

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_CODE = re.compile(r"`([^`]+?)`")


def _spans(line: str) -> list[tuple[str, str]]:
    """Split a line into (style, text) runs. Styles: plain, bold, ital, code."""
    out: list[tuple[str, str]] = []
    i = 0
    pattern = re.compile(r"\*\*(.+?)\*\*|(?<!\*)\*([^*]+?)\*(?!\*)|`([^`]+?)`")
    for m in pattern.finditer(line):
        if m.start() > i:
            out.append(("plain", line[i:m.start()]))
        if m.group(1) is not None:
            out.append(("bold", m.group(1)))
        elif m.group(2) is not None:
            out.append(("ital", m.group(2)))
        else:
            out.append(("code", m.group(3)))
        i = m.end()
    if i < len(line):
        out.append(("plain", line[i:]))
    return out


def _wrap(d: ImageDraw.ImageDraw, spans: list[tuple[str, str]], fonts: dict,
          width: int) -> list[list[tuple[str, str]]]:
    """Greedy wrap over styled runs, so bold text wraps like any other."""
    lines: list[list[tuple[str, str]]] = [[]]
    x = 0.0
    for style, text in spans:
        f = fonts[style]
        for word in re.split(r"(\s+)", text):
            if not word:
                continue
            w = d.textlength(word, font=f)
            if x + w > width and word.strip() and lines[-1]:
                lines.append([])
                x = 0.0
                if not word.strip():
                    continue
            lines[-1].append((style, word))
            x += w
    return [ln for ln in lines if ln]


def _chip(d: ImageDraw.ImageDraw, xy: tuple[float, int], label: str,
          font) -> float:
    """A status marking, drawn as a chip. Returns the advance."""
    fg, bg = STATUS[label]
    x, y = xy
    w = d.textlength(label, font=font)
    d.rounded_rectangle([x, y - 2, x + w + 20, y + 30], 4, fill=bg)
    _text(d, (int(x + 10), y + 5), label, font, fg, spacing=1.0)
    return w + 26


def blocks(body: list[str]) -> list[tuple[str, str]]:
    """Group source lines into (kind, text) blocks.

    Markdown wraps a paragraph across several source lines, and inline emphasis
    is free to straddle those breaks. Rendering line by line therefore prints
    `**` literally wherever a bold run happened to cross a newline — which it
    did, on the slide carrying the capability numbers, turning the headline
    figure of the deck into visible asterisks. Blocks are joined before anything
    is parsed, so emphasis is matched over the whole paragraph.

    Quotes carry structure of their own. This source nests bullet lists inside
    blockquotes, and a parser that only strips the `>` runs three separate
    findings together into one wall of prose with stray hyphens in it. The
    inside of a quote is therefore parsed the same way as the outside.
    """
    out: list[tuple[str, str]] = []
    kind: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal kind, buf
        if kind and buf:
            joined = " ".join(x.strip() for x in buf).strip()
            if joined:
                out.append((kind, joined))
        kind, buf = None, []

    for raw in body:
        line = raw.rstrip()
        stripped = line.lstrip()

        if stripped.startswith(">"):
            inner = stripped[1:]
            if not inner.strip():          # `>` alone ends the sub-block
                flush()
                continue
            if re.match(r"^\s*[-*]\s+", inner):
                flush()
                kind = "quote-bullet"
                buf.append(re.sub(r"^\s*[-*]\s+", "", inner))
                continue
            if kind not in ("quote", "quote-bullet"):
                flush()
                kind = "quote"
            buf.append(inner)
            continue

        if not stripped:
            flush()
            continue
        img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if img:
            flush()
            out.append(("image", f"{img.group(1)}\n{img.group(2)}"))
            continue
        if re.match(r"^\s*[-*]\s+", line):
            flush()
            kind = "bullet"
            buf.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue
        if kind is None:
            kind = "para"
        buf.append(line)
    flush()
    return out


def draw_body(d: ImageDraw.ImageDraw, body: list[tuple[str, str]],
              top: int, canvas: Image.Image | None = None) -> int:
    """Render blocks from `top`. Returns how many were drawn.

    A block is measured before it is committed, and one that will not fit is
    left for the next page rather than run off the bottom. Overflowing text
    under the footer rule is the clearest possible signal that nobody looked at
    the output.
    """
    fonts = {"plain": SANS(30), "bold": SANS_B(30), "ital": SANS(30),
             "code": MONO(27)}
    chip_f = SANS_B(19)
    y = top
    width = W - 2 * MARGIN
    limit = H - 88
    drawn = 0

    for kind, raw in body:
        if kind == "image":
            cap, rel = raw.split("\n", 1)
            src = Path(rel)
            if not src.is_absolute():
                src = ROOT / src
            if not src.exists() or canvas is None:
                drawn += 1
                continue
            shot = Image.open(src).convert("RGB")
            max_w, max_h = width, min(820, limit - y - 28)
            if max_h < 80:
                break
            scale = min(max_w / shot.width, max_h / shot.height, 1.0)
            nw, nh = max(1, int(shot.width * scale)), max(1, int(shot.height * scale))
            shot = shot.resize((nw, nh), Image.Resampling.LANCZOS)
            canvas.paste(shot, (MARGIN, y))
            d.rectangle([MARGIN, y, MARGIN + nw, y + nh], outline=RULE, width=1)
            if cap.strip():
                d.text((MARGIN, y + nh + 8), cap.strip(),
                       font=SANS(19), fill=PAPER_INK_2)
                y += nh + 40
            else:
                y += nh + 16
            drawn += 1
            continue

        quoted = kind.startswith("quote")
        listed = kind.endswith("bullet")
        x0, avail = MARGIN, width
        if quoted or listed:
            x0, avail = MARGIN + 36, width - 36
        if quoted and listed:
            x0, avail = MARGIN + 72, width - 72

        text = raw
        chips = [m for m in STATUS if f"**{m}**" in text or f"({m}" in text]
        for m in chips:
            text = (text.replace(f"**{m}**", "").replace(f"({m} —", "(")
                        .replace(f"({m})", "").replace(f"*({m})*", ""))
        text = re.sub(r"\s{2,}", " ", text).strip()

        wrapped = _wrap(d, _spans(text), fonts, avail)
        if not wrapped:
            drawn += 1
            continue
        block_h = len(wrapped) * 44
        if y + block_h > limit and drawn:
            break                       # continue on the next page

        if quoted:
            d.rectangle([MARGIN, y - 2, MARGIN + 5, y + block_h - 8], fill=SEAL)
        if listed:
            bx = MARGIN + (45 if quoted else 9)
            d.ellipse([bx, y + 14, bx + 8, y + 22], fill=SEAL)

        for i, run_line in enumerate(wrapped):
            x = float(x0)
            for style, word in run_line:
                f = fonts[style]
                col = (PAPER_INK if style in ("bold", "code") or quoted
                       else PAPER_INK_2)
                d.text((x, y), word, font=f, fill=col)
                x += d.textlength(word, font=f)
            if i == len(wrapped) - 1:
                for m in chips:
                    x += 10
                    x += _chip(d, (x, y + 3), m, chip_f)
            y += 44
        y += 20
        drawn += 1
    return drawn


def slide(n: int, page: int, total: int, title: str,
          body: list[tuple[str, str]], cont: bool = False
          ) -> tuple[Image.Image, int]:
    """One page. Navy furniture, paper body — the same split as the console.

    Returns the page and how many blocks fitted on it, so a long slide can be
    continued rather than truncated or overflowed.
    """
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 96], fill=NAVY)
    d.ellipse([MARGIN - 60, 30, MARGIN - 24, 66], outline=SEAL, width=2)
    _text(d, (MARGIN - 8, 33), "SAAKSHYA", SANS_B(21), INK, spacing=3.0)
    _text(d, (MARGIN - 8, 60), "GUJARAT POLICE · CCTV INTELLIGENCE & EVIDENCE",
          SANS(12), INK_2, spacing=1.2)
    mark = "OFFICIAL · SENSITIVE"
    mw = d.textlength(mark, font=SANS_B(13))
    _text(d, (int(W - mw - MARGIN - 20), 41), mark, SANS_B(13), SEAL, spacing=1.4)

    d.text((MARGIN, 150), f"{n:02d}", font=MONO(30), fill=SEAL)
    head = f"{title} (cont.)" if cont else title
    size = 52 if d.textlength(head, font=SANS_B(52)) < W - 2 * MARGIN - 90 else 40
    d.text((MARGIN + 74, 142 + (0 if size == 52 else 8)), head,
           font=SANS_B(size), fill=PAPER_INK)
    d.line([(MARGIN, 244), (W - MARGIN, 244)], fill=RULE, width=1)

    fitted = draw_body(d, body, BODY_TOP, canvas=img)

    d.line([(MARGIN, H - 74), (W - MARGIN, H - 74)], fill=RULE, width=1)
    d.text((MARGIN, H - 58), "Gujarat Police Innovation Challenge 2026",
           font=SANS(19), fill=(140, 149, 161))
    # The marker beside the title is the *slide*; the footer is the *page*.
    # A continued slide keeps its number and advances the page, and conflating
    # the two printed "14 / 19" on two consecutive sheets.
    pg = f"{page} / {total}"
    pw = d.textlength(pg, font=MONO(19))
    d.text((W - pw - MARGIN, H - 58), pg, font=MONO(19), fill=(140, 149, 161))
    return img, fitted


def cover(total: int) -> Image.Image:
    """The cover. Navy throughout — it is the one page that is pure frame."""
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 150, W, H], fill=NAVY_2)

    d.ellipse([MARGIN, 250, MARGIN + 96, 346], outline=SEAL, width=3)
    _text(d, (MARGIN + 132, 258), "SAAKSHYA", SANS_B(76), INK, spacing=11.0)
    if _has_devanagari():
        d.text((MARGIN + 136, 344), "साक्ष्य", font=DEVA(30), fill=SEAL)
        _text(d, (MARGIN + 232, 352), "· EVIDENCE", SANS(26), SEAL, spacing=3.0)
    else:
        _text(d, (MARGIN + 136, 352), "SAAKSHYA · EVIDENCE", SANS(26), SEAL,
              spacing=3.0)
    d.line([(MARGIN, 430), (W - MARGIN, 430)], fill=SEAL, width=2)

    d.text((MARGIN, 470), "Federated CCTV Intelligence", font=SANS(54), fill=INK)
    d.text((MARGIN, 536), "and Evidence Fabric", font=SANS(54), fill=INK)
    d.text((MARGIN, 632), "Gujarat Police Innovation Challenge 2026",
           font=SANS(28), fill=INK_2)
    d.text((MARGIN, 682), "Hybrid of Models 1 + 2 + 3. Model 4 rejected on arithmetic.",
           font=SANS(24), fill=INK_2)

    _text(d, (MARGIN, H - 104), "OFFICIAL · SENSITIVE", SANS_B(15), SEAL, spacing=1.6)
    d.text((MARGIN, H - 74),
           "Every number in this deck is marked MEASURED, MODELLED or NOT YET RUN.",
           font=SANS(19), fill=INK_2)
    pg = f"{total} pages"
    pw = d.textlength(pg, font=MONO(19))
    d.text((W - pw - MARGIN, H - 74), pg, font=MONO(19), fill=INK_2)
    return img


def parse(md: str) -> list[tuple[str, list[str]]]:
    """Split the source into (title, body-lines) pairs, one per slide."""
    slides: list[tuple[str, list[str]]] = []
    title: str | None = None
    body: list[str] = []
    for line in md.splitlines():
        m = re.match(r"^##\s+(?:(\d+)\s*·\s*)?(.+)$", line)
        if m:
            if title is not None:
                slides.append((title, body))
            title, body = m.group(2).strip(), []
            continue
        if title is not None and line.strip() != "---":
            body.append(line)
    if title is not None:
        slides.append((title, body))
    # The trailing section is an editorial note to ourselves, not a slide.
    return [s for s in slides if not s[0].lower().startswith("numbers permitted")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", default="docs/PPT_CONTENT.md")
    ap.add_argument("--out", default="var/demo/SAAKSHYA_deck.pdf")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.exists():
        print(f"no such source: {src}", file=sys.stderr)
        return 2
    slides = parse(src.read_text())
    if not slides:
        print("no slides found in source", file=sys.stderr)
        return 2

    # Lay out once to learn the real page count, then again with it, so the
    # "n / total" footer is right on every page including continuations.
    def lay_out(total: int) -> list[Image.Image]:
        out: list[Image.Image] = [cover(total)]
        for idx, (title, raw) in enumerate(slides, start=1):
            pending = blocks(raw)
            cont = False
            while pending:
                img, fitted = slide(idx, len(out) + 1, total, title,
                                    pending, cont)
                out.append(img)
                # A block too tall for any page is dropped rather than looped
                # on forever; the run says nothing fitted, which is visible.
                pending = pending[fitted:] if fitted else pending[1:]
                cont = True
        return out

    pages = lay_out(len(slides) + 1)
    pages = lay_out(len(pages))
    total = len(pages)
    for i, (title, _) in enumerate(slides, start=1):
        print(f"  {i:2d}  {title}")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:],
                  resolution=150.0)

    # A PNG of each page too: the portal may want images, and a reviewer
    # skimming a directory should not have to open a PDF to see a slide.
    png_dir = out.with_suffix("")
    png_dir.mkdir(exist_ok=True)
    for i, p in enumerate(pages):
        p.save(png_dir / f"slide_{i:02d}.png")

    print(f"\ndeck   : {display(out)} ({total} pages, {out.stat().st_size/1e6:.1f} MB)")
    print(f"images : {display(png_dir)}/slide_NN.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
