"""Rekey ballspin.webm and ballspin-poster.webp with the topological flood fill.

Both shipped files were keyed with a plain colour test, which punched holes
through the face wherever a pixel sat inside the key tolerance -- the sclera
especially. The webm's colour plane still carries the untouched D3D3D3 backdrop
(alpha lives in a WebM side-channel), and the clip is mp4 frames 20-119, so the
cleanest fix is to re-derive both from the source mp4 rather than rekey an
already-compressed frame.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import avatarlib as L

SRC = L.AVATAR / "Using_the_original_provided_im.mp4"
WEBM = L.AVATAR / "ballspin.webm"
POSTER = L.AVATAR / "ballspin-poster.webp"

SRC_W, SRC_H = 1280, 720
CROP_X = 340
OFFSET, COUNT, FPS = 20, 100, 24
KEY_RGB = (0xD3, 0xD3, 0xD3)

# Facial-feature box in frame coordinates, from idle.webp's landmarks widened
# for the head drift across the clip.
FACE = (205, 170, 385, 340)
EDGE_SLIVER = 3   # px from the backdrop within which a hole is an edge pinch


def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def source_frames():
    raw = subprocess.run([ffmpeg(), "-v", "error", "-i", str(SRC),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, SRC_H, SRC_W, 3)
    return a[OFFSET:OFFSET + COUNT, :, CROP_X:CROP_X + 680]


def face_holes(alpha):
    """(total holes, real damage inside the face box).

    A transparent pixel touching the backdrop is a pinch in the silhouette --
    the soft edge biting one pixel deep -- not an eaten feature. Real damage is
    a hole sitting well inside the subject, like a sclera or a fingernail. So
    holes within EDGE_SLIVER px of the flood-filled backdrop are discounted.
    """
    clear = alpha < 128
    bg = L.flood_from_border(clear)
    hm = clear & ~bg
    deep = hm & ~L.dilate(bg, EDGE_SLIVER)
    x0, y0, x1, y1 = FACE
    return int(hm.sum()), int(deep[y0:y1, x0:x1].sum())


def encode(frames, out, crf):
    cmd = [ffmpeg(), "-v", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgba", "-s", "680x720", "-r", str(FPS), "-i", "-",
           "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
           "-b:v", "0", "-crf", str(crf), "-row-mt", "1", "-auto-alt-ref", "0",
           str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.clip(f + 0.5, 0, 255).astype(np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg encode failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crf", type=int, default=30)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    src = source_frames()
    print(f"source: mp4 frames {OFFSET}..{OFFSET+COUNT-1}, cropped 680x720 at x={CROP_X}")

    keyed, tot, worst = [], 0, (0, -1)
    for i, f in enumerate(src):
        rgba, st = L.key_image(f, key=KEY_RGB)
        keyed.append(rgba)
        h, fh = face_holes(rgba[..., 3])
        tot += h
        if fh > worst[0]:
            worst = (fh, i)
    print(f"keyed {len(keyed)} frames: similarity {st['similarity']:.4f}, "
          f"blend {st['blend']}")
    print(f"  interior holes total {tot:,} (hair gaps + edge pinches)")
    print(f"  worst FACE damage in any frame: {worst[0]} px (frame {worst[1]})")

    if worst[0] != 0:
        print("  FACE HOLES PRESENT -- not writing")
        return 1

    if not a.write:
        print("  (dry run; pass --write)")
        return 0

    encode(keyed, WEBM, a.crf)
    Image.fromarray(np.clip(keyed[0] + 0.5, 0, 255).astype(np.uint8), "RGBA").save(
        POSTER, "WEBP", quality=82, method=6, alpha_quality=100)
    print(f"\nwrote {WEBM.name} {WEBM.stat().st_size/1024:.1f} KB (crf {a.crf})")
    print(f"wrote {POSTER.name} {POSTER.stat().st_size/1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
