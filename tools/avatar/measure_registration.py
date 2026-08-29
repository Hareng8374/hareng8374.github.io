"""Measure how each pose still registers against the master idle.webp reference.

For every image it locates the top of the head, the head width/height, the head
centre, and the eye line, then derives the similarity transform (uniform scale +
translate) that maps that image into the 680x720 idle frame.

The stills are 765x1024 and idle is 680x720, so the absolute transform is large
for every still and carries no signal on its own. The number that matters is how
far each still's transform deviates from the median across the set, because one
common crop recipe has to serve all of them. That deviation is what the 2%-of-
frame-height threshold is applied to.

Read-only: writes nothing except an optional landmark-overlay contact sheet.
"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
AVATAR = ROOT / "src" / "assets" / "avatar"
REFERENCE = "idle.webp"
STILLS = ["image.png", "wave1.png", "wave2.png", "wave3.png",
          "point.png", "thumbsup.png", "dance1.png", "dance2.png"]

SIMILARITY = 0.06
BLEND = 0.03
FLAG_FRAC = 0.02  # 2% of the idle frame height

# Head-geometry priors. Scale is taken from head WIDTH, not head height: the
# silhouette gives a clean temple-to-temple span, whereas the head/neck junction
# is not separable from the jaw once the mouth opens, which made an earlier
# height-based version report 12% scale swings that were purely detector noise.
HEAD_BAND = 0.30       # top..top+30% of image height is reliably skull
# Eye band, as multiples of head width below the head top. Excludes the mouth at
# every expression in this set, so open-mouth poses do not shift it.
EYE_LO, EYE_HI = 0.45, 0.95
FACE_HALF = 0.45       # face box half-width, as a multiple of head width


def load_rgba(path):
    im = Image.open(path)
    if im.mode == "RGBA":
        a = np.array(im)
        return a[..., :3], a[..., 3]
    rgb = np.array(im.convert("RGB"))
    return rgb, None


def border_bg(rgb, m=6):
    edges = np.concatenate([
        rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3),
        rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3),
    ])
    return tuple(int(v) for v in np.median(edges, axis=0))


def colorkey_alpha(rgb, key):
    d = rgb.astype(np.float32) / 255.0 - np.array(key, np.float32) / 255.0
    diff = np.sqrt((d ** 2).sum(axis=-1) / 3.0)
    return np.clip((diff - SIMILARITY) / BLEND, 0.0, 1.0)


def foreground(rgb, alpha):
    """Use the embedded alpha when present, else key each image on its own backdrop."""
    if alpha is not None:
        return alpha > 127, None
    bg = border_bg(rgb)
    return colorkey_alpha(rgb, bg) > 0.5, bg


def runs(row):
    """Contiguous foreground spans in a boolean row, as (start, end_exclusive)."""
    d = np.diff(np.concatenate([[0], row.view(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def track_head(mask, min_px=5):
    """Follow the head silhouette down from the crown, ignoring detached blobs.

    A raised hand beside the head is a separate run and never merges into the
    tracked span, so head width stays uncontaminated in the waving poses.
    """
    rows = np.flatnonzero(mask.sum(axis=1) >= min_px)
    if rows.size == 0:
        return None
    top = int(rows[0])
    spans, cur = {}, None
    for y in range(top, mask.shape[0]):
        rs = runs(mask[y])
        if not rs:
            break
        if cur is None:
            cur = max(rs, key=lambda r: r[1] - r[0])
        else:
            over = [r for r in rs if min(r[1], cur[1]) - max(r[0], cur[0]) > 0]
            if not over:
                break
            cur = max(over, key=lambda r: min(r[1], cur[1]) - max(r[0], cur[0]))
        spans[y] = cur
    return top, spans


def landmarks(rgb, alpha, name):
    h, w = rgb.shape[:2]
    mask, bg = foreground(rgb, alpha)
    tracked = track_head(mask)
    if tracked is None:
        raise RuntimeError(f"{name}: no foreground found")
    top, spans = tracked

    head_hi = top + int(HEAD_BAND * h)
    widths = {y: s[1] - s[0] for y, s in spans.items()}

    skull = [y for y in spans if top <= y < head_hi]
    head_w = max(widths[y] for y in skull)
    # Centre from the widest part of the skull, which is stable across expressions.
    wide = [y for y in skull if widths[y] >= 0.85 * head_w]
    head_cx = float(np.mean([(spans[y][0] + spans[y][1]) / 2 for y in wide]))

    eye_y, eye_src = eye_line(rgb, mask, top, head_w, head_cx)
    return dict(name=name, size=(w, h), bg=bg, top=top,
                head_w=head_w, head_cx=head_cx,
                eye_y=eye_y, eye_src=eye_src)


def eye_line(rgb, mask, top, head_w, head_cx):
    """Eye line from the irises; falls back to the brow band when the eyes are shut.

    An iris is dark and has bright, near-neutral sclera immediately beside it on
    the same row. Eyebrows and hair are dark too but have no sclera next to them,
    which is what separates them here. The search band is derived from head width
    rather than head height so it does not depend on the unreliable neck row.
    """
    h, w = mask.shape
    lo = max(0, top + int(EYE_LO * head_w))
    hi = min(h, top + int(EYE_HI * head_w))
    x0 = max(0, int(head_cx - FACE_HALF * head_w))
    x1 = min(w, int(head_cx + FACE_HALF * head_w))
    if hi <= lo or x1 <= x0:
        return float("nan"), "none"

    box = rgb[lo:hi, x0:x1].astype(np.int16)
    fg = mask[lo:hi, x0:x1]
    lum = box @ np.array([0.299, 0.587, 0.114])
    chroma = box.max(axis=-1) - box.min(axis=-1)

    sclera = (lum > 165) & (chroma < 30) & fg
    dark = (lum < 100) & fg

    # Horizontal dilation of the sclera mask: an iris sits within ~15% of head
    # width of the white beside it.
    reach = max(4, int(0.05 * head_w))
    near = np.zeros_like(sclera)
    for d in range(-reach, reach + 1):
        near |= np.roll(sclera, d, axis=1)

    iris = dark & near
    rows = np.arange(lo, hi, dtype=float)

    counts = iris.sum(axis=1).astype(float)
    if counts.sum() >= 30:
        return float(np.average(rows, weights=counts)), "iris"
    # Eyes shut: fall back to the brow band, still inside the face box only.
    counts = dark.sum(axis=1).astype(float)
    if counts.sum() > 0:
        return float(np.average(rows, weights=counts)), "brow*"
    return float("nan"), "none"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=Path, help="write a landmark-overlay contact sheet here")
    args = ap.parse_args()

    ref = landmarks(*load_rgba(AVATAR / REFERENCE), REFERENCE)
    ref_h = ref["size"][1]
    flag_px = FLAG_FRAC * ref_h

    measured = [landmarks(*load_rgba(AVATAR / n), n) for n in STILLS]

    print(f"reference: {REFERENCE}  {ref['size'][0]}x{ref['size'][1]}")
    print(f"  head top y={ref['top']}  head w={ref['head_w']}  cx={ref['head_cx']:.1f}"
          f"  eye y={ref['eye_y']:.1f} ({ref['eye_src']})")
    print(f"  head-top -> eye line = {ref['eye_y'] - ref['top']:.1f}px "
          f"= {(ref['eye_y'] - ref['top']) / ref['head_w']:.3f} head widths\n")

    print("RAW LANDMARKS (native pixels)")
    print(f"{'file':14} {'size':>9} {'bg':>7} {'headtop':>8} {'head w':>7} {'head cx':>8} "
          f"{'eye y':>7} {'src':>6} {'top->eye':>9}")
    for m in measured:
        bg = "%02X%02X%02X" % m["bg"] if m["bg"] else "-"
        print(f"{m['name']:14} {'%dx%d' % m['size']:>9} {bg:>7} {m['top']:>8} "
              f"{m['head_w']:>7} {m['head_cx']:>8.1f} {m['eye_y']:>7.1f} "
              f"{m['eye_src']:>6} {m['eye_y'] - m['top']:>9.1f}")

    # Similarity transform into the idle frame: uniform scale from head width,
    # then translate so head top and head centre coincide with the reference.
    for m in measured:
        s = ref["head_w"] / m["head_w"]
        m["scale"] = s
        m["tx"] = ref["head_cx"] - m["head_cx"] * s
        m["ty"] = ref["top"] - m["top"] * s
        m["eye_mapped"] = m["eye_y"] * s + m["ty"]

    med_s = float(np.median([m["scale"] for m in measured]))
    med_tx = float(np.median([m["tx"] for m in measured]))
    med_ty = float(np.median([m["ty"] for m in measured]))

    print(f"\nTRANSFORM INTO THE {ref['size'][0]}x{ref['size'][1]} IDLE FRAME")
    print(f"  group median: scale {med_s:.4f}  tx {med_tx:+.1f}  ty {med_ty:+.1f}")
    print(f"  flag threshold: {FLAG_FRAC:.0%} of {ref_h}px = {flag_px:.1f}px "
          f"(and {FLAG_FRAC:.0%} on scale)\n")

    hdr = (f"{'file':14} {'scale':>7} {'tx':>8} {'ty':>8} | {'dScale':>8} {'dX px':>7} "
           f"{'dY px':>7} {'eyeRes':>7} | flags")
    print(hdr)
    print("-" * len(hdr))

    for m in measured:
        d_s = m["scale"] / med_s - 1.0
        d_x = m["tx"] - med_tx
        d_y = m["ty"] - med_ty
        eye_res = m["eye_mapped"] - ref["eye_y"]

        flags = []
        if abs(d_s) > FLAG_FRAC:
            flags.append(f"SCALE {d_s:+.1%}")
        if abs(d_x) > flag_px:
            flags.append(f"X {d_x:+.0f}px")
        if abs(d_y) > flag_px:
            flags.append(f"Y {d_y:+.0f}px")
        if abs(eye_res) > flag_px:
            flags.append(f"EYELINE {eye_res:+.0f}px")
        if m["eye_src"] != "iris":
            flags.append(f"eye={m['eye_src']}")
        m["flags"] = flags

        print(f"{m['name']:14} {m['scale']:>7.4f} {m['tx']:>+8.1f} {m['ty']:>+8.1f} | "
              f"{d_s:>+7.2%} {d_x:>+7.1f} {d_y:>+7.1f} {eye_res:>+7.1f} | "
              f"{'  '.join(flags) if flags else 'ok'}")

    print("\ndScale/dX/dY = deviation from the group median transform.")
    print("eyeRes = eye-line error after the transform aligns head top, centre and scale;")
    print("         a large value means the face proportions differ, not just the framing.")

    if args.sheet:
        overlay_sheet([ref] + measured, args.sheet)
        print(f"\nlandmark overlay -> {args.sheet}")


def overlay_sheet(items, out):
    tw = 300
    cells = []
    for m in items:
        src = Image.open(AVATAR / m["name"])
        # Flatten onto the same grey the stills use, so idle.webp's transparent
        # region does not render as undefined RGB.
        im = Image.new("RGB", src.size, (214, 214, 214))
        im.paste(src, (0, 0), src if src.mode == "RGBA" else None)
        d = ImageDraw.Draw(im)
        w, h = im.size
        cx = m["head_cx"]
        d.line([(0, m["top"]), (w, m["top"])], fill=(255, 60, 60), width=3)
        if not np.isnan(m["eye_y"]):
            d.line([(0, m["eye_y"]), (w, m["eye_y"])], fill=(60, 160, 255), width=3)
        d.line([(cx, 0), (cx, h)], fill=(255, 220, 40), width=3)
        half = m["head_w"] / 2
        d.rectangle([cx - half, m["top"], cx + half, m["top"] + m["head_w"] * 1.25],
                    outline=(255, 120, 255), width=3)
        th = int(tw * h / w)
        cells.append((m, im.resize((tw, th), Image.LANCZOS)))

    ch = max(c[1].height for c in cells)
    cols = 5
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (ch + 20)), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, (m, im) in enumerate(cells):
        x, y = (i % cols) * tw, (i // cols) * (ch + 20)
        sheet.paste(im, (x, y))
        label = f"{m['name']}  eye:{m['eye_src']}"
        if m.get("flags"):
            label += "  !" + ",".join(f.split()[0] for f in m["flags"])
        d.text((x + 4, y + ch + 4), label, fill=(235, 235, 235))
    sheet.save(out)


if __name__ == "__main__":
    main()
