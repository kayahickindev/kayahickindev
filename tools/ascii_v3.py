"""Generate the profile's ASCII portrait from the committed GitHub avatar.

Glyph ink is halftone density, so it has to follow whichever direction reads
as "more ink" on the panel behind it. On the dark card, light glyphs mean ink
tracks *brightness*: the dark suit and hair fall away to near-empty while the
lit face and shirt carry the detail. On the light card the polarity flips, or
the portrait comes out as its own negative. Tone is error-diffused across a
short glyph ramp, which renders the portrait as a stipple rather than the
solid block of dense glyphs a straight luminance ramp produces.

The presets make crop/density comparisons reproducible. ``balanced`` is the
committed card portrait; the others are useful review candidates.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps


HERE = Path(__file__).resolve().parent
COLS, ROWS = 72, 56
CHAR_WIDTH, LINE_HEIGHT = 3.6, 7.5
SS = 5

# Glyph ramp with approximate ink coverage. Short on purpose: error diffusion
# turns the gaps between levels into stipple texture rather than banding.
RAMP: tuple[tuple[str, float], ...] = (
    (" ", 0.00),
    (".", 0.25),
    (":", 0.50),
    ("*", 0.75),
    ("o", 1.00),
)
#: Below these, a cell is flat panel rather than something worth a glyph.
EDGE_FLOOR = 0.16
INK_FLOOR = 0.07

RAMP_CHARS = np.array([glyph for glyph, _ in RAMP])
RAMP_INK = np.array([ink for _, ink in RAMP])


@dataclass(frozen=True)
class Tone:
    """How subject luminance becomes ink on one panel.

    The two panels are not mirror images of each other. On the dark card the
    navy suit is the empty end and can be clamped away wholesale; on the light
    card that same suit is the *inked* end, so it needs a low ceiling instead
    or it floods into one solid block.
    """

    #: Percentiles of subject luminance mapped to the tone range's ends.
    black_point: float
    white_point: float
    gamma: float
    #: Ink coverage of the most-inked cell; below 1.0 the extreme stays open.
    ceiling: float


@dataclass(frozen=True)
class Preset:
    #: Which backdrop the source photo has, and therefore how to cut it out.
    backdrop: str
    source: str
    center_x: int
    top: int
    height: int
    #: Broad-tone compression; below 1.0 keeps the lit shirt from filling in.
    base_gain: float
    #: Local-detail gain; above 1.0 is what makes eyes, brows and lapels read.
    detail_gain: float
    #: Extra ink along luminance edges, which is what draws the silhouette.
    edge_gain: float
    dark: Tone
    light: Tone


DARK_TONE = Tone(35.0, 99.0, 1.05, 0.95)
LIGHT_TONE = Tone(1.0, 99.0, 1.35, 0.62)

PRESETS = {
    # Studio headshot: a cut-out subject on white at 1024px, which resolves far
    # more detail per glyph cell than the 460px GitHub avatar can.
    "open": Preset("white", "headshot.png", 494, 82, 778,
                   0.80, 1.50, 0.55, DARK_TONE, LIGHT_TONE),
    "balanced": Preset("white", "headshot.png", 494, 96, 700,
                       0.80, 1.50, 0.55, DARK_TONE, LIGHT_TONE),
    "tight": Preset("white", "headshot.png", 494, 138, 616,
                    0.80, 1.50, 0.55, DARK_TONE, LIGHT_TONE),
    # The public GitHub avatar, shot against green foliage. Lower resolution
    # and a busy backdrop, so it resolves noticeably less of the face.
    "avatar": Preset("foliage", "avatar.png", 218, 14, 352,
                     0.80, 1.50, 0.45, Tone(20.0, 99.0, 1.05, 0.95), LIGHT_TONE),
}


#: Panel a portrait is drawn on, and therefore which end of the tone range the
#: glyphs have to fill in.
POLARITIES = ("dark", "light")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=PRESETS, default="balanced")
    parser.add_argument("--polarity", choices=POLARITIES, default=None,
                        help="build one panel's art; omit to build both")
    parser.add_argument("--source", type=Path, default=None,
                        help="override the preset's committed source photo")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def art_path(polarity: str) -> Path:
    return HERE / f"ascii_art_{polarity}.txt"


def crop_box(preset: Preset) -> tuple[int, int, int, int]:
    width = round(preset.height * (COLS * CHAR_WIDTH) / (ROWS * LINE_HEIGHT))
    left = preset.center_x - width // 2
    return left, preset.top, left + width, preset.top + preset.height


def flood_from_border(candidate: np.ndarray) -> np.ndarray:
    """Border-connected subset of ``candidate``.

    A studio cut-out and the subject's white shirt are the same colour, so a
    threshold alone deletes the shirt. Only the backdrop touches the frame
    edge, so reachability from the border separates them.
    """
    reached = np.zeros_like(candidate)
    reached[0] |= candidate[0]
    reached[-1] |= candidate[-1]
    reached[:, 0] |= candidate[:, 0]
    reached[:, -1] |= candidate[:, -1]
    while True:
        grown = reached.copy()
        grown[1:] |= reached[:-1]
        grown[:-1] |= reached[1:]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= candidate
        if grown.sum() == reached.sum():
            return grown
        reached = grown


def white_backdrop_mask(hsv: np.ndarray) -> np.ndarray:
    """True where a pixel belongs to a cut-out subject on white."""
    saturation, value = hsv[..., 1], hsv[..., 2]
    return ~flood_from_border((saturation <= 30) & (value >= 225))


def subject_mask(hsv: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """True where a pixel belongs to the portrait rather than green foliage."""
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    yy, xx = np.indices(shape)
    x_norm = xx / max(1, shape[1] - 1)
    y_norm = yy / max(1, shape[0] - 1)

    # The avatar background is green foliage. Preserve the neutral shirt only
    # in the center/lower subject region, while dropping pale bokeh and cars.
    green = (hue >= 30) & (hue <= 145) & (saturation > 15)
    pale_neutral = (saturation <= 48) & (value >= 138)
    shirt_region = (x_norm >= 0.30) & (x_norm <= 0.72) & (y_norm >= 0.58)
    background = green | (pale_neutral & ~shirt_region)

    # Remove isolated background at the extreme lower corners so that the
    # shoulders end in deliberate diagonals rather than stray glyph islands.
    lower_corner = (y_norm > 0.76) & (
        (x_norm < 0.10 + (y_norm - 0.76) * 0.45)
        | (x_norm > 0.94 - (y_norm - 0.76) * 0.18)
    )
    background |= lower_corner & green
    return ~background


def local_contrast(gray: np.ndarray, preset: Preset) -> np.ndarray:
    """Flatten broad tone and lift local detail.

    A headshot is mostly two big flat areas - lit shirt, dark suit - with the
    features living in small luminance steps. Straight tone mapping spends the
    whole ramp on the flat areas and erases the face, so the broad component is
    compressed and the high-pass residual is amplified before mapping.
    """
    blurred = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(radius=SS * 2.5)
        )
    ).astype(np.float64)
    mid = 128.0
    broad = mid + (blurred - mid) * preset.base_gain
    return broad + (gray - blurred) * preset.detail_gain


def largest_silhouette(drawn: np.ndarray) -> np.ndarray:
    """Keep only the subject mass, dropping stray background cells.

    Blurred foliage and pavement survive the colour masks in places; they show
    up as speckle islands that are never adjacent to the portrait. Growing a
    seed out from the centre column removes them without hand-tuned boxes.
    """
    rows, cols = drawn.shape
    seed = np.zeros_like(drawn)
    band = slice(int(cols * 0.35), int(cols * 0.65))
    seed[int(rows * 0.25) : int(rows * 0.95), band] = drawn[
        int(rows * 0.25) : int(rows * 0.95), band
    ]
    if not seed.any():
        return drawn
    reached = seed
    while True:
        grown = reached.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                grown |= np.roll(np.roll(reached, dy, axis=0), dx, axis=1)
        grown &= drawn
        # np.roll wraps; clear the wrapped edges so opposite sides never join.
        grown[0] &= drawn[0]
        if grown.sum() == reached.sum():
            return grown
        reached = grown


def edge_energy(gray: np.ndarray) -> np.ndarray:
    """Sobel magnitude, normalised to [0, 1]."""
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[1:-1, 1:-1] = (
        gray[:-2, 2:] + 2 * gray[1:-1, 2:] + gray[2:, 2:]
        - gray[:-2, :-2] - 2 * gray[1:-1, :-2] - gray[2:, :-2]
    )
    gy[1:-1, 1:-1] = (
        gray[2:, :-2] + 2 * gray[2:, 1:-1] + gray[2:, 2:]
        - gray[:-2, :-2] - 2 * gray[:-2, 1:-1] - gray[:-2, 2:]
    )
    magnitude = np.hypot(gx, gy)
    ceiling = np.percentile(magnitude, 99.0) or 1.0
    return np.clip(magnitude / ceiling, 0.0, 1.0)


def cell_fields(source: Path, preset: Preset) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-cell (subject coverage, mean subject luminance, edge energy)."""
    image = Image.open(source).convert("RGB").crop(crop_box(preset))
    high_res = image.resize((COLS * SS, ROWS * SS), Image.Resampling.LANCZOS)
    hsv = np.asarray(high_res.convert("HSV")).astype(np.int32)
    gray = np.asarray(
        ImageOps.autocontrast(high_res.convert("L"), cutoff=1)
    ).astype(np.float64)

    gray = np.clip(local_contrast(gray, preset), 0.0, 255.0)
    if preset.backdrop == "white":
        subject = white_backdrop_mask(hsv).astype(np.float64)
    else:
        subject = subject_mask(hsv, gray.shape).astype(np.float64)
    blocks = (ROWS, SS, COLS, SS)
    coverage = subject.reshape(blocks).mean(axis=(1, 3))
    weighted = (gray * subject).reshape(blocks).sum(axis=(1, 3))
    counted = subject.reshape(blocks).sum(axis=(1, 3))
    luminance = np.divide(
        weighted, counted, out=np.zeros_like(weighted), where=counted > 0
    )
    edges = (edge_energy(gray) * subject).reshape(blocks).mean(axis=(1, 3))
    return coverage, luminance, edges


def ink_field(
    coverage: np.ndarray,
    luminance: np.ndarray,
    edges: np.ndarray,
    preset: Preset,
    polarity: str = "dark",
) -> np.ndarray:
    """Map subject luminance onto target ink coverage in [0, ceiling]."""
    tone = preset.light if polarity == "light" else preset.dark
    drawn = largest_silhouette(coverage > 0.40)
    if not drawn.any():
        return np.zeros_like(luminance)
    values = luminance[drawn]
    black = np.percentile(values, tone.black_point)
    white = np.percentile(values, tone.white_point)
    span = max(1.0, white - black)
    normalized = np.clip((luminance - black) / span, 0.0, 1.0)
    if polarity == "light":
        normalized = 1.0 - normalized
    ink = (normalized**tone.gamma) * tone.ceiling
    # Tone alone leaves the dark hair and suit as empty panel, so the head has
    # no outline. Edge energy puts glyphs back exactly on those boundaries -
    # but only real boundaries, since sensor grain in the flat navy jacket
    # otherwise dithers into a field of speckle that reads as static.
    ink = np.clip(ink + np.where(edges > EDGE_FLOOR, edges, 0.0) * preset.edge_gain, 0.0, 1.0)
    ink[ink < INK_FLOOR] = 0.0
    # Partly covered cells sit on the silhouette edge; fade them out so the
    # outline dissolves into the panel instead of ending on a hard step.
    ink *= np.clip((coverage - 0.15) / 0.55, 0.0, 1.0)
    fringe = np.zeros_like(drawn)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            fringe |= np.roll(np.roll(drawn, dy, axis=0), dx, axis=1)
    return np.where(fringe & (coverage > 0.15), ink, 0.0)


def diffuse(ink: np.ndarray) -> list[str]:
    """Floyd-Steinberg the ink field onto the glyph ramp."""
    field = ink.astype(np.float64).copy()
    rows, cols = field.shape
    out = np.full((rows, cols), " ", dtype="<U1")
    for y in range(rows):
        for x in range(cols):
            target = field[y, x]
            index = int(np.argmin(np.abs(RAMP_INK - target)))
            out[y, x] = RAMP_CHARS[index]
            error = target - RAMP_INK[index]
            if x + 1 < cols:
                field[y, x + 1] += error * 7 / 16
            if y + 1 < rows:
                if x > 0:
                    field[y + 1, x - 1] += error * 3 / 16
                field[y + 1, x] += error * 5 / 16
                if x + 1 < cols:
                    field[y + 1, x + 1] += error * 1 / 16
    return ["".join(row).rstrip() for row in out]


def generate(source: Path, preset: Preset, polarity: str = "dark") -> list[str]:
    coverage, luminance, edges = cell_fields(source, preset)
    return diffuse(ink_field(coverage, luminance, edges, preset, polarity))


def main() -> None:
    args = parse_args()
    polarities = [args.polarity] if args.polarity else list(POLARITIES)
    if args.output and len(polarities) > 1:
        raise SystemExit("--output needs a single --polarity")
    for polarity in polarities:
        preset = PRESETS[args.preset]
        source = args.source or HERE / preset.source
        lines = generate(source, preset, polarity)
        output = args.output or art_path(polarity)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {output} with preset={args.preset} polarity={polarity}")


if __name__ == "__main__":
    main()
