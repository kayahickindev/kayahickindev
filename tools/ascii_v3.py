"""Generate the profile's ASCII portrait from the committed GitHub avatar.

The presets make crop/density comparisons reproducible. ``balanced`` is the
committed card portrait; the others are useful review candidates.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


HERE = Path(__file__).resolve().parent
COLS, ROWS = 37, 25
CHAR_WIDTH, LINE_HEIGHT = 9.6, 20.0
SS = 8
RAMP = " .,:;i1jftzY0Zkao#M8@$g"


@dataclass(frozen=True)
class Preset:
    center_x: int
    top: int
    height: int
    edge_threshold: float
    tone_gamma: float
    dense_threshold: float


PRESETS = {
    # Retained only to make the previous framing reproducible for comparisons.
    "legacy": Preset(215, 0, 410, 34.0, 1.25, 0.55),
    # Increasingly close head-and-shoulders treatments.
    "open": Preset(220, 0, 360, 32.0, 1.16, 0.57),
    "balanced": Preset(220, 0, 338, 30.0, 1.10, 0.59),
    "tight": Preset(220, 0, 318, 28.0, 1.04, 0.61),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", choices=PRESETS, default="balanced")
    parser.add_argument("--source", type=Path, default=HERE / "avatar.png")
    parser.add_argument("--output", type=Path, default=HERE / "ascii_art_C.txt")
    return parser.parse_args()


def crop_box(preset: Preset) -> tuple[int, int, int, int]:
    width = round(preset.height * (COLS * CHAR_WIDTH) / (ROWS * LINE_HEIGHT))
    left = preset.center_x - width // 2
    return left, preset.top, left + width, preset.top + preset.height


def generate(source: Path, preset: Preset) -> list[str]:
    image = Image.open(source).convert("RGB").crop(crop_box(preset))
    high_res = image.resize((COLS * SS, ROWS * SS), Image.Resampling.LANCZOS)
    hsv = np.asarray(high_res.convert("HSV")).astype(np.int32)
    gray = np.asarray(
        ImageOps.autocontrast(high_res.convert("L"), cutoff=2)
    ).astype(np.float64)

    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    yy, xx = np.indices(gray.shape)
    x_norm = xx / max(1, gray.shape[1] - 1)
    y_norm = yy / max(1, gray.shape[0] - 1)

    # The avatar background is green foliage. Preserve the neutral shirt only
    # in the center/lower subject region, while dropping pale bokeh and cars.
    green = (hue >= 30) & (hue <= 145) & (saturation > 15)
    pale_neutral = (saturation <= 24) & (value >= 150)
    shirt_region = (x_norm >= 0.30) & (x_norm <= 0.72) & (y_norm >= 0.58)
    background = green | (pale_neutral & ~shirt_region)

    # Remove isolated background at the extreme lower corners so that the
    # shoulders end in deliberate diagonals rather than stray glyph islands.
    lower_corner = (y_norm > 0.76) & (
        (x_norm < 0.10 + (y_norm - 0.76) * 0.45)
        | (x_norm > 0.94 - (y_norm - 0.76) * 0.18)
    )
    background |= lower_corner & green

    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[1:-1, 1:-1] = (
        gray[:-2, 2:]
        + 2 * gray[1:-1, 2:]
        + gray[2:, 2:]
        - gray[:-2, :-2]
        - 2 * gray[1:-1, :-2]
        - gray[2:, :-2]
    )
    gy[1:-1, 1:-1] = (
        gray[2:, :-2]
        + 2 * gray[2:, 1:-1]
        + gray[2:, 2:]
        - gray[:-2, :-2]
        - 2 * gray[:-2, 1:-1]
        - gray[:-2, 2:]
    )
    magnitude = np.hypot(gx, gy) / 4.0

    def cell(row: int, column: int) -> str:
        block = np.s_[row * SS : (row + 1) * SS, column * SS : (column + 1) * SS]
        block_background = background[block]
        if block_background.mean() > 0.60:
            return " "
        subject = ~block_background
        luminance = gray[block][subject].mean()
        tone = ((255.0 - luminance) / 255.0) ** preset.tone_gamma
        strength = magnitude[block][subject].mean()
        if strength > preset.edge_threshold and tone < preset.dense_threshold:
            vx = gx[block][subject].mean()
            vy = gy[block][subject].mean()
            gradient_angle = (
                np.degrees(np.arctan2(vy, vx)) + 180.0
            ) % 180.0
            contour = (gradient_angle + 90.0) % 180.0
            if contour < 22.5 or contour >= 157.5:
                return "-"
            if contour < 67.5:
                return "/"
            if contour < 112.5:
                return "|"
            return "\\"
        index = min(len(RAMP) - 1, int(tone * len(RAMP)))
        return RAMP[index]

    lines = ["".join(cell(y, x) for x in range(COLS)) for y in range(ROWS)]

    # Fill one-cell gaps inside the hair mass without inventing edge detail.
    for row in range(6):
        line = lines[row]
        for index in range(2, len(line) - 1):
            if (
                line[index] == " "
                and line[index - 1] not in " ."
                and line[index + 1] not in " ."
            ):
                line = line[:index] + line[index - 1] + line[index + 1 :]
        lines[row] = line

    return [line.rstrip() for line in lines]


def main() -> None:
    args = parse_args()
    lines = generate(args.source, PRESETS[args.preset])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for index, line in enumerate(lines):
        print(f"{index:2d}|{line}")
    print(f"wrote {args.output} with preset={args.preset}")


if __name__ == "__main__":
    main()
