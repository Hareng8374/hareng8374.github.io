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


def grow(a, seed, step=0.022, max_iter=900):
    """Region-grow the background using a local (neighbour-to-neighbour) test."""
    reached = seed.copy()
    f = a / 255.0
    for _ in range(max_iter):
        before = reached.sum()
        for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
            nb = np.roll(reached, sh, axis=ax)
            ref = np.roll(f, sh, axis=ax)
            close = np.sqrt(((f - ref) ** 2).sum(-1) / 3.0) < step
            reached |= nb & close
        if reached.sum() == before:
            break
    return reached


def main():
    a = np.array(Image.open(SRC).convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    bg = model_background(a)

    d = (a - bg) / 255.0
    diff = np.sqrt((d ** 2).sum(-1) / 3.0)

    # Seed from what is unambiguously background, then GROW the region by
    # comparing each pixel to its already-background NEIGHBOUR rather than to a
    # global key. That walks smoothly down his cast shadow -- which a global
    # tolerance cannot follow, because the shadow's hard edge is as far from the
    # modelled backdrop as his jeans are -- and still stops dead at the figure,
    # where the step to sweater/denim/canvas is far larger than one increment.
    # The wall keys cleanly off the modelled backdrop. The ledge does not: his
    # cast shadow sits as far from the model as his denim does, so no single
    # distance threshold separates them. But shadow and ledge are both NEUTRAL
    # greys at middling luminance, while every part of him is not -- sweater
    # L~28, denim is blue, skin is warm, canvas shoes are near-white. So the
    # ledge is identified by what it IS rather than by distance from a key.
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    chroma = a.max(-1) - a.min(-1)
    # Floor 40: the darkest shadow measures L~53, his sweater L~27.
    # Ceiling 170: keeps the shoes' grey shading out; the wall (L~187) is
    # already handled by the modelled-backdrop term above.
    neutral = (chroma < 26) & (lum > 40) & (lum < 170)
    # Confine the semantic test to the ledge band. Above the horizon the wall
    # keys perfectly off the model, and letting the neutral rule loose up there
    # chews holes in the sweater, whose rim-lit edge is also a mid-grey.
    med = np.median(a.reshape(h, -1, 3), axis=1).mean(-1)
    horizon = int(np.argmax(np.abs(np.diff(med))))
    band = np.zeros((h, w), bool); band[horizon - 10:] = True
    outside = L.flood_from_border((diff < TOL_WALL) | (neutral & band))
    print(f"  ledge band starts at y={horizon}")
    soft = L.dilate(outside, BAND)
    sim = float(np.clip(np.percentile(diff[L.erode(outside, 3)], 99.9) * 1.4, 0.02, 0.05))
    alpha = np.clip((diff - sim) / L.BLEND, 0.0, 1.0)
    # Both ends have to be pinned. Forcing the figure opaque is not enough:
    # alpha is derived from distance to the MODELLED backdrop, and in his cast
    # shadow that distance is large, so the shadow stayed opaque no matter what
    # `outside` said. Pin the background clear too and let the ramp act only in
    # the band between them.
    alpha[L.erode(outside, BAND)] = 0.0
    alpha[~soft] = 1.0

    # De-spill against the LOCAL background, not a global key.
    rgb = a.copy()
    edge = (alpha > 0) & (alpha < 1)
    if edge.any():
        al = alpha[edge][:, None]
        rgb[edge] = np.clip((rgb[edge] - bg[edge] * (1 - al)) / np.maximum(al, 1e-3), 0, 255)

    # Fill enclosed transparent specks. Anything not reachable from the frame
    # border is inside him, and this figure has no genuine see-through gaps
    # worth keeping at this size.
    clear = alpha < 0.5
    hole_mask = clear & ~L.flood_from_border(clear)
    holes = int(hole_mask.sum())
    alpha[hole_mask] = 1.0

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
