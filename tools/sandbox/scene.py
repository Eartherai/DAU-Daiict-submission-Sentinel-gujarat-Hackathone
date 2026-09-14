"""Deterministic scene synthesis for the local sandbox replica.

Frames are rendered in Python and piped raw to FFmpeg rather than described as
an FFmpeg filter graph. Three reasons, in order of importance:

1. ``drawbox`` in the bundled FFmpeg build does not re-evaluate per-frame ``x``
   expressions, so filter-graph animation silently produced empty scenes. This
   was caught by inspecting rendered pixels rather than trusting the command to
   have worked.
2. Rendering here means we know the exact pixel box of every vehicle and every
   plate in every frame, so the corpus can carry **bounding-box ground truth**,
   not just "this plate appears on this camera". That makes the evaluation
   harness able to score detection, not only retrieval.
3. Degradation (blur, low light, glare) becomes a controlled, measurable knob
   instead of an opaque filter string — which matters because one camera has to
   be *hard but not impossible*, and that balance needs tuning against measured
   OCR yield.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


@dataclass
class VehiclePass:
    plate: str
    body_rgb: tuple[int, int, int]
    colour_name: str
    vtype: str
    t_enter: float
    duration: float
    direction: str = "LR"
    lane: int = 0
    scale: float = 1.0


@dataclass
class Degradation:
    """Controlled camera degradation. Each knob is independently measurable."""

    blur_sigma: float = 0.0
    brightness: float = 1.0     # multiplicative
    contrast: float = 1.0
    noise_sigma: float = 0.0
    glare_strength: float = 0.0  # 0..1 bright blob in upper area
    jpeg_like: int = 0           # 0 = off; else downscale/upscale factor


@dataclass
class SceneSpec:
    camera_id: str
    width: int
    height: int
    fps: int
    duration: float
    ground_rgb: tuple[int, int, int] = (44, 48, 55)
    road_rgb: tuple[int, int, int] = (60, 64, 70)
    passes: list[VehiclePass] = field(default_factory=list)
    degradation: Degradation = field(default_factory=Degradation)
    seed: int = 7


class SceneRenderer:
    """Renders one camera's looping clip and reports per-frame ground truth."""

    def __init__(self, spec: SceneSpec) -> None:
        self.s = spec
        self.rng = np.random.default_rng(spec.seed)
        self.horizon = int(spec.height * 0.42)
        self._bg = self._make_background()
        self._plate_font_cache: dict[int, ImageFont.FreeTypeFont] = {}

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._plate_font_cache:
            self._plate_font_cache[size] = find_font(size)
        return self._plate_font_cache[size]

    def _make_background(self) -> Image.Image:
        s = self.s
        img = Image.new("RGB", (s.width, s.height), s.ground_rgb)
        d = ImageDraw.Draw(img)
        # Road surface
        d.rectangle([0, self.horizon, s.width, s.height], fill=s.road_rgb)
        # Kerb
        d.rectangle([0, self.horizon, s.width, self.horizon + 3], fill=(86, 92, 100))
        # Lane markings
        mid = self.horizon + int((s.height - self.horizon) * 0.52)
        dash = max(18, s.width // 26)
        for x in range(0, s.width, dash * 2):
            d.rectangle([x, mid, x + dash, mid + max(2, s.height // 260)],
                        fill=(196, 200, 96))
        # A little static clutter so the scene is not perfectly flat
        for _ in range(9):
            x = int(self.rng.integers(0, s.width))
            y = int(self.rng.integers(0, self.horizon - 8))
            w = int(self.rng.integers(14, 48))
            h = int(self.rng.integers(8, 26))
            g = int(self.rng.integers(48, 78))
            d.rectangle([x, y, x + w, y + h], fill=(g, g + 3, g + 7))
        return img

    def _lane_y(self, lane: int, body_h: int) -> int:
        s = self.s
        band = s.height - self.horizon
        base = self.horizon + int(band * (0.34 + 0.26 * lane))
        return min(base, s.height - body_h - 4)

    def _draw_vehicle(
        self, d: ImageDraw.ImageDraw, p: VehiclePass, x: int, frame_w: int
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]] | None:
        s = self.s
        base_w = int(260 * p.scale * (s.width / 1280))
        base_h = int(140 * p.scale * (s.width / 1280))
        base_w, base_h = max(48, base_w), max(30, base_h)
        y = self._lane_y(p.lane, base_h)

        # Body
        d.rounded_rectangle([x, y, x + base_w, y + base_h],
                            radius=max(2, base_h // 9), fill=p.body_rgb)
        # Cabin / windscreen
        cw, ch = int(base_w * 0.46), int(base_h * 0.36)
        d.rounded_rectangle([x + int(base_w * 0.17), y + int(base_h * 0.08),
                             x + int(base_w * 0.17) + cw, y + int(base_h * 0.08) + ch],
                            radius=max(1, ch // 5), fill=(28, 32, 38))
        # Wheels
        wr = max(3, base_h // 6)
        for wx in (x + int(base_w * 0.22), x + int(base_w * 0.76)):
            d.ellipse([wx - wr, y + base_h - wr, wx + wr, y + base_h + wr],
                      fill=(20, 20, 22))
        # Plate. Real Indian single-row plates are ~500x120 mm, so ~4.2:1.
        # The font is *fitted* to the box rather than guessed: an earlier version
        # picked font size from plate height alone, which made 10-character
        # plates overflow the white backing onto the dark body. OCR then read
        # only the characters that happened to land on white — which looked
        # exactly like a model limitation and was not one.
        pw = int(base_w * 0.62)
        ph = max(8, int(pw / 4.2))
        px, py = x + int(base_w * 0.19), y + base_h - ph - max(3, base_h // 14)
        d.rectangle([px, py, px + pw, py + ph], fill=(238, 238, 232))
        d.rectangle([px, py, px + pw, py + ph], outline=(40, 40, 40), width=1)

        inner_w, inner_h = pw - 4, ph - 2
        fsize, font, tb = self._fit_font(d, p.plate, inner_w, inner_h)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tx = px + max(1, (pw - tw) // 2) - tb[0]
        ty = py + max(0, (ph - th) // 2) - tb[1]
        d.text((tx, ty), p.plate, fill=(16, 16, 16), font=font)

        body_box = (x, y, x + base_w, y + base_h)
        plate_box = (px, py, px + pw, py + ph)
        if x + base_w < 0 or x > frame_w:
            return None
        return body_box, plate_box

    def _fit_font(
        self, d: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int
    ) -> tuple[int, ImageFont.FreeTypeFont, tuple[int, int, int, int]]:
        """Largest font size whose rendered text fits inside the plate box.

        Guarantees the full registration mark is actually present in pixels, so
        a failed read is a genuine perception failure and not a rendering
        artefact. Without this the corpus silently tests the wrong thing.
        """
        lo, hi, best = 6, max(7, max_h * 2), None
        while lo <= hi:
            mid = (lo + hi) // 2
            f = self._font(mid)
            tb = d.textbbox((0, 0), text, font=f)
            if (tb[2] - tb[0]) <= max_w and (tb[3] - tb[1]) <= max_h:
                best = (mid, f, tb)
                lo = mid + 1
            else:
                hi = mid - 1
        if best is None:
            f = self._font(6)
            best = (6, f, d.textbbox((0, 0), text, font=f))
        return best

    def _degrade(self, img: Image.Image) -> Image.Image:
        g = self.s.degradation
        if g.jpeg_like > 1:
            w, h = img.size
            img = img.resize((max(1, w // g.jpeg_like), max(1, h // g.jpeg_like)),
                             Image.BILINEAR).resize((w, h), Image.BILINEAR)
        if g.blur_sigma > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=g.blur_sigma))
        a = np.asarray(img).astype(np.float32)
        if g.contrast != 1.0:
            a = (a - 128.0) * g.contrast + 128.0
        if g.brightness != 1.0:
            a *= g.brightness
        if g.glare_strength > 0:
            h, w = a.shape[:2]
            yy, xx = np.mgrid[0:h, 0:w]
            cx, cy = w * 0.66, h * 0.30
            r = np.sqrt(((xx - cx) / (w * 0.30)) ** 2 + ((yy - cy) / (h * 0.30)) ** 2)
            blob = np.clip(1.0 - r, 0, 1) ** 2 * (255.0 * g.glare_strength)
            a += blob[..., None]
        if g.noise_sigma > 0:
            a += self.rng.normal(0.0, g.noise_sigma, a.shape)
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    def frame(self, t: float) -> tuple[np.ndarray, list[dict]]:
        """Render one frame at time ``t``; return BGR array and its ground truth."""
        s = self.s
        img = self._bg.copy()
        d = ImageDraw.Draw(img)
        truth: list[dict] = []

        for p in s.passes:
            if not (p.t_enter <= t <= p.t_enter + p.duration):
                continue
            frac = (t - p.t_enter) / p.duration
            span = s.width + int(300 * (s.width / 1280))
            if p.direction == "LR":
                x = int(-int(260 * (s.width / 1280)) + span * frac)
            else:
                x = int(s.width - span * frac)
            boxes = self._draw_vehicle(d, p, x, s.width)
            if boxes is None:
                continue
            body, plate = boxes
            truth.append({
                "plate": p.plate, "colour": p.colour_name, "vehicle_type": p.vtype,
                "body_box": body, "plate_box": plate,
                "direction": p.direction,
            })

        img = self._degrade(img)
        rgb = np.asarray(img)
        return rgb[:, :, ::-1].copy(), truth  # BGR for the pipeline

    def measured_plate_legibility(self, t: float) -> float:
        """Contrast ratio inside the plate box after degradation.

        Used to *justify* the claim that a camera is or is not ANPR-viable,
        rather than asserting it. Returns 0..1.
        """
        bgr, truth = self.frame(t)
        if not truth:
            return 0.0
        x0, y0, x1, y1 = truth[0]["plate_box"]
        x0, y0 = max(0, x0), max(0, y0)
        crop = bgr[y0:y1, x0:x1]
        if crop.size == 0:
            return 0.0
        g = crop.mean(axis=2)
        return float(np.clip((g.max() - g.min()) / 255.0, 0.0, 1.0))
