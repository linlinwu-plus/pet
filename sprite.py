"""Render the desktop pet with Pillow.

All geometry is authored in a 260 x 360 logical box and scaled up for the
actual window / DPI.  Frames are supersampled and box-filtered down, which
gives clean anti-aliased edges without extra runtime dependencies.

Several built-in "models" (skins) share the same body silhouette and differ in
palette, ears, tail and face details.  A custom PNG can be used as well.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------
OUTLINE = (76, 58, 49, 255)
CREAM = (247, 232, 210, 255)
CREAM_SHADE = (238, 220, 194, 255)
WHITE = (255, 251, 244, 255)
LATTE = (205, 174, 140, 255)
LATTE_SOFT = (226, 203, 174, 255)
PINK = (244, 168, 168, 255)
BLUSH = (246, 201, 190, 255)
EYE = (57, 42, 36, 255)
TONGUE = (240, 148, 148, 255)
MOUTH = (122, 66, 62, 255)
WHISKER = (196, 172, 148, 255)
HEART = (244, 137, 148, 255)
NOTE = (150, 112, 190, 255)

LOGICAL_W, LOGICAL_H = 260, 360
CAT_DY = 20          # pushes the cat down to leave room for speech bubbles
SHADOW_Y = 318


def _rgba(c) -> tuple[int, int, int, int]:
    return (c[0], c[1], c[2], 255) if len(c) == 3 else c


@dataclass(frozen=True)
class Skin:
    key: str
    name: str
    kind: str                    # cat | dog | bunny | panda
    fur: tuple
    shade: tuple
    belly: tuple
    ear: tuple
    inner: tuple
    blush: tuple
    outline: tuple
    tail_tip: tuple
    whisker: tuple | None = None

    def rgba(self) -> "SkinRGBA":
        return SkinRGBA(
            kind=self.kind,
            fur=_rgba(self.fur),
            shade=_rgba(self.shade),
            belly=_rgba(self.belly),
            ear=_rgba(self.ear),
            inner=_rgba(self.inner),
            blush=_rgba(self.blush),
            outline=_rgba(self.outline),
            tail_tip=_rgba(self.tail_tip),
            whisker=_rgba(self.whisker) if self.whisker else None,
        )


@dataclass(frozen=True)
class SkinRGBA:
    kind: str
    fur: tuple
    shade: tuple
    belly: tuple
    ear: tuple
    inner: tuple
    blush: tuple
    outline: tuple
    tail_tip: tuple
    whisker: tuple | None


SKINS: dict[str, Skin] = {}


def _add_skin(skin: Skin) -> None:
    SKINS[skin.key] = skin


_add_skin(Skin("cream_cat", "奶油猫", "cat",
               (247, 232, 210), (238, 220, 194), (255, 251, 244),
               (205, 174, 140), (244, 168, 168), (246, 201, 190),
               (76, 58, 49), (205, 174, 140), (196, 172, 148)))
_add_skin(Skin("mocha_cat", "煤球猫", "cat",
               (150, 128, 118), (128, 108, 100), (242, 233, 224),
               (108, 90, 84), (240, 176, 176), (238, 186, 180),
               (58, 46, 42), (108, 90, 84), (196, 172, 158)))
_add_skin(Skin("puppy", "布丁狗", "dog",
               (246, 203, 132), (230, 184, 112), (255, 248, 230),
               (204, 154, 88), (246, 178, 166), (247, 190, 168),
               (92, 64, 42), (204, 154, 88), None))
_add_skin(Skin("bunny", "棉花兔", "bunny",
               (250, 245, 240), (232, 224, 220), (255, 255, 255),
               (240, 218, 218), (248, 188, 196), (250, 196, 202),
               (122, 104, 106), (250, 245, 240), None))
_add_skin(Skin("panda", "熊猫", "panda",
               (250, 248, 244), (230, 226, 222), (255, 255, 255),
               (58, 54, 56), (120, 112, 114), (247, 202, 202),
               (52, 46, 48), (58, 54, 56), None))


@dataclass
class Pose:
    """Everything the renderer needs to know about the current frame."""

    state: str = "idle"          # idle | walk | eat | happy | sleep | drag | action
    t: float = 0.0
    walk_phase: float = 0.0
    facing: int = 1
    blink: float = 0.0
    look: float = 0.0
    mouth: float = 0.0
    eat_frac: float = 1.0
    happy: float = 0.0
    action: str = ""
    hop: float = 0.0             # logical px lifted off the ground
    squash: float = 1.0          # 1 = normal, <1 squashed at the feet
    spin: float = 0.0            # degrees around the vertical axis
    tail_wag: float = 0.0        # -1..1 extra tail swing
    notes: float = 0.0           # 0..1 music notes around the head


class Painter:
    """Draw helper that scales logical coordinates by ``k``."""

    def __init__(self, image: Image.Image, k: float, dy: float = 0.0):
        self.k = k
        self.dy = dy
        self.d = ImageDraw.Draw(image)

    def _box(self, box):
        x0, y0, x1, y1 = box
        return [x0 * self.k, (y0 + self.dy) * self.k,
                x1 * self.k, (y1 + self.dy) * self.k]

    def _pts(self, pts):
        return [(x * self.k, (y + self.dy) * self.k) for x, y in pts]

    def _width(self, width):
        return max(1, int(round(width * self.k)))

    def ellipse(self, box, fill=None, outline=None, width=0):
        self.d.ellipse(self._box(box), fill=fill, outline=outline,
                       width=self._width(width) if width else 0)

    def polygon(self, pts, fill=None, outline=None, width=0):
        self.d.polygon(self._pts(pts), fill=fill, outline=outline,
                       width=self._width(width) if width else 0)

    def line(self, pts, fill, width=1, joint="curve"):
        self.d.line(self._pts(pts), fill=fill, width=self._width(width), joint=joint)

    def rounded(self, box, radius, fill=None, outline=None, width=0):
        self.d.rounded_rectangle(self._box(box), radius=radius * self.k,
                                 fill=fill, outline=outline,
                                 width=self._width(width) if width else 0)

    def arc(self, box, start, end, fill, width=1):
        self.d.arc(self._box(box), start, end, fill=fill, width=self._width(width))


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _bezier(p0, p1, p2, p3, n=22):
    pts = []
    for i in range(n + 1):
        u = i / n
        a = (1 - u) ** 3
        b = 3 * (1 - u) ** 2 * u
        c = 3 * (1 - u) * u ** 2
        e = u ** 3
        pts.append((
            a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
            a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1],
        ))
    return pts


@lru_cache(maxsize=16)
def _font(px: int, bold: bool = True):
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    try:
        return ImageFont.truetype(f"C:/Windows/Fonts/{name}", px)
    except OSError:
        return ImageFont.load_default()


def _heart(p: Painter, cx, cy, size, color=HEART):
    # two round lobes on top of a soft triangle
    r = size * 0.29
    lobe_y = cy - size * 0.18
    p.ellipse((cx - size * 0.48 - r, lobe_y - r * 1.05,
               cx - size * 0.48 + r, lobe_y + r * 0.95), fill=color)
    p.ellipse((cx + size * 0.48 - r, lobe_y - r * 1.05,
               cx + size * 0.48 + r, lobe_y + r * 0.95), fill=color)
    p.polygon([
        (cx - size * 0.76, lobe_y + r * 0.15),
        (cx + size * 0.76, lobe_y + r * 0.15),
        (cx, cy + size * 0.62),
    ], fill=color)


def _shadow(p: Painter, squash: float = 1.0, alpha: int = 46):
    p.ellipse((76, SHADOW_Y - 9, 184, SHADOW_Y + 12), fill=(60, 45, 38, alpha))
    p.ellipse((88, SHADOW_Y - 6, 172, SHADOW_Y + 7), fill=(60, 45, 38, 40 * alpha // 46))
    p.ellipse((100, SHADOW_Y - 3, 160, SHADOW_Y + 3), fill=(60, 45, 38, 34 * alpha // 46))


def _apply_motion(img: Image.Image, pose: Pose) -> Image.Image:
    """Squash-at-the-feet and Y-axis twirl, applied to a finished frame."""
    w, h = img.size
    spin = pose.spin % 360.0
    if abs(spin) > 1.0:
        a = math.radians(spin)
        mirror = math.cos(a) < 0
        sw = max(0.06, abs(math.cos(a)))
        src = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if mirror else img
        nw = max(1, int(round(w * sw)))
        shrink = src.resize((nw, h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(shrink, ((w - nw) // 2, 0))
        img = canvas
    if abs(pose.squash - 1.0) > 0.01:
        nh = max(1, int(round(h * pose.squash)))
        sq = img.resize((w, nh), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        canvas.alpha_composite(sq, (0, h - nh))
        img = canvas
    return img


def _draw_notes(img: Image.Image, pose: Pose, head_cx: float, head_cy: float,
                scale: float) -> None:
    """Music notes floating up around the head (final-resolution overlay)."""
    if pose.notes <= 0.01:
        return
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    t = pose.t
    for i in range(3):
        frac = (t * 0.85 + i * 0.33) % 1.0
        alpha = int(235 * (1.0 - frac) * min(1.0, pose.notes))
        if alpha <= 4:
            continue
        side = -1 if i % 2 == 0 else 1
        x = (head_cx + side * (58 + i * 8) + math.sin(t * 3 + i) * 6) * scale
        y = (head_cy - 40 - frac * 70 + CAT_DY) * scale
        size = (17 + 5 * (1 - frac)) * scale
        color = (150, 112, 190, alpha)
        # note head
        rx, ry = size * 0.30, size * 0.24
        ld.ellipse([x - rx, y - ry, x + rx, y + ry], fill=color)
        # stem
        ld.line([(x + rx * 0.72, y - ry * 0.2), (x + rx * 0.72, y - size * 0.85)],
                fill=color, width=max(2, int(size * 0.13)))
        # flag
        ld.line([(x + rx * 0.72, y - size * 0.85),
                 (x + rx * 0.72 + size * 0.34, y - size * 0.62)],
                fill=color, width=max(2, int(size * 0.13)))
    img.alpha_composite(layer)


# --------------------------------------------------------------------------
# main sprite
# --------------------------------------------------------------------------
def render_cat(pose: Pose, scale: float = 1.0, ss: int = 2,
               skin: Skin | None = None) -> Image.Image:
    """Return an RGBA frame of size (LOGICAL_W*scale, LOGICAL_H*scale)."""
    s = (skin or SKINS["cream_cat"]).rgba()
    fur, belly, ear, inner = s.fur, s.belly, s.ear, s.inner
    outline, blush, shade = s.outline, s.blush, s.shade
    kind = s.kind
    k = scale * ss
    img = Image.new("RGBA", (int(LOGICAL_W * k), int(LOGICAL_H * k)), (0, 0, 0, 0))
    p = Painter(img, k, CAT_DY)

    t = pose.t
    walk = pose.state == "walk"
    eating = pose.state == "eat"
    sleeping = pose.state == "sleep"
    dragging = pose.state == "drag"
    acting = pose.state == "action"
    happy_state = pose.state == "happy"
    joyful = happy_state or (acting and pose.action in ("dance", "hop", "roll"))
    happy = joyful

    # ---------------- motion parameters ----------------
    phase = pose.walk_phase * math.tau
    step = abs(math.sin(phase))
    if walk:
        bob = -step * 4.5
        sway = math.sin(phase) * 2.4
    elif happy_state:
        bob = -abs(math.sin(t * 9.0)) * 7.0
        sway = 0.0
    elif acting:
        bob = math.sin(t * 6.0) * 2.0
        sway = math.sin(t * 9.0) * 2.0 if pose.action == "dance" else 0.0
    elif dragging:
        bob = math.sin(t * 6.0) * 1.6 - 3
        sway = math.sin(t * 4.0) * 2.0
    elif sleeping:
        bob = math.sin(t * 1.0) * 1.4
        sway = 0.0
    else:
        bob = math.sin(t * 1.7) * 1.1
        sway = 0.0

    bob -= pose.hop
    breathe = math.sin(t * 1.7) * (0.6 if walk else 1.3)
    cx = 130 + sway
    body_cy = 257 + bob
    head_cy = 176 + bob * 1.15 + (7 if sleeping else 0) + (3 if eating else 0)
    head_cx = cx + (1.5 if walk else 0)

    # ---------------- shadow ----------------
    _shadow(p)

    # ---------------- tail ----------------
    tail_sway = math.sin(t * (2.1 if not acting else 6.5)) * (9 if walk else 5)
    tail_sway += pose.tail_wag * 14
    if kind in ("cat",):
        tip_y = 230 + tail_sway * 0.5 - (6 if happy else 0)
        tail_pts = _bezier(
            (cx + 42, body_cy + 30),
            (cx + 92, body_cy + 34),
            (cx + 108, body_cy - 14),
            (cx + 84, tip_y),
        )
        p.line(tail_pts, outline, width=19)
        p.line(tail_pts, fur, width=13)
        p.line(tail_pts[-5:], s.tail_tip, width=13)
        p.ellipse((cx + 78, tip_y - 6, cx + 90, tip_y + 6), fill=s.tail_tip)
        p.ellipse((cx + 78, tip_y - 6, cx + 90, tip_y + 6), outline=outline, width=2.4)
    elif kind == "dog":
        tip_y = body_cy - 20 + tail_sway * 0.7
        tail_pts = _bezier(
            (cx + 40, body_cy + 22),
            (cx + 82, body_cy + 20),
            (cx + 98, body_cy - 4),
            (cx + 78, tip_y),
        )
        p.line(tail_pts, outline, width=16)
        p.line(tail_pts, fur, width=11)
        p.line(tail_pts[-4:], s.tail_tip, width=11)
    elif kind == "bunny":
        p.ellipse((cx + 40, body_cy + 22, cx + 66, body_cy + 46),
                  fill=belly, outline=outline, width=3)
    else:  # panda
        p.ellipse((cx + 40, body_cy + 18, cx + 64, body_cy + 40),
                  fill=ear, outline=outline, width=3)

    # ---------------- hind feet ----------------
    for side in (-1, 1):
        fx = cx + side * 30
        p.ellipse((fx - 23, 286 + bob * 0.2, fx + 23, 308 + bob * 0.2),
                  fill=fur, outline=outline, width=3)

    # ---------------- body ----------------
    body_ry = 52 + breathe
    p.ellipse((cx - 53, body_cy - body_ry, cx + 53, body_cy + body_ry),
              fill=fur, outline=outline, width=3.4)
    p.ellipse((cx - 32, body_cy + 8, cx + 32, body_cy + 47), fill=belly)

    # ---------------- front paws ----------------
    for i, side in enumerate((-1, 1)):
        px = cx + side * 13
        lift = 0.0
        if walk:
            lift = max(0.0, math.sin(phase + (0 if side < 0 else math.pi))) * 5
        if dragging:
            lift = 8 + math.sin(t * 8 + i) * 2
        if acting and pose.action == "dance":
            lift = max(0.0, math.sin(t * 10 + i * 2.2)) * 10
        p.ellipse((px - 15, 289 - lift, px + 15, 308 - lift),
                  fill=belly, outline=outline, width=3)
        p.line([(px - 5, 301 - lift), (px - 5, 305 - lift)], shade, width=1.6)
        p.line([(px + 1, 302 - lift), (px + 1, 306 - lift)], shade, width=1.6)

    # ---------------- ears (behind the head) ----------------
    ear_drop = 6 if dragging else 0
    if kind == "cat":
        left_outer = [(70, 132 + ear_drop), (80, 70 + ear_drop), (124, 106 + ear_drop)]
        right_outer = [(190, 132 + ear_drop), (180, 70 + ear_drop), (136, 106 + ear_drop)]
        p.polygon(left_outer, fill=ear, outline=outline, width=3.4)
        p.polygon(right_outer, fill=fur, outline=outline, width=3.4)
        p.polygon([(82, 118 + ear_drop), (89, 86 + ear_drop), (114, 106 + ear_drop)],
                  fill=inner)
        p.polygon([(178, 118 + ear_drop), (171, 86 + ear_drop), (146, 106 + ear_drop)],
                  fill=inner)
    elif kind == "dog":
        for side in (-1, 1):
            ecx = head_cx + side * 63
            p.ellipse((ecx - 27, head_cy - 60 + ear_drop, ecx + 25, head_cy + 36 + ear_drop),
                      fill=ear, outline=outline, width=3.2)
            p.ellipse((ecx - 14, head_cy - 42 + ear_drop, ecx + 12, head_cy + 16 + ear_drop),
                      fill=inner)
    elif kind == "bunny":
        for side in (-1, 1):
            ecx = head_cx + side * 30
            p.ellipse((ecx - 21, head_cy - 100 + ear_drop, ecx + 21, head_cy - 38 + ear_drop),
                      fill=fur, outline=outline, width=3.2)
            p.ellipse((ecx - 11, head_cy - 88 + ear_drop, ecx + 11, head_cy - 50 + ear_drop),
                      fill=inner)
    else:  # panda
        for side in (-1, 1):
            ecx = head_cx + side * 44
            p.ellipse((ecx - 26, head_cy - 84 + ear_drop, ecx + 26, head_cy - 32 + ear_drop),
                      fill=ear, outline=outline, width=3.2)

    # ---------------- head ----------------
    p.ellipse((head_cx - 66, head_cy - 63, head_cx + 66, head_cy + 63),
              fill=fur, outline=outline, width=3.6)

    # forehead stripes / cheek fluff (cats only)
    if kind == "cat":
        for dx in (-9, 0, 9):
            p.line([(head_cx + dx, head_cy - 55), (head_cx + dx + 1, head_cy - 43)],
                   fill=shade, width=3.2)
        p.polygon([(head_cx - 62, head_cy + 12), (head_cx - 76, head_cy + 18),
                   (head_cx - 60, head_cy + 30)], fill=fur, outline=outline, width=2.4)
        p.polygon([(head_cx + 62, head_cy + 12), (head_cx + 76, head_cy + 18),
                   (head_cx + 60, head_cy + 30)], fill=fur, outline=outline, width=2.4)

    # ---------------- face ----------------
    ey = head_cy + 1
    ex = 22
    look = pose.look * 3.4
    eye_rx, eye_ry = 13.5, 16.0

    if kind == "panda":
        for sign in (-1, 1):
            ecx = head_cx + sign * ex
            p.ellipse((ecx - 21, ey - 23, ecx + 21, ey + 21),
                      fill=ear)

    def closed_eye(sign):
        e_cx = head_cx + sign * ex
        if happy or sleeping:
            p.arc((e_cx - 14, ey - 13, e_cx + 14, ey + 13), 200, 340,
                  fill=EYE, width=4.2)
        else:
            p.arc((e_cx - 13, ey - 12, e_cx + 13, ey + 12), 200, 340,
                  fill=EYE, width=4.2)

    def open_eye(sign):
        e_cx = head_cx + sign * ex + look
        if dragging:
            p.ellipse((e_cx - 14, ey - 16, e_cx + 14, ey + 16), fill=WHITE)
            p.ellipse((e_cx - 6, ey - 8, e_cx + 6, ey + 8), fill=EYE)
            p.ellipse((e_cx - 8, ey - 13, e_cx - 1, ey - 6), fill=WHITE)
        elif kind == "panda":
            p.ellipse((e_cx - eye_rx, ey - eye_ry, e_cx + eye_rx, ey + eye_ry), fill=WHITE)
            p.ellipse((e_cx - 7, ey - 9, e_cx + 7, ey + 9), fill=EYE)
            p.ellipse((e_cx - 5, ey - 7, e_cx, ey - 2), fill=WHITE)
        else:
            p.ellipse((e_cx - eye_rx, ey - eye_ry, e_cx + eye_rx, ey + eye_ry), fill=EYE)
            p.ellipse((e_cx - 6, ey - 9, e_cx + 1, ey - 2), fill=WHITE)
            p.ellipse((e_cx + 2, ey + 4, e_cx + 6, ey + 8), fill=(235, 225, 214, 255))

    for sign in (-1, 1):
        if pose.blink > 0.55 and not happy and not sleeping and not dragging:
            closed_eye(sign)
        elif happy or sleeping:
            closed_eye(sign)
        else:
            open_eye(sign)

    # blush
    p.ellipse((head_cx - 53, ey + 15, head_cx - 29, ey + 28), fill=blush)
    p.ellipse((head_cx + 29, ey + 15, head_cx + 53, ey + 28), fill=blush)

    # muzzle
    p.ellipse((head_cx - 23, ey + 16, head_cx + 7, ey + 38), fill=belly)
    p.ellipse((head_cx - 7, ey + 16, head_cx + 23, ey + 38), fill=belly)
    p.polygon([(head_cx - 6, ey + 14), (head_cx + 6, ey + 14), (head_cx, ey + 22)],
              fill=PINK, outline=outline, width=1.6)

    # mouth
    open_amt = pose.mouth
    if open_amt > 0.06:
        h = 4 + 9 * open_amt
        p.ellipse((head_cx - 9, ey + 22, head_cx + 9, ey + 22 + h),
                  fill=MOUTH, outline=outline, width=1.8)
        p.ellipse((head_cx - 6, ey + 24 + h * 0.45, head_cx + 6, ey + 24 + h),
                  fill=TONGUE)
    else:
        p.arc((head_cx - 12, ey + 18, head_cx, ey + 31), 20, 160, fill=outline, width=2.2)
        p.arc((head_cx, ey + 18, head_cx + 12, ey + 31), 20, 160, fill=outline, width=2.2)

    # whiskers
    if s.whisker is not None:
        for sign in (-1, 1):
            sx = head_cx + sign * 27
            for dy, wy in ((-2, -6), (3, 2), (8, 10)):
                p.line([(sx, ey + 24 + dy), (sx + sign * 30, ey + 24 + dy + wy)],
                       fill=s.whisker, width=1.8)

    # ---------------- held cookie while eating ----------------
    if eating:
        frac = max(0.0, min(1.0, pose.eat_frac))
        r = 15 * frac + 2
        cxx = head_cx + 8
        cyy = ey + 40
        if frac > 0.05:
            p.ellipse((cxx - r, cyy - r * 0.8, cxx + r, cyy + r * 0.8),
                      fill=(232, 181, 106, 255), outline=(107, 74, 47, 255), width=2.4)
            for ang, dist in ((0.5, 0.45), (2.2, 0.5), (4.0, 0.4)):
                p.ellipse((cxx + math.cos(ang) * r * dist - 2.4,
                           cyy + math.sin(ang) * r * dist * 0.8 - 2.4,
                           cxx + math.cos(ang) * r * dist + 2.4,
                           cyy + math.sin(ang) * r * dist * 0.8 + 2.4),
                          fill=(90, 59, 40, 255))
        for i in range(4):
            life = ((t * 1.8 + i * 0.27) % 1.0)
            if life > 0.85:
                continue
            px = cxx - 6 + math.sin(i * 2.1 + t * 3) * 9
            py = cyy + 12 + life * 34
            rr = 2.2 * (1 - life)
            p.ellipse((px - rr, py - rr, px + rr, py + rr), fill=(203, 154, 88, 255))

    # ---------------- zzz ----------------
    if sleeping:
        for i in range(3):
            frac = (t * 0.45 + i * 0.33) % 1.0
            size = 11 + frac * 8
            alpha = int(230 * (1 - frac))
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            font = _font(int(size * k), bold=True)
            ld.text((int((head_cx + 58 + frac * 16) * k),
                     int((head_cy - 82 - frac * 34 + CAT_DY) * k)),
                    "z", font=font, fill=(96, 80, 70, alpha))
            img.alpha_composite(layer)

    # ---------------- hearts ----------------
    if happy_state:
        for i in range(4):
            side = -1 if i % 2 == 0 else 1
            frac = (t * 0.75 + i * 0.25) % 1.0
            hx = head_cx + side * (80 + i * 2) + math.sin(t * 2.0 + i) * 3
            hy = head_cy + 22 - frac * 62
            hscale = 0.72 + 0.28 * math.sin(frac * math.pi)
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            hp = Painter(layer, k, CAT_DY)
            _heart(hp, hx, hy, 14 * hscale)
            if frac > 0.7:
                alpha = int(255 * (1 - (frac - 0.7) / 0.3))
                layer.putalpha(layer.getchannel("A").point(lambda v: v * alpha // 255))
            img.alpha_composite(layer)

    # ---------------- superscript "!" when dragged ----------------
    if dragging:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        font = _font(int(26 * k), bold=True)
        ld.text((int((head_cx + 54) * k), int((head_cy - 92 + CAT_DY) * k)), "!",
                font=font, fill=(240, 130, 120, 255))
        img.alpha_composite(layer)

    if pose.facing < 0:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    w, h = int(LOGICAL_W * scale), int(LOGICAL_H * scale)
    img = img.resize((w, h), Image.Resampling.BOX)
    img = _apply_motion(img, pose)
    _draw_notes(img, pose, head_cx, head_cy, scale)
    return img


# --------------------------------------------------------------------------
# custom image model
# --------------------------------------------------------------------------
def cutout_white(img: Image.Image, threshold: int = 236) -> Image.Image:
    """Remove a flat white/light background connected to the image border.

    Only kicks in when most of the border is near-white, so transparent PNGs
    and photos with busy backgrounds are left untouched.
    """
    from collections import deque

    im = img.convert("RGBA")
    w, h = im.size
    if w < 4 or h < 4:
        return im
    px = im.load()

    def near_white(p) -> bool:
        return p[3] > 0 and p[0] >= threshold and p[1] >= threshold and p[2] >= threshold

    border = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
    border += [px[0, y] for y in range(1, h - 1)] + [px[w - 1, y] for y in range(1, h - 1)]
    if sum(1 for p in border if near_white(p)) / max(1, len(border)) < 0.72:
        return im

    seen = bytearray(w * h)
    queue = deque()
    for x in range(w):
        for y in (0, h - 1):
            if near_white(px[x, y]) and not seen[y * w + x]:
                seen[y * w + x] = 1
                queue.append((x, y))
    for y in range(1, h - 1):
        for x in (0, w - 1):
            if near_white(px[x, y]) and not seen[y * w + x]:
                seen[y * w + x] = 1
                queue.append((x, y))
    while queue:
        x, y = queue.popleft()
        px[x, y] = (px[x, y][0], px[x, y][1], px[x, y][2], 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and near_white(px[nx, ny]):
                seen[ny * w + nx] = 1
                queue.append((nx, ny))
    return im


def render_custom(pose: Pose, src: Image.Image, scale: float = 1.0) -> Image.Image:
    """Render a user supplied PNG as the pet (static art + motion effects)."""
    W, H = int(LOGICAL_W * scale), int(LOGICAL_H * scale)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    p = Painter(img, scale)
    _shadow(p)

    target_h = int(212 * scale)
    sw, sh = src.size
    if sh <= 0 or sw <= 0:
        return img
    ratio = target_h / sh
    art = src.resize((max(1, int(sw * ratio)), target_h), Image.Resampling.LANCZOS)

    sway = math.sin(pose.t * 2.0) * 2.0 * scale
    left = int((W - art.width) / 2 + sway)
    top = int((SHADOW_Y + 4) * scale) - art.height - int(pose.hop * scale)
    img.alpha_composite(art, (left, top))
    img = _apply_motion(img, pose)
    _draw_notes(img, pose, 130.0, 150.0, scale)
    return img


# --------------------------------------------------------------------------
# speech bubble
# --------------------------------------------------------------------------
def _wrap(text: str, font, draw, max_width: float):
    lines = []
    current = ""
    for ch in text:
        if ch == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + ch
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = trial
    if current or not lines:
        lines.append(current)
    return lines


def render_bubble(text: str, scale: float = 1.0, max_width: float = 228) -> Image.Image:
    """Rounded speech bubble, transparent background."""
    font_px = max(10, int(round(15 * scale)))
    font = _font(font_px, bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = _wrap(text, font, probe, max_width * scale)
    line_h = font_px * 1.45
    text_w = max(probe.textlength(line, font=font) for line in lines)
    pad_x, pad_y = 14 * scale, 9 * scale
    bw = min(max_width * scale, text_w + pad_x * 2)
    bh = line_h * len(lines) + pad_y * 2
    tail_h = 9 * scale
    W = int(bw + 8 * scale)
    H = int(bh + tail_h + 8 * scale)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0 = 3 * scale, 3 * scale
    x1, y1 = x0 + bw, y0 + bh
    d.rounded_rectangle([x0, y0, x1, y1], radius=13 * scale,
                        fill=(255, 252, 245, 255),
                        outline=OUTLINE, width=max(2, int(2.4 * scale)))
    # tail
    tx = x0 + bw * 0.5
    d.polygon([(tx - 8 * scale, y1 - 1), (tx + 7 * scale, y1 - 1),
               (tx, y1 + tail_h)], fill=(255, 252, 245, 255),
              outline=OUTLINE, width=max(2, int(2.2 * scale)))
    d.line([(tx - 7 * scale, y1), (tx + 6 * scale, y1)],
           fill=(255, 252, 245, 255), width=max(2, int(3 * scale)))
    for i, line in enumerate(lines):
        d.text((x0 + pad_x, y0 + pad_y + i * line_h), line, font=font,
               fill=(74, 58, 49, 255))
    return img


# --------------------------------------------------------------------------
# food (cookie)
# --------------------------------------------------------------------------
def render_food(scale: float = 1.0, ss: int = 3) -> Image.Image:
    k = 56 * scale * ss / 56.0
    img = Image.new("RGBA", (int(56 * scale * ss), int(56 * scale * ss)), (0, 0, 0, 0))
    p = Painter(img, k)
    p.ellipse((8, 44, 48, 53), fill=(60, 45, 38, 40))  # shadow
    p.ellipse((11, 11, 45, 44), fill=(234, 186, 114, 255),
              outline=(107, 74, 47, 255), width=2.6)
    p.ellipse((15, 14, 38, 34), fill=(243, 201, 136, 255))
    for cx, cy, r in ((20, 22, 2.6), (31, 19, 2.2), (35, 30, 2.8),
                      (23, 34, 2.2), (17, 30, 1.8)):
        p.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(92, 60, 41, 255))
    # sparkle
    p.polygon([(48, 8), (50, 14), (56, 16), (50, 18), (48, 24), (46, 18),
               (40, 16), (46, 14)], fill=(255, 236, 176, 255))
    return img.resize((int(56 * scale), int(56 * scale)), Image.Resampling.BOX)


def preview_model(key: str, custom: Image.Image | None = None,
                  scale: float = 0.75) -> Image.Image:
    """Small idle pose used by the settings window for its preview."""
    pose = Pose(state="idle", t=1.1)
    if key == "custom" and custom is not None:
        return render_custom(pose, custom, scale=scale)
    return render_cat(pose, scale=scale, ss=2, skin=SKINS.get(key))
