"""Key, transform, colour-match and export every pose into the 680x720 idle frame.

Stages:
  key     key + transform all poses, cache them, and write verification artifacts
  match   histogram-match dance2 to dance1 in LAB, with before/after
  export  write the final WebPs under the size budget
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import avatarlib as L
import measure_registration as M

MAGENTA = (255, 0, 255)
CACHE = "poses.npz"


def measure_transform(src, ref):
    rgb = L.load_rgb(L.AVATAR / src)
    m = M.landmarks(rgb, None, src)
    s = ref["head_w"] / m["head_w"]
    return s, ref["head_cx"] - m["head_cx"] * s, ref["top"] - m["top"] * s


def band(mask, a, b):
    """Ring between erosion depth a and depth b."""
    return L.erode(mask, a) & ~L.erode(mask, b)


def build(scratch):
    ref = M.landmarks(*M.load_rgba(L.AVATAR / "idle.webp"), "idle.webp")
    out = {}
    rows = []

    for stem, src in L.POSES.items():
        rgb = L.load_rgb(L.AVATAR / src)
        rgba, st = L.key_image(rgb)
        s, tx, ty = measure_transform(src, ref)

        # --- verification, in native space where the backdrop is still flat ---
        alpha = rgba[..., 3]
        # A correct key has exactly one transparent region: the outer backdrop.
        # Any transparent pixel not reachable from the frame border is a hole
        # punched through the subject. Counting alpha<255 instead would just
        # count the legitimate soft edge.
        clear = alpha < 128
        hole_mask = clear & ~L.flood_from_border(clear)
        holes = int(hole_mask.sum())
        # Curly hair legitimately has see-through gaps between strands, so a
        # nonzero hole count is expected and correct. What must be zero is holes
        # in the face, where they would be eaten eyes, teeth or nails.
        m = M.landmarks(rgb, None, src)
        hy, hx = np.nonzero(hole_mask)
        # Facial features only. A wider box catches the ear and hair silhouette
        # edges, where a stray transparent pixel is just the soft edge, not
        # damage: the eyes sit at +/-0.15 head widths, nowhere near +/-0.40.
        face_holes = int((((hy > m["top"] + m["head_w"] * 0.55) &
                           (hy < m["top"] + m["head_w"] * 1.15) &
                           (np.abs(hx - m["head_cx"]) < m["head_w"] * 0.30)).sum())
                         if holes else 0)
        residue = float(alpha[st["bg_core"]].max()) if st["bg_core"].any() else 0.0

        # Halo is backdrop colour surviving in partially-transparent edge pixels.
        # Measure it on the edge pixels themselves, as distance to the key colour
        # before and after de-spill: de-spill should push them away from it.
        e = st["edge"]
        if e.any():
            d_raw = float(L.diff_map(rgb.astype(np.float32), st["key"])[e].mean())
            d_fix = float(L.diff_map(rgba[..., :3], st["key"])[e].mean())
        else:
            d_raw = d_fix = 0.0
        halo, halo_raw = d_fix, d_raw

        frame = L.to_frame(rgba, s, tx, ty)
        out[stem] = frame
        rows.append(dict(stem=stem, src=src, key=st["key"], sim=st["similarity"],
                         protected=st["protected"], edge=st["edge_px"],
                         holes=holes, face_holes=face_holes,
                         residue=residue, halo=halo, halo_raw=halo_raw,
                         scale=s, tx=tx, ty=ty,
                         cover=float((frame[..., 3] > 0).mean())))

    print(f"{'pose':12} {'src':14} {'key':>7} {'sim':>6} {'protected':>10} {'edge px':>8} | "
          f"{'hair':>5} {'face':>5} {'residue':>8} {'edge d':>7} {'(raw)':>7} | "
          f"{'scale':>7} {'tx':>7} {'ty':>7}")
    for r in rows:
        print(f"{r['stem']:12} {r['src']:14} {'%02X%02X%02X' % r['key']:>7} {r['sim']:>6.4f} "
              f"{r['protected']:>10,} {r['edge']:>8,} | {r['holes']:>5} {r['face_holes']:>5} {r['residue']:>8.1f} "
              f"{r['halo']:>7.3f} {r['halo_raw']:>7.3f} | {r['scale']:>7.4f} "
              f"{r['tx']:>+7.1f} {r['ty']:>+7.1f}")

    ok = all(r["face_holes"] == 0 and r["residue"] == 0 for r in rows)
    print(f"\nface holes: {'0 across all poses -- nothing eaten' if ok else 'FAILURES ABOVE'}")
    print("hair  = see-through gaps between curly strands (expected, correct)")
    print("face  = eaten eyes/teeth/nails (must be 0)")
    print("protected = interior px a plain colour test at this similarity would have eaten")
    print("edge d    = mean colorkey distance of partial-alpha px from the backdrop,")
    print("            after de-spill vs (raw) before: higher after = less grey left in the edge")

    np.savez_compressed(scratch / CACHE, **{k: v.astype(np.float32) for k, v in out.items()})
    print(f"\ncached -> {scratch / CACHE}")
    return out


def sheets(frames, scratch):
    """Magenta composites plus 5x zooms of the regions most likely to break."""
    tw = 227
    cols = 4
    rows_n = (len(frames) + cols - 1) // cols
    th = int(tw * L.FRAME_H / L.FRAME_W)
    sheet = Image.new("RGB", (cols * tw, rows_n * (th + 16)), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, (stem, f) in enumerate(frames.items()):
        im = Image.fromarray(L.over(f, MAGENTA)).resize((tw, th), Image.LANCZOS)
        x, y = (i % cols) * tw, (i // cols) * (th + 16)
        sheet.paste(im, (x, y))
        d.text((x + 4, y + th + 3), stem, fill=(235, 235, 235))
    sheet.save(scratch / "magenta.png")

    ref = M.landmarks(*M.load_rgba(L.AVATAR / "idle.webp"), "idle.webp")
    cx, ey, hw = ref["head_cx"], ref["eye_y"], ref["head_w"]
    regions = {
        "hair edge": (int(cx - hw * .45), ref["top"] - 4, int(cx + hw * .45), ref["top"] + 46),
        "eyes": (int(cx - hw * .34), int(ey - 22), int(cx + hw * .34), int(ey + 20)),
    }
    for label, box in regions.items():
        w, h = box[2] - box[0], box[3] - box[1]
        strip = Image.new("RGB", (w * 3 * len(frames), h * 3), (24, 24, 28))
        for i, (stem, f) in enumerate(frames.items()):
            im = Image.fromarray(L.over(f, MAGENTA)).crop(box)
            strip.paste(im.resize((w * 3, h * 3), Image.NEAREST), (i * w * 3, 0))
        strip.save(scratch / f"zoom_{label.replace(' ', '_')}.png")

    # Hands differ per pose, so crop each pose's own lowest-hand region.
    strip = Image.new("RGB", (150 * 3 * len(frames), 120 * 3), (24, 24, 28))
    for i, (stem, f) in enumerate(frames.items()):
        a = f[..., 3] > 128
        skin = (f[..., 0] > f[..., 2] + 30) & (f[..., 0] > 120) & a
        ys, xs = np.nonzero(skin)
        below = ys > ref["top"] + hw * 1.4          # below the head: hands only
        if below.any():
            yc, xc = int(np.median(ys[below])), int(np.median(xs[below]))
        else:
            yc, xc = 400, 340
        box = (max(0, xc - 75), max(0, yc - 60), max(150, xc + 75), max(120, yc + 60))
        im = Image.fromarray(L.over(f, MAGENTA)).crop(box).resize((450, 360), Image.NEAREST)
        strip.paste(im, (i * 450, 0))
    strip.save(scratch / "zoom_hands.png")
    print(f"wrote magenta.png, zoom_hair_edge.png, zoom_eyes.png, zoom_hands.png -> {scratch}")


def lab_stats(lab):
    return [(float(lab[:, c].mean()), float(lab[:, c].std())) for c in range(3)]


def match(scratch):
    """Histogram-match dance2 to dance1 in LAB, on subject pixels only."""
    d = np.load(scratch / CACHE)
    a1, a2 = d["dance1"], d["dance2"]
    m1, m2 = a1[..., 3] > 128, a2[..., 3] > 128

    lab1 = L.rgb2lab(a1[..., :3][m1])
    lab2 = L.rgb2lab(a2[..., :3][m2])
    fixed = L.match_histogram(lab2, lab1)

    out = a2.copy()
    out[..., :3][m2] = L.lab2rgb(fixed)

    names = ["L", "a", "b"]
    print("LAB, subject pixels only        " + "  ".join(f"{n:>16}" for n in names))
    for label, st in [("dance1 (reference)", lab_stats(lab1)),
                      ("dance2 before", lab_stats(lab2)),
                      ("dance2 after", lab_stats(fixed))]:
        print(f"  {label:28} " + "  ".join(f"{m:>7.2f} +/-{s:>6.2f}" for m, s in st))

    b, af = lab_stats(lab2), lab_stats(fixed)
    r = lab_stats(lab1)
    print("\n  residual vs dance1           " +
          "  ".join(f"{af[c][0]-r[c][0]:>+7.2f} ({b[c][0]-r[c][0]:+.2f} before)" for c in range(3)))

    # Banding risk lives in the sweater: a narrow, heavily populated part of the
    # L histogram, where a steep CDF remap can collapse adjacent levels.
    dark = m2 & (L.rgb2lab(a2[..., :3])[..., 0] < 30)
    before_lv = len(np.unique(np.round(a2[..., :3][dark]).astype(int)))
    after_lv = len(np.unique(np.round(out[..., :3][dark]).astype(int)))
    print(f"\n  sweater region ({int(dark.sum()):,} px): {before_lv:,} distinct RGB levels before, "
          f"{after_lv:,} after  ({after_lv/max(before_lv,1)-1:+.1%})")

    tiles = [("dance1 (ref)", a1), ("dance2 before", a2), ("dance2 after", out)]
    tw, th = 340, 360
    sheet = Image.new("RGB", (tw * 3, th + 16), (24, 24, 28))
    dr = ImageDraw.Draw(sheet)
    for i, (lab, f) in enumerate(tiles):
        sheet.paste(Image.fromarray(L.over(f, (255, 255, 255))).resize((tw, th), Image.LANCZOS),
                    (i * tw, 0))
        dr.text((i * tw + 4, th + 3), lab, fill=(235, 235, 235))
    sheet.save(scratch / "colour_match.png")

    # Face patches at 3x: where a grade mismatch is most visible when alternating.
    box = (250, 150, 430, 290)
    w, h = box[2] - box[0], box[3] - box[1]
    strip = Image.new("RGB", (w * 3 * 3, h * 3), (24, 24, 28))
    for i, (lab, f) in enumerate(tiles):
        strip.paste(Image.fromarray(L.over(f, (255, 255, 255))).crop(box)
                    .resize((w * 3, h * 3), Image.NEAREST), (i * w * 3, 0))
    strip.save(scratch / "colour_match_face.png")

    np.savez_compressed(scratch / "dance2_matched.npz", dance2=out.astype(np.float32))
    print(f"\nwrote colour_match.png, colour_match_face.png -> {scratch}")


def export(scratch, lid="harvest"):
    """Write every layer as WebP under the size budget, then re-verify."""
    d = np.load(scratch / CACHE)
    frames = {k: d[k] for k in L.POSES}
    frames["dance2"] = np.load(scratch / "dance2_matched.npz")["dance2"]
    eye = np.load(scratch / "eye_layers.npz")
    frames["pupils"] = eye["pupils"]
    frames["eyes-closed"] = eye[lid]

    print(f"{'file':20} {'quality':>8} {'size':>10} {'budget':>8} {'psnr dB':>8} {'alpha':>16}")
    rows = []
    for stem, f in frames.items():
        p = L.AVATAR / f"{stem}.webp"
        q, n, psnr = L.save_webp(f, p)
        a = f[..., 3]
        cover = float((a > 0).mean())
        print(f"{p.name:20} {q:>8} {n/1024:>8.1f} KB {'OK' if n < 60_000 else 'OVER':>8} "
              f"{psnr:>8.1f} {cover*100:>13.1f}% ")
        rows.append((p.name, q, n, psnr))

    idle = (L.AVATAR / "idle.webp").stat().st_size
    print(f"\n{'idle.webp':20} {'lossless':>8} {idle/1024:>8.1f} KB {'master':>8}"
          f"        (registration reference, not re-encoded)")
    print(f"\ntotal shipped: {(sum(r[2] for r in rows) + idle)/1024:.0f} KB across "
          f"{len(rows)+1} files")

    print("\nregistration after keying, resampling and lossy encoding:")
    ref = M.landmarks(*M.load_rgba(L.AVATAR / "idle.webp"), "idle.webp")
    print(f"  {'file':16} {'head top':>9} {'head cx':>9} {'eye y':>8}   vs idle")
    for stem in L.POSES:
        m = M.landmarks(*M.load_rgba(L.AVATAR / f"{stem}.webp"), stem)
        print(f"  {stem:16} {m['top']:>9} {m['head_cx']:>9.1f} {m['eye_y']:>8.1f}   "
              f"dy {m['top']-ref['top']:+d}  dx {m['head_cx']-ref['head_cx']:+.1f}  "
              f"deye {m['eye_y']-ref['eye_y']:+.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["key", "match", "export"])
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--lid", choices=["synth", "harvest"], default="harvest")
    a = ap.parse_args()
    a.scratch.mkdir(parents=True, exist_ok=True)
    if a.stage == "key":
        sheets(build(a.scratch), a.scratch)
    elif a.stage == "match":
        match(a.scratch)
    elif a.stage == "export":
        export(a.scratch, a.lid)


if __name__ == "__main__":
    main()