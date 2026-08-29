"""Shared primitives for the avatar asset pipeline: keying, transform, LAB, export."""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
AVATAR = ROOT / "src" / "assets" / "avatar"

FRAME_W, FRAME_H = 680, 720

# Poses to ship: output stem -> source file. wave3 was dropped; wave2 and
# surprised are regenerations that re-measure at 0.00% scale deviation.
POSES = {
    "idle-still": "image.png",
    "wave1": "wave1.png",
    "wave2": "wave2.png",
    "point": "point.png",
    "thumbsup": "thumbsup.png",
    "dance1": "dance1.png",
    "dance2": "dance2.png",
    "surprised": "surprised.png",
}

FILL_TOL = 0.045   # flood-fill tolerance: tight enough not to leak through soft edges
BLEND = 0.03       # ffmpeg colorkey blend, ~1px soft edge
EDGE_BAND = 3      # px around the flood fill where the colorkey ramp may act


# --------------------------------------------------------------------------- io

def load_rgb(path):
    return np.array(Image.open(path).convert("RGB"))


def border_bg(rgb, m=6):
    """Median colour of the frame border — the true backdrop value."""
    e = np.concatenate([rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3),
                        rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3)])
    return tuple(int(v) for v in np.median(e, axis=0))


# ------------------------------------------------------------------- flood fill

def _spread_rows(ok, reached):
    """Within each row, any reached pixel floods its whole contiguous ok-run."""
    h, w = ok.shape
    po = np.zeros((h, w + 1), bool); po[:, :w] = ok        # separator column so
    pr = np.zeros((h, w + 1), bool); pr[:, :w] = reached   # runs never cross rows
    fo, fr = po.ravel(), pr.ravel()
    start = fo & ~np.concatenate(([False], fo[:-1]))
    rid = np.cumsum(start)
    hit = np.bincount(rid[fo], weights=fr[fo].astype(np.float64),
                      minlength=int(rid[-1]) + 1) > 0
    out = np.zeros_like(fo)
    out[fo] = hit[rid[fo]]
    return out.reshape(h, w + 1)[:, :w]


def flood_from_border(ok, max_passes=64):
    """Pixels of `ok` reachable from the frame border, 4-connected.

    Alternating row and column run-propagation converges in a handful of passes,
    where naive per-pixel dilation would need one pass per pixel of path length.
    """
    reached = np.zeros_like(ok)
    reached[0], reached[-1] = ok[0], ok[-1]
    reached[:, 0], reached[:, -1] = ok[:, 0], ok[:, -1]
    for _ in range(max_passes):
        n = reached.sum()
        reached = _spread_rows(ok, reached)
        reached = _spread_rows(ok.T, reached.T).T
        if reached.sum() == n:
            break
    return reached


def erode(mask, n=2):
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:] &= m[:-1]; e[:-1] &= m[1:]
        e[:, 1:] &= m[:, :-1]; e[:, :-1] &= m[:, 1:]
        m = e
    return m


def dilate(mask, n=2):
    m = mask.copy()
    for _ in range(n):
        e = m.copy()
        e[1:] |= m[:-1]; e[:-1] |= m[1:]
        e[:, 1:] |= m[:, :-1]; e[:, :-1] |= m[:, 1:]
        m = e
    return m


# ------------------------------------------------------------------------ keying

def diff_map(rgb, key):
    """ffmpeg vf_colorkey distance: sqrt((dr^2+dg^2+db^2)/3) on 0..1 channels."""
    d = rgb.astype(np.float32) / 255.0 - np.array(key, np.float32) / 255.0
    return np.sqrt((d ** 2).sum(-1) / 3.0)


def tune_similarity(diff, bg_core):
    """Smallest similarity that clears this image's own backdrop, plus margin.

    Interior protection does NOT come from this value -- it comes from the flood
    fill. This only has to swallow the backdrop's own noise floor.
    """
    if bg_core.sum() == 0:
        return 0.06
    return float(np.clip(np.percentile(diff[bg_core], 99.99) * 1.5, 0.02, 0.05))


def key_image(rgb, key=None, blend=BLEND):
    """Key the backdrop topologically. Returns (rgba float32 0..255, stats)."""
    if key is None:
        key = border_bg(rgb)
    diff = diff_map(rgb, key)

    outside = flood_from_border(diff < FILL_TOL)   # backdrop, reached from the edge
    interior = ~outside                             # subject + any enclosed pixels
    bg_core = erode(outside, 3)

    sim = tune_similarity(diff, bg_core)
    alpha = np.clip((diff - sim) / blend, 0.0, 1.0)
    # The colorkey ramp is allowed only within a narrow band around the flood-
    # filled backdrop; everywhere further in is forced opaque. That is what
    # protects eye whites, teeth, fingernails and the grey hair rim-light, some
    # of which sit at distance 0.0000 from the backdrop and would otherwise be
    # erased. Confining the ramp to the band rather than to `outside` itself is
    # what keeps the silhouette soft: a hard interior/exterior split leaves
    # every pixel at alpha 0 or 1 and aliases the hair.
    soft = dilate(outside, EDGE_BAND)
    alpha[~soft] = 1.0

    # De-spill: edge pixels are a blend of subject and backdrop. Recover the
    # subject's true colour so they do not read as a grey halo over any
    # non-grey background.
    out = rgb.astype(np.float32).copy()
    edge = (alpha > 0.0) & (alpha < 1.0)
    if edge.any():
        a = alpha[edge][:, None]
        k = np.array(key, np.float32)[None, :]
        out[edge] = np.clip((out[edge] - k * (1.0 - a)) / np.maximum(a, 1e-3), 0, 255)

    rgba = np.dstack([out, alpha * 255.0])
    stats = dict(key=key, similarity=sim, blend=blend,
                 interior=interior, outside=outside, bg_core=bg_core, edge=edge,
                 protected=int((~soft & (diff < sim + blend)).sum()),
                 edge_px=int(edge.sum()))
    return rgba, stats


# --------------------------------------------------------------------- transform

def to_frame(rgba, scale, tx, ty, size=(FRAME_W, FRAME_H)):
    """Scale then translate into the idle frame, resampling premultiplied.

    Premultiplying before resampling is what stops edge pixels from bleeding
    fully-transparent colour into the silhouette. Offsets are rounded to whole
    pixels; the measured values are within 0.6px of each other so the residual
    is under half a pixel, far inside the 14.4px registration tolerance, and
    rounding avoids a second resample that would soften every pose.
    """
    h, w = rgba.shape[:2]
    a = rgba[..., 3:4] / 255.0
    prem = np.dstack([rgba[..., :3] * a, rgba[..., 3]])
    im = Image.fromarray(np.clip(prem + 0.5, 0, 255).astype(np.uint8), "RGBA")
    im = im.resize((int(round(w * scale)), int(round(h * scale))), Image.LANCZOS)

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(im, (int(round(tx)), int(round(ty))))

    p = np.array(canvas).astype(np.float32)
    a = p[..., 3:4] / 255.0
    rgb = np.where(a > 0, p[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.dstack([np.clip(rgb, 0, 255), p[..., 3]])


# --------------------------------------------------------------------------- LAB

_M_RGB2XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]], np.float64)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb2lab(rgb):
    s = np.asarray(rgb, np.float64) / 255.0
    lin = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)
    xyz = lin @ _M_RGB2XYZ.T / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16,
                     500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])], -1)


def lab2rgb(lab):
    lab = np.asarray(lab, np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 0.206893, f ** 3, (f - 16.0 / 116.0) / 7.787) * _WHITE
    lin = xyz @ np.linalg.inv(_M_RGB2XYZ).T
    lin = np.clip(lin, 0, 1)
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(s * 255.0, 0, 255)


def match_histogram(src_lab, ref_lab, bins=4096):
    """Match src's per-channel LAB distribution to ref's, via CDF lookup."""
    out = np.empty_like(src_lab)
    for c, (lo, hi) in enumerate([(0.0, 100.0), (-128.0, 128.0), (-128.0, 128.0)]):
        s, r = src_lab[:, c], ref_lab[:, c]
        edges = np.linspace(lo, hi, bins + 1)
        cs = np.cumsum(np.histogram(s, edges)[0]).astype(np.float64)
        cr = np.cumsum(np.histogram(r, edges)[0]).astype(np.float64)
        cs /= max(cs[-1], 1); cr /= max(cr[-1], 1)
        mid = (edges[:-1] + edges[1:]) / 2
        out[:, c] = np.interp(np.interp(s, mid, cs), cr, mid)
    return out


# ------------------------------------------------------------------------ export

def save_webp(rgba, path, max_bytes=60_000, target=59_000, lossless=False):
    """Highest quality that fits the byte budget. Returns (quality, size, psnr)."""
    im = Image.fromarray(np.clip(rgba + 0.5, 0, 255).astype(np.uint8), "RGBA")
    if lossless:
        im.save(path, "WEBP", lossless=True, quality=100, method=6, exact=True)
        return 100, path.stat().st_size, float("inf")

    best = None
    lo, hi = 1, 100
    while lo <= hi:
        q = (lo + hi) // 2
        im.save(path, "WEBP", quality=q, method=6, alpha_quality=100)
        n = path.stat().st_size
        if n <= target:
            best = (q, n)
            lo = q + 1
        else:
            hi = q - 1
    if best is None:                      # even q=1 overshoots
        im.save(path, "WEBP", quality=1, method=6, alpha_quality=100)
        best = (1, path.stat().st_size)
    else:
        im.save(path, "WEBP", quality=best[0], method=6, alpha_quality=100)

    got = np.array(Image.open(path).convert("RGBA")).astype(np.float32)
    a = rgba[..., 3:4] / 255.0            # weight error by coverage
    mse = float((((got[..., :3] - rgba[..., :3]) ** 2) * a).sum() / max(a.sum() * 3, 1))
    psnr = 10 * np.log10(255.0 ** 2 / mse) if mse > 0 else float("inf")
    return best[0], path.stat().st_size, psnr


def over(rgba, bg):
    """Composite over a flat colour, for inspection."""
    a = rgba[..., 3:4] / 255.0
    return np.clip(rgba[..., :3] * a + np.array(bg, np.float32) * (1 - a), 0, 255).astype(np.uint8)