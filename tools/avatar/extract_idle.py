"""Extract the master neutral idle still from the source mp4.

Decodes frames 0-19 (before the ball appears), crops each to the exact
ballspin.webm window (680x720 at x=340), scores sharpness, writes a contact
sheet for visual selection, and on --frame N keys and saves idle.webp.

Keying reproduces ffmpeg's vf_colorkey math exactly:
    diff  = sqrt((dr^2 + dg^2 + db^2) / 3)     on 0..1 normalised channels
    alpha = clip((diff - similarity) / blend, 0, 1)
colorkey (RGB distance), not chromakey (U/V distance): the backdrop is neutral
grey, and a U/V test would also key the subject's desaturated pixels.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
AVATAR = ROOT / "src" / "assets" / "avatar"
SRC = AVATAR / "Using_the_original_provided_im.mp4"

SRC_W, SRC_H = 1280, 720
CROP_X, CROP_W, CROP_H = 340, 680, 720
N_FRAMES = 20

KEY_RGB = (0xD3, 0xD3, 0xD3)
SIMILARITY = 0.06
BLEND = 0.03


def decode_frames(n=N_FRAMES):
    """Decode the first n frames of the source as an (n, H, W, 3) uint8 array."""
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [exe, "-v", "error", "-i", str(SRC), "-frames:v", str(n),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout
    frame_bytes = SRC_W * SRC_H * 3
    got = len(raw) // frame_bytes
    return np.frombuffer(raw[: got * frame_bytes], np.uint8).reshape(got, SRC_H, SRC_W, 3)


def crop(frame):
    return frame[:, CROP_X:CROP_X + CROP_W]


def colorkey_alpha(rgb, key=KEY_RGB, similarity=SIMILARITY, blend=BLEND):
    """ffmpeg vf_colorkey alpha, as float32 0..1."""
    d = rgb.astype(np.float32) / 255.0 - np.array(key, np.float32) / 255.0
    diff = np.sqrt((d ** 2).sum(axis=-1) / 3.0)
    if blend > 0.0001:
        return np.clip((diff - similarity) / blend, 0.0, 1.0)
    return (diff > similarity).astype(np.float32)


def foreground_mask(rgb):
    return colorkey_alpha(rgb) > 0.5


def head_box(mask, min_px=5):
    """(top, bottom, left, right) of the head blob, using the row-width profile."""
    widths = mask.sum(axis=1)
    rows = np.flatnonzero(widths >= min_px)
    if rows.size == 0:
        return None
    top = int(rows[0])
    # Head then neck then shoulders: find the neck as the narrowest row in the
    # band below the widest part of the head and above the shoulder flare.
    search_lo = top + 40
    search_hi = min(mask.shape[0] - 1, top + int(mask.shape[0] * 0.75))
    band = widths[search_lo:search_hi]
    if band.size == 0:
        return None
    head_peak = int(np.argmax(band[: max(1, band.size // 2)])) + search_lo
    after = widths[head_peak:search_hi]
    neck = int(np.argmin(after)) + head_peak
    cols = np.flatnonzero(mask[top:neck].any(axis=0))
    if cols.size == 0:
        return None
    return top, neck, int(cols[0]), int(cols[-1])


def laplacian_var(gray):
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float32)
    g = gray.astype(np.float32)
    out = np.zeros_like(g)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            w = k[dy + 1, dx + 1]
            if w:
                out[1:-1, 1:-1] += w * g[1 + dy:g.shape[0] - 1 + dy, 1 + dx:g.shape[1] - 1 + dx]
    return float(out[1:-1, 1:-1].var())


def border_bg(rgb, m=6):
    """Median colour of the frame border — the true backdrop value."""
    edges = np.concatenate([
        rgb[:m].reshape(-1, 3), rgb[-m:].reshape(-1, 3),
        rgb[:, :m].reshape(-1, 3), rgb[:, -m:].reshape(-1, 3),
    ])
    return tuple(int(v) for v in np.median(edges, axis=0))


def analyse(frames):
    rows = []
    for i, f in enumerate(frames):
        c = crop(f)
        gray = c.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        box = head_box(foreground_mask(c))
        if box:
            top, neck, left, right = box
            face_lo = top + int((neck - top) * 0.30)
            face = gray[face_lo:neck, left:right]
            sharp = laplacian_var(face)
        else:
            top = neck = left = right = -1
            sharp = laplacian_var(gray)
        rows.append(dict(idx=i, sharp=sharp, bg=border_bg(c),
                         top=top, neck=neck, left=left, right=right))
    return rows


def contact_sheet(frames, rows, out):
    cols, thumb_w = 5, 238
    thumb_h = int(thumb_w * CROP_H / CROP_W)
    n_rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, n_rows * (thumb_h + 18)), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    best = max(r["sharp"] for r in rows)
    for r in rows:
        i = r["idx"]
        t = Image.fromarray(crop(frames[i])).resize((thumb_w, thumb_h), Image.LANCZOS)
        x, y = (i % cols) * thumb_w, (i // cols) * (thumb_h + 18)
        sheet.paste(t, (x, y))
        mark = "  <-- sharpest" if r["sharp"] == best else ""
        d.text((x + 4, y + thumb_h + 4),
               f"f{i:02d}  lapvar {r['sharp']:.0f}{mark}", fill=(235, 235, 235))
    sheet.save(out)


def save_idle(frames, idx, out):
    """Key with the topological method from avatarlib.

    A plain colour test cannot be used here: this render's sclera is bright and
    desaturated enough to fall inside the key tolerance, and an earlier
    colour-only version of this function punched a ~200px transparent hole
    through his right eye. avatarlib.key_image protects anything the backdrop
    flood fill cannot reach, and de-spills the soft edge.
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import avatarlib as AL

    c = crop(frames[idx])
    rgba, st = AL.key_image(c, key=KEY_RGB)
    clear = rgba[..., 3] < 128
    holes = int((clear & ~AL.flood_from_border(clear)).sum())
    print(f"  similarity {st['similarity']:.4f}  blend {st['blend']}  "
          f"protected {st['protected']:,}px  soft edge {st['edge_px']:,}px  "
          f"interior holes {holes}")
    Image.fromarray(np.clip(rgba + 0.5, 0, 255).astype(np.uint8), "RGBA").save(
        out, "WEBP", lossless=True, quality=100, method=6, exact=True)
    return rgba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", type=int, help="frame index to key and save as idle.webp")
    ap.add_argument("--sheet", type=Path, help="write a contact sheet here")
    args = ap.parse_args()

    frames = decode_frames()
    rows = analyse(frames)

    print(f"source {SRC.name}: decoded {len(frames)} frames at {SRC_W}x{SRC_H}")
    print(f"crop window: {CROP_W}x{CROP_H} at x={CROP_X}, y=0\n")
    print(f"{'frame':>5}  {'lapvar(face)':>12}  {'bg':>8}  {'head top':>8}  "
          f"{'neck':>6}  {'head w':>7}  {'head cx':>8}")
    for r in rows:
        bg = "%02X%02X%02X" % r["bg"]
        hw = r["right"] - r["left"]
        cx = (r["right"] + r["left"]) / 2
        print(f"{r['idx']:>5}  {r['sharp']:>12.1f}  {bg:>8}  {r['top']:>8}  "
              f"{r['neck']:>6}  {hw:>7}  {cx:>8.1f}")

    best = max(rows, key=lambda r: r["sharp"])
    print(f"\nsharpest: frame {best['idx']} (lapvar {best['sharp']:.1f})")
    print(f"measured backdrop: {'%02X%02X%02X' % best['bg']}   "
          f"specified key: {'%02X%02X%02X' % KEY_RGB}")

    if args.sheet:
        contact_sheet(frames, rows, args.sheet)
        print(f"contact sheet -> {args.sheet}")

    if args.frame is not None:
        out = AVATAR / "idle.webp"
        rgba = save_idle(frames, args.frame, out)
        a = rgba[..., 3]
        print(f"\nwrote {out}  {rgba.shape[1]}x{rgba.shape[0]} RGBA  "
              f"{out.stat().st_size / 1024:.0f} KB")
        print(f"  corners alpha: {a[0,0]} {a[0,-1]} {a[-1,0]} {a[-1,-1]}  (want 0)")
        print(f"  fully opaque: {(a == 255).mean() * 100:.1f}%   "
              f"fully clear: {(a == 0).mean() * 100:.1f}%   "
              f"partial: {((a > 0) & (a < 255)).mean() * 100:.2f}%")


if __name__ == "__main__":
    sys.exit(main())
