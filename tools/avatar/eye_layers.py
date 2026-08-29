"""Cut the pupil and closed-lid layers from idle.webp.

Both layers live in the same 680x720 frame as idle.webp and composite straight
over it, so a blink is just toggling a layer's visibility.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
import avatarlib as L
import measure_registration as M


def components(mask, min_size=20):
    """Connected components, largest first. Uses the run-based flood fill."""
    out, remaining = [], mask.copy()
    while remaining.any():
        ys, xs = np.nonzero(remaining)
        seed = np.zeros_like(remaining)
        seed[ys[0], xs[0]] = True
        comp = seed
        for _ in range(64):
            n = comp.sum()
            comp = L.dilate(comp, 1) & remaining
            if comp.sum() == n:
                break
        if comp.sum() >= min_size:
            out.append(comp)
        remaining &= ~comp
    return sorted(out, key=lambda c: -c.sum())


def find_eyes(rgba):
    """Locate each eye's aperture and iris in the idle frame.

    Luminance does not separate eye from face here: the sclera peaks around 195
    and the lit cheek reaches 205. Chroma does, cleanly -- profiling a row
    through each pupil gives skin at 80-108, sclera 17-36, pupil 3-9, iris
    40-65. So the aperture is the low-chroma blob containing the pupil, inside a
    window tight enough that the nose bridge and temple cannot join it.
    """
    ref = M.landmarks(rgba[..., :3].astype(np.uint8), rgba[..., 3].astype(np.uint8), "idle")
    cx, hw, top = ref["head_cx"], ref["head_w"], ref["top"]
    rgb = rgba[..., :3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    chroma = rgb.max(-1) - rgb.min(-1)

    # Eye centres as fractions of head width, read off idle.webp and then
    # refined locally. Slightly asymmetric because his head is turned a few
    # degrees toward camera-left.
    guesses = [(cx - 0.156 * hw, top + 0.694 * hw),
               (cx + 0.139 * hw, top + 0.694 * hw)]

    out = []
    for gx, gy in guesses:
        gx, gy = int(round(gx)), int(round(gy))
        # Refine on the pupil: the darkest blob in a tight window, concentric
        # with the iris.
        ws = 16
        sub = lum[gy - ws:gy + ws, gx - ws:gx + ws]
        dark = sub <= np.percentile(sub, 6)
        py, px = np.nonzero(dark)
        pcx, pcy = gx - ws + float(px.mean()), gy - ws + float(py.mean())

        win = np.zeros(rgba.shape[:2], bool)
        win[int(pcy - 19):int(pcy + 20), int(pcx - 34):int(pcx + 35)] = True

        # The aperture is the low-chroma blob containing this eye's own pupil.
        cand = L.dilate((chroma < 70) & win, 1) & win
        ap = next((c for c in components(cand, 60) if c[int(round(pcy)), int(round(pcx))]), None)
        if ap is None:
            raise RuntimeError(f"no aperture found at ({pcx:.0f}, {pcy:.0f})")

        ys, xs = np.nonzero(ap)
        ir = ap & (lum < 150)
        iy, ix = np.nonzero(ir)
        row = np.abs(iy - pcy) < 3
        r = (ix[row].max() - ix[row].min()) / 2.0 if row.sum() > 4 else 18.0

        # The raw blob is ragged and leaks toward the nose bridge. Fit an
        # ellipse to it via second moments: an eye opening is close enough to an
        # ellipse that this gives a far cleaner region to fill than the blob,
        # and a smooth boundary is what makes the lid fill and lash arc read.
        ell = fit_ellipse(ap)
        out.append(dict(ap=ap, iris=ir, cx=pcx, cy=pcy, r=r, ell=ell,
                        x0=int(xs.min()), x1=int(xs.max()),
                        y0=int(ys.min()), y1=int(ys.max())))
    return ref, out


def fit_ellipse(mask):
    """Centre, semi-axes and orientation from the mask's second moments."""
    ys, xs = np.nonzero(mask)
    cy, cx = ys.mean(), xs.mean()
    cov = np.cov(np.stack([xs - cx, ys - cy]))
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    a, b = 2.0 * np.sqrt(np.maximum(vals, 1e-6))
    return dict(cx=float(cx), cy=float(cy), a=float(a), b=float(b),
                ang=float(np.arctan2(vecs[1, 0], vecs[0, 0])))


def ellipse_mask(shape, e, grow=1.0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    ca, sa = np.cos(-e["ang"]), np.sin(-e["ang"])
    dx, dy = xx - e["cx"], yy - e["cy"]
    u, v = dx * ca - dy * sa, dx * sa + dy * ca
    return (u / (e["a"] * grow)) ** 2 + (v / (e["b"] * grow)) ** 2 <= 1.0


def feather(mask, blur=1.0):
    a = Image.fromarray((mask * 255).astype(np.uint8), "L")
    return np.array(a.filter(ImageFilter.GaussianBlur(blur))).astype(np.float32) / 255.0


def build_pupils(rgba, eyes):
    """The visible iris of each eye, isolated on transparent."""
    keep = np.zeros(rgba.shape[:2], bool)
    yy, xx = np.mgrid[0:rgba.shape[0], 0:rgba.shape[1]]
    for e in eyes:
        disc = (xx - e["cx"]) ** 2 + (yy - e["cy"]) ** 2 <= (e["r"] + 1.5) ** 2
        # Clip to the aperture so the lids stay where they are: the occluded top
        # of the iris is not in the source and cannot be invented.
        keep |= disc & L.dilate(e["ap"], 1)
    a = feather(keep, 0.8)
    out = np.dstack([rgba[..., :3], a * 255.0])
    out[..., 3] *= (rgba[..., 3] / 255.0)
    return out


def sample_col(rgb, x, y, n=3):
    return rgb[max(0, y - n):y + n + 1, x].mean(axis=0)


def lid_region(shape, e):
    """Everything the closed lid must cover: fitted ellipse plus the raw aperture."""
    return ellipse_mask(shape, e["ell"], 1.20) | L.dilate(e["ap"], 3)


def build_lid_synth(rgba, eyes, ref):
    """Variant A: close the eye with the subject's own lid skin.

    The fill is a plane fitted to the skin ringing each eye, excluding dark
    pixels. Sampling a strip directly above the eye and stretching it down --
    the physically obvious approach -- drags the eyebrow across the eye, because
    the brow sits only a few pixels above the aperture on this character.
    """
    rgb = rgba[..., :3]
    h, w = rgba.shape[:2]
    lid = np.zeros((h, w, 4), np.float32)
    cover = np.zeros((h, w), bool)
    lash_acc = np.zeros((h, w), np.float32)

    # Lash colour from the subject's own lash line, not a guess.
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    dark = np.concatenate([rgb[e["ap"] & (lum < 70)] for e in eyes])
    lash_rgb = dark.mean(0) if len(dark) > 20 else np.array([52.0, 36.0, 32.0])

    for e in eyes:
        reg = lid_region((h, w), e)
        ys, xs = np.nonzero(reg)

        # Skin ring around the eye: opaque, not brow, not lash, not hair, and
        # warm enough to actually be skin. The chroma floor matters -- the cool
        # rim-light down the side of his face is bright and desaturated, and
        # without it the fitted plane comes out grey-lavender.
        chroma = rgb.max(-1) - rgb.min(-1)
        ring = (L.dilate(reg, 7) & ~L.dilate(reg, 1) & (rgba[..., 3] > 200)
                & (lum > 95) & (chroma > 45) & (rgb[..., 0] > rgb[..., 2]))
        ry, rx = np.nonzero(ring)
        A = np.stack([rx, ry, np.ones_like(rx)], 1).astype(np.float64)
        coef = [np.linalg.lstsq(A, rgb[ring][:, c].astype(np.float64), rcond=None)[0]
                for c in range(3)]
        fill = np.stack([xs * c[0] + ys * c[1] + c[2] for c in coef], 1)
        lid[ys, xs, :3] = np.clip(fill, 0, 255)
        cover[reg] = True

        im = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(im)
        pts = []
        for x in range(xs.min(), xs.max() + 1):
            col = np.nonzero(reg[:, x])[0]
            if col.size < 3:
                continue
            y0, y1 = int(col.min()), int(col.max())
            pts.append((x, y0 + 0.66 * (y1 - y0)))

        span = xs.max() - xs.min()
        for i in range(len(pts) - 1):
            t = (pts[i][0] - xs.min()) / max(span, 1)
            thick = 1.0 + 2.4 * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.55
            d.line([pts[i], pts[i + 1]], fill=255, width=max(1, int(round(thick))))
        lash_acc = np.maximum(
            lash_acc,
            np.array(im.filter(ImageFilter.GaussianBlur(0.7))).astype(np.float32) / 255.0)

    # Crease shadow just above the lashes, then the lashes themselves.
    sh = np.array(Image.fromarray((lash_acc * 255).astype(np.uint8))
                  .filter(ImageFilter.GaussianBlur(2.6))).astype(np.float32) / 255.0
    sh = np.roll(sh, -3, axis=0) * cover
    lid[..., :3] *= (1 - sh[..., None] * 0.28)
    la = lash_acc[..., None]
    lid[..., :3] = lid[..., :3] * (1 - la) + lash_rgb * la

    cover |= lash_acc > 0.06
    # Generous feather: the fill meets real skin at the region boundary, and a
    # tight edge there shows as a sticker seam.
    lid[..., 3] = feather(L.erode(cover, 1), 2.2) * 255.0
    lid[..., 3] *= (rgba[..., 3] / 255.0)
    return lid


def build_lid_harvest(rgba, eyes, ref, scratch):
    """Variant B: warp dance2's genuine closed eyes onto idle's eye geometry."""
    d = np.load(scratch / "poses.npz")
    src = d["dance2"]
    sref = M.landmarks(src[..., :3].astype(np.uint8), src[..., 3].astype(np.uint8), "dance2")

    dx = int(round(ref["head_cx"] - sref["head_cx"]))
    dy = int(round(ref["eye_y"] - sref["eye_y"]))
    warped = np.roll(np.roll(src, dy, axis=0), dx, axis=1)

    # Transplant only the fitted eye ellipses, grown enough to cover the open
    # eye and its lashes. A bounding rectangle drags in cheek and brow, which is
    # what made an earlier version smear.
    cover = np.zeros(rgba.shape[:2], bool)
    for e in eyes:
        cover |= lid_region(rgba.shape[:2], e)

    # Colour-match the transplant to idle's own skin around the eyes.
    ring = L.dilate(cover, 6) & ~L.dilate(cover, 1) & (rgba[..., 3] > 200)
    if ring.sum() > 50:
        a = L.rgb2lab(rgba[..., :3][ring]).mean(0)
        b = L.rgb2lab(warped[..., :3][ring]).mean(0)
        lab = L.rgb2lab(warped[..., :3]) + (a - b)
        warped = np.dstack([L.lab2rgb(lab), warped[..., 3]])

    al = feather(L.erode(cover, 1), 2.0)
    out = np.dstack([warped[..., :3], al * 255.0])
    out[..., 3] *= (rgba[..., 3] / 255.0)
    return out


def sheet(rgba, layers, eyes, path, zoom=4):
    """idle, then idle with each layer composited: whole face and both eyes."""
    x0 = min(e["x0"] for e in eyes) - 30
    x1 = max(e["x1"] for e in eyes) + 30
    y0 = min(e["y0"] for e in eyes) - 26
    y1 = max(e["y1"] for e in eyes) + 26
    bw, bh = x1 - x0, y1 - y0
    tiles = [("idle (open)", rgba)] + [(n, comp(rgba, l)) for n, l in layers]

    tw = bw * zoom
    th = int(tw * 0.62)
    head = (int(eyes[0]["cx"] - 150), 20, int(eyes[1]["cx"] + 150), 20 + int(300 * 0.62))
    top = Image.new("RGB", (tw * len(tiles), th + bh * zoom + 34), (24, 24, 28))
    d = ImageDraw.Draw(top)
    for i, (name, f) in enumerate(tiles):
        flat = Image.fromarray(L.over(f, (255, 255, 255)))
        top.paste(flat.crop(head).resize((tw, th), Image.LANCZOS), (i * tw, 0))
        d.text((i * tw + 4, th + 3), name, fill=(235, 235, 235))
        top.paste(flat.crop((x0, y0, x1, y1)).resize((bw * zoom, bh * zoom), Image.NEAREST),
                  (i * tw, th + 18))
    top.save(path)


def layer_sheet(layers, eyes, path, zoom=4):
    """The layers themselves on a checker, to show what each file contains."""
    x0 = min(e["x0"] for e in eyes) - 30
    x1 = max(e["x1"] for e in eyes) + 30
    y0 = min(e["y0"] for e in eyes) - 26
    y1 = max(e["y1"] for e in eyes) + 26
    bw, bh = x1 - x0, y1 - y0
    out = Image.new("RGB", (bw * zoom * len(layers), bh * zoom + 16), (24, 24, 28))
    d = ImageDraw.Draw(out)
    for i, (name, l) in enumerate(layers):
        crop = l[y0:y1, x0:x1]
        yy, xx = np.mgrid[0:bh, 0:bw]
        ck = np.where(((yy // 8 + xx // 8) % 2) == 0, 235, 200).astype(np.float32)
        a = crop[..., 3:4] / 255.0
        im = np.clip(crop[..., :3] * a + ck[..., None] * (1 - a), 0, 255).astype(np.uint8)
        out.paste(Image.fromarray(im).resize((bw * zoom, bh * zoom), Image.NEAREST), (i * bw * zoom, 0))
        d.text((i * bw * zoom + 4, bh * zoom + 2), name, fill=(235, 235, 235))
    out.save(path)


def comp(base, layer):
    a = layer[..., 3:4] / 255.0
    rgb = layer[..., :3] * a + base[..., :3] * (1 - a)
    al = np.maximum(base[..., 3:4], layer[..., 3:4])
    return np.dstack([rgb, al])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--write", action="store_true", help="write the webp layers")
    ap.add_argument("--lid", choices=["synth", "harvest"], default="synth")
    # The layers must be cut from the pose the component actually renders.
    # idle.webp (video frame) and idle-still.webp (from image.png) are different
    # renders whose irises sit in different places, so layers cut from one do
    # not composite cleanly onto the other.
    ap.add_argument("--source", default="idle-still.webp")
    a = ap.parse_args()

    rgba = np.array(Image.open(L.AVATAR / a.source).convert("RGBA")).astype(np.float32)
    print(f"cutting eye layers from {a.source}")
    ref, eyes = find_eyes(rgba)
    for i, e in enumerate(eyes):
        el = e["ell"]
        print(f"eye {i}: aperture x {e['x0']}..{e['x1']}  y {e['y0']}..{e['y1']}  "
              f"iris centre ({e['cx']:.1f}, {e['cy']:.1f}) r {e['r']:.1f}  |  "
              f"ellipse ({el['cx']:.1f}, {el['cy']:.1f}) axes {el['a']:.1f}x{el['b']:.1f} "
              f"tilt {np.degrees(el['ang']):+.1f}deg")

    pupils = build_pupils(rgba, eyes)
    synth = build_lid_synth(rgba, eyes, ref)
    harvest = build_lid_harvest(rgba, eyes, ref, a.scratch)
    print(f"\npupils: {int((pupils[...,3]>0).sum()):,} px   "
          f"synth lid: {int((synth[...,3]>0).sum()):,} px   "
          f"harvest lid: {int((harvest[...,3]>0).sum()):,} px")

    sheet(rgba, [("pupils only", pupils), ("A: synthesised lid", synth),
                 ("B: harvested lid", harvest)], eyes, a.scratch / "eyes.png")
    layer_sheet([("pupils.webp", pupils), ("A: eyes-closed", synth),
                 ("B: eyes-closed", harvest)], eyes, a.scratch / "eye_layers.png")
    print(f"wrote eyes.png, eye_layers.png -> {a.scratch}")

    np.savez_compressed(a.scratch / "eye_layers.npz",
                        pupils=pupils, synth=synth, harvest=harvest)
    if a.write:
        chosen = synth if a.lid == "synth" else harvest
        for name, arr in [("pupils", pupils), ("eyes-closed", chosen)]:
            p = L.AVATAR / f"{name}.webp"
            q, n, psnr = L.save_webp(arr, p)
            print(f"  {p.name:18} q{q:>3}  {n/1024:>6.1f} KB  psnr {psnr:.1f}")


if __name__ == "__main__":
    main()
