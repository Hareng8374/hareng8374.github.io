"""Key, register and export the four basketball shooting frames + the ball.

The four Gemini renders arrived at wildly different framings -- 765x1024,
1024x572, 765x1024 and 1024x1024 -- with the figure drawn at scales that differ
by up to 1.7x. Aligning them needs a ruler that is rigid across poses, and the
usual head-width detector in measure_registration.py cannot supply one here: it
tracks the topmost silhouette run down from the crown, which in three of these
four poses is the raised ARM, not the head.

The basketball is the ruler. It is a sphere, so its projected diameter is a pure
scale measurement independent of pose, and it appears in three of the four
frames. Fitting a circle to the part of its outline that borders the backdrop
ignores whatever the hands occlude, which is what makes the fit usable while he
is gripping it -- the free arc alone pins the radius to under a pixel RMS.

followthru has no ball, so its scale comes from cross-correlating its head
against gather's over a scale sweep (s=0.896, ncc=0.83). That agrees with a
by-hand read of the two head widths to 0.7%.

Alignment is then: uniform scale to a common ball diameter, horizontal on the
centroid of the lower body (the legs -- the arms swing too much to be an
anchor), vertical on the lowest opaque pixel so every frame shares one ground
line. The jump itself is NOT baked into the frames; the game translates the
whole sprite along an arc, which keeps the arc tunable and stops the generated
(and inconsistent) airborne heights from dictating it.

Outputs, all sharing one canvas so the game can blit them into the same rect:
  shot-gather.webp  shot-rise.webp  shot-release.webp  shot-followthru.webp
  ball.webp         -- cut out of release.png, which is where it flies free
and prints the ball's spawn point in canvas coordinates.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import avatarlib as L

FRAMES = ["gather", "rise", "release", "followthru"]

# Search boxes for the ball's circle fit. Hand-set: the ball and skin are
# indistinguishable by hue (both H 14-22, S ~0.6), so the fit has to be told
# where to look rather than finding the ball by colour alone.
BALL_BOX = {
    "gather":  (440, 330, 650, 540),
    "rise":    (478,   3, 578, 108),
    "release": (515,   3, 672, 150),
}
# followthru holds no ball; scale comes from the head NCC against gather.
FOLLOWTHRU_VS_GATHER = 0.8960

TARGET_BALL_D = 66.0   # normalised ball diameter, px
PAD = 10               # canvas margin
LOWER_BODY = 0.35      # bottom fraction of the figure used for the x anchor

# Gemini changed the wardrobe between generations: gather came back in khaki
# trousers while the other three are charcoal. Unfixed, the trousers strobe on
# every shot. These are the leg boxes used to sample each -- gather's get
# retinted to followthru's distribution.
PANTS_BOX = {"gather": (540, 945, 250, 620), "followthru": (540, 930, 380, 660)}


# --------------------------------------------------------------------- helpers

def hsv(rgb):
    a = rgb.astype(np.float32) / 255.0
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    s = np.where(mx > 0, d / np.maximum(mx, 1e-6), 0.0)
    h = np.zeros_like(mx)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = d > 1e-6
    i = m & (mx == r); h[i] = ((g - b)[i] / d[i]) % 6
    i = m & (mx == g); h[i] = ((b - r)[i] / d[i]) + 2
    i = m & (mx == b); h[i] = ((r - g)[i] / d[i]) + 4
    return h * 60.0, s, mx


def flood_seed(ok, seed, max_passes=96):
    r = seed & ok
    for _ in range(max_passes):
        n = r.sum()
        r = L._spread_rows(ok, r)
        r = L._spread_rows(ok.T, r.T).T
        if r.sum() == n:
            break
    return r


def largest_component(mask):
    """Biggest 4-connected blob. Few components here, so flood-and-repeat is fine."""
    todo = mask.copy()
    best = None
    while todo.any():
        ys, xs = np.where(todo)
        seed = np.zeros_like(mask)
        seed[ys[0], xs[0]] = True
        comp = flood_seed(mask, seed)
        if best is None or comp.sum() > best.sum():
            best = comp
        todo &= ~comp
    return best


def fit_circle(x, y):
    """Kasa algebraic circle fit."""
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    c, *_ = np.linalg.lstsq(A, x ** 2 + y ** 2, rcond=None)
    cx, cy = float(c[0]), float(c[1])
    r = float(np.sqrt(c[2] + cx ** 2 + cy ** 2))
    return cx, cy, r, np.abs(np.hypot(x - cx, y - cy) - r)


def ball_circle(rgb, bg, box):
    """Radius and centre from the ball's free arc -- the part bordering the backdrop.

    Occluded arc contributes nothing, so a gripped ball measures the same as a
    loose one. `bg` is dilated first because the anti-aliased rim sits in neither
    the saturated-orange mask nor the flood-filled backdrop, and without the
    reach across that band the two masks never touch.
    """
    x0, y0, x1, y1 = box
    H, S, V = hsv(rgb)
    inbox = np.zeros(bg.shape, bool)
    inbox[y0:y1, x0:x1] = True
    orange = inbox & ~bg & (S > 0.30) & (H > 2) & (H < 40) & (V > 0.20)
    orange = L.erode(L.dilate(orange, 3), 3)
    arc = orange & L.dilate(bg, 5)
    ys, xs = np.where(arc)
    x, y = xs.astype(float), ys.astype(float)
    for _ in range(4):
        cx, cy, r, resid = fit_circle(x, y)
        keep = resid < max(2.0, 2.0 * resid.std())
        if keep.all():
            break
        x, y = x[keep], y[keep]
    return cx, cy, r, float(resid.mean()), len(x)


def leg_mask(rgb, fg, box, v_min):
    """Trousers inside `box`: everything lit enough not to be the sweater or the shoes.

    A hue/saturation gate looked like the obvious rule and was wrong -- it drops
    the specular rim down the front of each leg, which then survives the retint
    as a khaki outline. Luminance alone separates cleanly here: the sweater sits
    at V~0.03 and the shoes at V~0.13, well under the trousers' V~0.35-0.95.
    Closing plus hole-filling recovers the dark fold interiors.
    """
    y0, y1, x0, x1 = box
    b = np.zeros(fg.shape, bool)
    b[y0:y1, x0:x1] = True
    _, _, V = hsv(rgb)
    core = b & fg & (V > v_min)
    closed = L.erode(L.dilate(core, 4), 4)
    holes = ~closed & ~L.flood_from_border(~closed)
    return (closed | holes) & fg & b


def recolour_pants(rgb, fg, ref_rgb, ref_fg):
    """Retint gather's khaki trousers to followthru's charcoal, in LAB.

    Mean/std transfer per channel rather than a flat fill, so the fabric's folds
    and the rim light survive; matching the reference's spread as well as its
    mean is what stops the retinted leg reading flatter than the other frames.
    """
    mask = leg_mask(rgb, fg, PANTS_BOX["gather"], 0.20)
    ref = leg_mask(ref_rgb, ref_fg, PANTS_BOX["followthru"], 0.07) & (
        L.rgb2lab(ref_rgb.astype(np.float64))[..., 0] < 45)

    src = L.rgb2lab(rgb[mask].astype(np.float64))
    dst = L.rgb2lab(ref_rgb[ref].astype(np.float64))
    out = src.copy()
    for c in range(3):
        out[:, c] = ((src[:, c] - src[:, c].mean())
                     * (dst[:, c].std() / max(src[:, c].std(), 1e-6)) + dst[:, c].mean())

    new = rgb.astype(np.float64).copy()
    new[mask] = L.lab2rgb(out)

    soft = L.dilate(mask, 2) & ~L.erode(mask, 2)      # feather the seam
    blur = new.copy()
    for _ in range(2):
        p = np.pad(blur, ((1, 1), (1, 1), (0, 0)), mode="edge")
        blur = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + blur * 2) / 6.0
    new[soft] = blur[soft]
    print(f"{'gather':11s} trousers retinted: {mask.sum()} px -> "
          f"rgb {new[mask].mean(0).round(1)} (ref {ref_rgb[ref].mean(0).round(1)})")
    return np.clip(new, 0, 255).astype(np.uint8)


def premultiplied_resize(rgba, w, h):
    """Premultiply -> Lanczos -> unpremultiply, so edges do not fringe."""
    a = rgba[..., 3:4] / 255.0
    pm = np.dstack([rgba[..., :3] * a, rgba[..., 3]])
    out = np.asarray(Image.fromarray(pm.astype(np.uint8), "RGBA")
                     .resize((w, h), Image.LANCZOS)).astype(np.float32)
    oa = out[..., 3:4] / 255.0
    rgb = np.clip(out[..., :3] / np.maximum(oa, 1e-3), 0, 255)
    return np.dstack([rgb, out[..., 3]])


# ------------------------------------------------------------------------ main

def main():
    meas, art = {}, {}

    ref_rgb = L.load_rgb(L.AVATAR / "followthru.png")
    ref_fg = ~L.flood_from_border(
        L.diff_map(ref_rgb, L.border_bg(ref_rgb)) < L.FILL_TOL)

    for name in FRAMES:
        rgb = L.load_rgb(L.AVATAR / f"{name}.png")
        if name == "gather":
            fg = ~L.flood_from_border(
                L.diff_map(rgb, L.border_bg(rgb)) < L.FILL_TOL)
            rgb = recolour_pants(rgb, fg, ref_rgb, ref_fg)
        rgba, st = L.key_image(rgb)
        bg = st["outside"]
        solid = rgba[..., 3] > 127

        ball_px = None
        if name in BALL_BOX:
            cx, cy, r, rms, n = ball_circle(rgb, bg, BALL_BOX[name])
            d = 2 * r
            yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]
            ball_px = (xx - cx) ** 2 + (yy - cy) ** 2 <= (r + 2.5) ** 2
            print(f"{name:11s} ball d={d:7.2f}  centre=({cx:7.2f},{cy:7.2f})  "
                  f"rms={rms:.2f}px  arc={n}")
        else:
            d = 142.60 * FOLLOWTHRU_VS_GATHER   # gather's ball, rescaled by the head NCC
            cx = cy = float("nan")
            print(f"{name:11s} ball d={d:7.2f}  (from head NCC vs gather, s={FOLLOWTHRU_VS_GATHER})")

        # release is the frame where the ball has left the hand: cut it out, so
        # the game's physics ball can take over at exactly that position.
        if name == "release":
            body = largest_component(solid & ~ball_px)
            loose = solid & ball_px
            art["ball"] = (rgba, loose)
        else:
            body = largest_component(solid)

        keep = body
        rgba = rgba.copy()
        rgba[..., 3][~keep] = 0.0

        ys, xs = np.where(keep)
        lo_y = ys.max() - int(LOWER_BODY * (ys.max() - ys.min()))
        legs = keep.copy()
        legs[:lo_y] = False
        ly, lx = np.where(legs)

        meas[name] = dict(ball_d=d, ball_cx=cx, ball_cy=cy,
                          scale=TARGET_BALL_D / d,
                          anchor_x=float(lx.mean()), ground_y=float(ys.max()),
                          bbox=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))
        art[name] = rgba

    # ---- common canvas: scale, then align on (anchor_x, ground_y)
    ext = []
    for n in FRAMES:
        m = meas[n]
        s = m["scale"]
        x0, y0, x1, y1 = m["bbox"]
        ext.append((( x0 - m["anchor_x"]) * s, (x1 - m["anchor_x"]) * s,
                    ( y0 - m["ground_y"]) * s, (y1 - m["ground_y"]) * s))
    min_x = min(e[0] for e in ext); max_x = max(e[1] for e in ext)
    min_y = min(e[2] for e in ext); max_y = max(e[3] for e in ext)

    CW = int(np.ceil(max_x - min_x)) + 2 * PAD
    CH = int(np.ceil(max_y - min_y)) + 2 * PAD
    ox = -min_x + PAD          # canvas x of each frame's anchor_x
    oy = -min_y + PAD          # canvas y of each frame's ground line
    print(f"\ncanvas {CW}x{CH}   anchor=({ox:.1f},{oy:.1f})")

    out = {}
    for n in FRAMES:
        m = meas[n]
        s = m["scale"]
        src = art[n]
        h, w = src.shape[:2]
        sw, sh = max(1, int(round(w * s))), max(1, int(round(h * s)))
        sc = premultiplied_resize(src, sw, sh)
        # top-left of the scaled image inside the canvas
        px = int(round(ox - m["anchor_x"] * s))
        py = int(round(oy - m["ground_y"] * s))
        canvas = np.zeros((CH, CW, 4), np.float32)
        sx0, sy0 = max(0, -px), max(0, -py)
        dx0, dy0 = max(0, px), max(0, py)
        cw = min(sw - sx0, CW - dx0)
        ch = min(sh - sy0, CH - dy0)
        canvas[dy0:dy0 + ch, dx0:dx0 + cw] = sc[sy0:sy0 + ch, sx0:sx0 + cw]
        out[n] = canvas
        path = L.AVATAR / f"shot-{n}.webp"
        L.save_webp(canvas, path, max_bytes=52_000, target=50_000)
        ys, xs = np.where(canvas[..., 3] > 20)
        print(f"  shot-{n:11s} scale={s:.4f}  bbox x[{xs.min()},{xs.max()}] "
              f"y[{ys.min()},{ys.max()}]  {path.stat().st_size/1024:.1f} KB")

    # ---- ball, cut from release
    rgba, loose = art["ball"]
    ys, xs = np.where(loose)
    b = rgba.copy()
    b[..., 3][~loose] = 0.0
    b = b[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(b.shape[0], b.shape[1])
    sq = np.zeros((side, side, 4), np.float32)
    sq[(side - b.shape[0]) // 2:(side - b.shape[0]) // 2 + b.shape[0],
       (side - b.shape[1]) // 2:(side - b.shape[1]) // 2 + b.shape[1]] = b
    BALL_OUT = 128
    ball = premultiplied_resize(sq, BALL_OUT, BALL_OUT)
    L.save_webp(ball, L.AVATAR / "ball.webp", max_bytes=14_000, target=13_000)
    print(f"  ball.webp    {BALL_OUT}x{BALL_OUT}  "
          f"{(L.AVATAR / 'ball.webp').stat().st_size/1024:.1f} KB")

    # ---- ball spawn point, in canvas coordinates
    m = meas["release"]
    s = m["scale"]
    spawn_x = ox + (m["ball_cx"] - m["anchor_x"]) * s
    spawn_y = oy + (m["ball_cy"] - m["ground_y"]) * s
    spawn_r = m["ball_d"] / 2 * s
    # ...and where the ball sits while he is still holding it, which is where the
    # aim UI has to anchor. The release point is above his head; hanging the
    # power ring there leaves it floating clear of the ball.
    mg = meas["gather"]
    held_x = ox + (mg["ball_cx"] - mg["anchor_x"]) * mg["scale"]
    held_y = oy + (mg["ball_cy"] - mg["ground_y"]) * mg["scale"]

    meta = dict(canvas=[CW, CH], anchor=[round(ox, 2), round(oy, 2)],
                spawn=[round(spawn_x, 2), round(spawn_y, 2)],
                held=[round(held_x, 2), round(held_y, 2)],
                ball_r=round(spawn_r, 2))
    print(f"\nball spawn in canvas coords: ({spawn_x:.1f}, {spawn_y:.1f})  r={spawn_r:.1f}")
    print(f"ball held  in canvas coords: ({held_x:.1f}, {held_y:.1f})")
    print(json.dumps(meta))
    (Path(__file__).parent / "shot_meta.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
