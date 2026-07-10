"""Portrait v3: supersampled tone + Sobel edge overlay with directional glyphs.

Each output cell averages an 8x8 high-res block (less sampling noise than v2's
single pixel). Cells sitting on a strong luminance edge render a directional
stroke (| / - \\) aligned with the contour, so silhouette lines read as lines.
"""
import numpy as np
from PIL import Image, ImageOps

COLS, ROWS = 37, 25
SS = 8
RAMP = " .,:;i1jftzY0Zkao#M8@$g"
EDGE_TH = 34.0          # mean |gradient| that counts as a contour
DENSE_T = 0.55          # tone above this keeps the fill glyph (hair/suit interior)

H_CROP = 410
W_CROP = int(H_CROP * (COLS * 9.6) / (ROWS * 20.0))
CX = 215
crop = (CX - W_CROP // 2, 0, CX + W_CROP // 2, H_CROP)

img = Image.open("avatar.png").convert("RGB").crop(crop)
hi = img.resize((COLS * SS, ROWS * SS), Image.LANCZOS)
hsv = np.asarray(hi.convert("HSV")).astype(np.int32)
gray = np.asarray(ImageOps.autocontrast(hi.convert("L"), cutoff=2)).astype(np.float64)

H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
bg = ((H >= 30) & (H <= 145) & (S > 15)) | ((S <= 20) & ~((H >= 145) & (V >= 200)))

# Sobel
gx = np.zeros_like(gray)
gy = np.zeros_like(gray)
gx[1:-1, 1:-1] = (gray[:-2, 2:] + 2 * gray[1:-1, 2:] + gray[2:, 2:]
                  - gray[:-2, :-2] - 2 * gray[1:-1, :-2] - gray[2:, :-2])
gy[1:-1, 1:-1] = (gray[2:, :-2] + 2 * gray[2:, 1:-1] + gray[2:, 2:]
                  - gray[:-2, :-2] - 2 * gray[:-2, 1:-1] - gray[:-2, 2:])
mag = np.hypot(gx, gy) / 4.0

def cell(y, x):
    sl = np.s_[y * SS:(y + 1) * SS, x * SS:(x + 1) * SS]
    b = bg[sl]
    if b.mean() > 0.6:
        return " "
    keep = ~b
    lum = gray[sl][keep].mean()
    t = ((255.0 - lum) / 255.0) ** 1.25
    strength = mag[sl][keep].mean()
    if strength > EDGE_TH and t < DENSE_T:
        vx = gx[sl][keep].mean()
        vy = gy[sl][keep].mean()
        ang = (np.degrees(np.arctan2(vy, vx)) + 180.0) % 180.0  # gradient dir
        # contour runs perpendicular to the gradient
        contour = (ang + 90.0) % 180.0
        if contour < 22.5 or contour >= 157.5:
            return "-"
        if contour < 67.5:
            return "/"
        if contour < 112.5:
            return "|"
        return "\\"
    idx = min(len(RAMP) - 1, int(t * len(RAMP)))
    return RAMP[idx]

lines = ["".join(cell(y, x) for x in range(COLS)) for y in range(ROWS)]

def blank(row, start, end=None):
    line = lines[row]
    end = len(line) if end is None else min(end, len(line))
    if start < len(line):
        lines[row] = line[:start] + " " * (end - start) + line[end:]

# fill single-space holes inside the hair mass
for r in (2, 3, 4, 5):
    s = lines[r]
    for i in range(2, len(s) - 1):
        if s[i] == " " and s[i - 1] not in " ." and s[i + 1] not in " .":
            s = s[:i] + s[i - 1] + s[i + 1:]
    lines[r] = s

lines = [l.rstrip() for l in lines]
with open("ascii_art_C.txt", "w") as f:
    f.write("\n".join(lines))
for i, l in enumerate(lines):
    print(f"{i:2d}|{l}")
