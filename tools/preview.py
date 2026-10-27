"""Offline preview: render poses / models / action frames and report timing."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from PIL import Image  # noqa: E402

import sprite  # noqa: E402

OUT = ROOT / "preview"
OUT.mkdir(exist_ok=True)


def checker_bg(w, h, cell=12):
    img = Image.new("RGB", (w, h), (250, 249, 246))
    px = img.load()
    for y in range(h):
        for x in range(w):
            if (x // cell + y // cell) % 2 == 0:
                px[x, y] = (238, 236, 231)
    return img


def on_checker(frame):
    bg = checker_bg(frame.width, frame.height)
    bg.paste(frame, (0, 0), frame)
    return bg


def main():
    poses = [
        ("idle", sprite.Pose(state="idle", t=0.8)),
        ("walk", sprite.Pose(state="walk", t=1.2, walk_phase=0.15, facing=1)),
        ("happy", sprite.Pose(state="happy", t=2.4)),
        ("eat", sprite.Pose(state="eat", t=3.0, eat_frac=0.55, mouth=0.9)),
        ("sleep", sprite.Pose(state="sleep", t=4.2)),
        ("drag", sprite.Pose(state="drag", t=5.1)),
    ]
    scale = 1.0
    frames = []
    for name, pose in poses:
        frame = sprite.render_cat(pose, scale=scale)
        bg = checker_bg(frame.width, frame.height)
        bg.paste(frame, (0, 0), frame)
        bg.save(OUT / f"pose_{name}.png")
        frames.append(bg)

    sheet = Image.new("RGB", (frames[0].width * 3, frames[0].height * 2), "white")
    for i, f in enumerate(frames):
        sheet.paste(f, ((i % 3) * f.width, (i // 3) * f.height))
    sheet.save(OUT / "poses.png")

    # ---- models ----
    thumbs = []
    for key, skin in sprite.SKINS.items():
        frame = sprite.render_cat(sprite.Pose(state="idle", t=1.1),
                                  scale=0.7, skin=skin)
        thumbs.append((key, on_checker(frame)))
    mw, mh = thumbs[0][1].size
    model_sheet = Image.new("RGB", (mw * len(thumbs), mh), "white")
    for i, (_, im) in enumerate(thumbs):
        model_sheet.paste(im, (i * mw, 0))
    model_sheet.save(OUT / "models.png")

    # ---- dance strip ----
    dance_frames = []
    for i in range(8):
        t = i * 0.32
        beat = t / 1.15
        u = beat % 1.0
        spin = 360.0 * u if int(beat) % 2 == 0 else 0.0
        pose = sprite.Pose(state="action", action="dance", t=t,
                           spin=spin, hop=abs(__import__("math").sin(t * 5.2)) * 8,
                           squash=1 - 0.07 * abs(__import__("math").cos(t * 5.2)),
                           notes=1.0, tail_wag=0.6)
        dance_frames.append(on_checker(sprite.render_cat(pose, scale=0.62)))
    dw, dh = dance_frames[0].size
    strip = Image.new("RGB", (dw * 4, dh * 2), "white")
    for i, f in enumerate(dance_frames):
        strip.paste(f, ((i % 4) * dw, (i // 4) * dh))
    strip.save(OUT / "dance.png")

    # bubble
    b = sprite.render_bubble("零食时间到啦～ 喵！", scale=1.0)
    canvas = checker_bg(b.width + 20, b.height + 20)
    canvas.paste(b, (10, 10), b)
    canvas.save(OUT / "bubble.png")

    # food
    f = sprite.render_food(2.0)
    fc = checker_bg(f.width + 20, f.height + 20)
    fc.paste(f, (10, 10), f)
    fc.save(OUT / "food.png")

    # timing
    pose = sprite.Pose(state="idle", t=1.0)
    start = time.perf_counter()
    n = 30
    for i in range(n):
        pose.t = i / 30
        sprite.render_cat(pose, scale=1.0)
    print(f"render 30 frames: {(time.perf_counter() - start) * 1000:.1f} ms "
          f"({(time.perf_counter() - start) / n * 1000:.2f} ms/frame)")


if __name__ == "__main__":
    main()
