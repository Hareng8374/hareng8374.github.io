"""Key the seated render.

Unlike the bust poses this frame has TWO backgrounds -- a flat wall above and a
lit ledge below -- and the ledge is not flat: it carries a gradient both down
and across. A single key colour cannot clear it, so the background is modelled
per row by interpolating between the left and right edge strips, which are
always background because the figure never reaches the frame edge.

The ledge is removed along with the wall: he needs to sit on a heading, not on
a grey slab.
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import avatarlib as L

SRC = L.AVATAR / "sitting.png"
OUT = L.AVATAR / "sitting.webp"
EDGE = 30          # px of guaranteed-background at each side
TOL_WALL = 0.055   # the wall is flat, so it keys tight
TOL_LEDGE = 0.135  # the ledge carries his cast shadow, whose hard edge the
                   # left-to-right model cannot follow; the figure is still far
                   # clear of it (sweater L~28, jeans blue, shoes near-white,
                   # shadow a mid grey) so the looser bound is safe
BAND = 3           # px around the fill where the soft ramp may act


def model_background(a):
    """Per-pixel background estimate: interpolate each row between its edges."""
    h, w = a.shape[:2]
    left = np.median(a[:, :EDGE], axis=1)        # (h,3)
    right = np.median(a[:, w - EDGE:], axis=1)
    t = np.linspace(0, 1, w, dtype=np.float32)[None, :, None]
    return left[:, None, :] * (1 - t) + right[:, None, :] * t


def main():
    a = np.array(Image.open(SRC).convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    bg = model_background(a)

    d = (a - bg) / 255.0
    diff = np.sqrt((d ** 2).sum(-1) / 3.0)

    # Find the ledge edge: the biggest row-to-row luminance step.
    med = np.median(a.reshape(h, -1, 3), axis=1).mean(-1)
    horizon = int(np.argmax(np.abs(np.diff(med))))
    tol = np.full((h, w), TOL_WALL, np.float32)
    tol[horizon:] = TOL_LEDGE
    print(f"  ledge edge detected at y={horizon}")

    outside = L.flood_from_border(diff < tol)
    soft = L.dilate(outside, BAND)
    sim = float(np.clip(np.percentile(diff[L.erode(outside, 3)], 99.9) * 1.4, 0.02, 0.05))
    alpha = np.clip((diff - sim) / L.BLEND, 0.0, 1.0)
    alpha[~soft] = 1.0

    # De-spill against the LOCAL background, not a global key.
    rgb = a.copy()
    edge = (alpha > 0) & (alpha < 1)
    if edge.any():
        al = alpha[edge][:, None]
        rgb[edge] = np.clip((rgb[edge] - bg[edge] * (1 - al)) / np.maximum(al, 1e-3), 0, 255)

    clear = alpha < 0.5
    holes = int((clear & ~L.flood_from_border(clear)).sum())

    rgba = np.dstack([rgb, alpha * 255.0])
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    pad = 4
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    crop = rgba[y0:y1, x0:x1]

    print(f"  source {w}x{h}   similarity {sim:.4f}   soft edge {int(edge.sum()):,}px")
    print(f"  interior holes {holes}")
    print(f"  figure bbox x {xs.min()}..{xs.max()}  y {ys.min()}..{ys.max()}")
    print(f"  cropped to {crop.shape[1]}x{crop.shape[0]}")

    q, n, psnr = L.save_webp(crop, OUT, max_bytes=90_000, target=88_000)
    print(f"  wrote {OUT.name}  q{q}  {n/1024:.1f} KB  psnr {psnr:.1f}")
    return crop


if __name__ == "__main__":
    main()
