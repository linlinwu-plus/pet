"""Crop and zoom the pet region out of a screenshot for inspection."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vendor"))
from PIL import Image  # noqa: E402

src = ROOT / "preview" / (sys.argv[1] if len(sys.argv) > 1 else "screen1.png")
box = tuple(int(v) for v in sys.argv[2:6]) if len(sys.argv) >= 6 else (1350, 640, 1620, 900)
zoom = float(sys.argv[6]) if len(sys.argv) > 6 else 2.0
out = sys.argv[7] if len(sys.argv) > 7 else "crop.png"
im = Image.open(src)
crop = im.crop(box)
if zoom != 1.0:
    crop = crop.resize((int(crop.width * zoom), int(crop.height * zoom)), Image.LANCZOS)
crop.save(ROOT / "preview" / out)
print(crop.size)
