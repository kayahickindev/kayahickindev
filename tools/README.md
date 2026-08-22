# Card generators

`ascii_v3.py` draws the portrait, `build_svg.py` assembles the two cards.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python tools/ascii_v3.py --preset balanced
.venv/bin/python tools/build_svg.py
.venv/bin/cairosvg dark_mode.svg -o dark_mode.png -s 1
.venv/bin/cairosvg light_mode.svg -o light_mode.png -s 1
```

`cairosvg` has no Consolas, so its output is only useful for checking colour and
block placement. To eyeball the monospace columns, substitute a local face first:
`sed 's/ConsolasFallback,Consolas,monospace/Menlo/' dark_mode.svg > /tmp/card.svg`.

## Portrait

The committed source is `headshot.png`, the studio headshot that is also the
public GitHub avatar, at 2048px, SHA-256
`5508f9f83832d7bfc3ceb27ec8f84084d5fdf0f79ca4fd71f322bf58f203c3f1`. It is kept
at full resolution deliberately: the crop is roughly a third of the frame, and
at 1024px the glyph grid was sampling it at close to 1:1, so there was no
detail left to supersample away.

The 430-column grid is the source's ceiling, not an arbitrary choice: the crop
is about 860 source pixels wide, so each cell already covers two of them. Finer
grids past this point invent detail rather than resolve it. Glyphs this small
are sub-pixel, so the browser integrates them into continuous tone; the ramp
still matters because a heavier glyph deposits more coverage per cell. That
also means `rim_gain` draws a sub-pixel line and contributes little at this
density - both it and `interior_floor` earn their keep only on coarser grids,
which the presets can still be regenerated at. The subject
is shot against a flat light backdrop, which `flood_from_border` separates from
the white shirt by reachability rather than by threshold. `open`, `balanced` and
`tight` differ only in how much shoulder they keep; `--source` overrides the
photo.

Framing is measured on the head, not the body: the subject's shoulders run off
the right of the source frame, so centring on the bounding box would sit the
face left of centre.

Glyphs are halftone density, error-diffused across a short ramp rather than
mapped straight onto a long one, which is what makes the portrait read as a
stipple instead of a solid slab. Two terms exist only to hold the figure
together: `rim_gain` inks the cutout's own boundary, because the hair is wispy
and backlit and its luminance edge comes out as broken scatter, and
`interior_floor` puts a faint dot field under every cell inside the silhouette,
because the widest part of the head is dark hair that otherwise maps to no ink
at all and leaves the portrait looking like debris. Density has to follow the panel it sits on:
`--polarity dark` inks the *bright* end, because light glyphs on the dark card
mean the navy suit falls away and the lit face carries the detail; `--polarity
light` inks the dark end. Each polarity has its own tone curve, since the two
are not mirror images - the dark card can clamp the suit away wholesale, while
the light card has to hold it under a low ceiling or it floods into one block.
Running with no `--polarity` writes both `ascii_art_dark.txt` and
`ascii_art_light.txt`; `build_svg.py` picks the one matching each palette.

## Layout

Real character advance is 0.6 x font size (the `size-adjust: 109%` rule). The
portrait is 430 columns of 0.6px and 412 rows of 1.0px at font size 1; the
readout is 63 characters of 10.2px at font size 17, starting at x=318. The
builder asserts that the portrait, the language block and the readout all stay
inside the 985x545 card, and that every readout line ends on the same column -
a silently clamped leader is what let the lines-of-code row run two columns
long and clip off the right edge. The card carries a `viewBox`, so a narrow
README column scales it down instead of cutting it off.

## Data

`update_readme.py` rewrites the dynamic tspan values by id each night, then the
workflow reruns `build_svg.py` to redraw both panels. Product traction is read
from the fresh snapshot rendered by `kayahickin.com`; GitHub activity, LOC and
the language-bar byte totals are refreshed with an authenticated GitHub token.
The update fails instead of publishing fallback site data or a partial LOC
total. LOC is summed from the authenticated user's non-merge commit history on
each code repository's default branch, avoiding GitHub's delayed aggregate
contributor-stat cache. `language_stats.json` records the same repositories'
GitHub-detected language bytes, so the bar covers the same set as the LOC
figure rather than a public-only subset. If a stat is renamed, update
`LINE_GROUPS` and keep its sibling `*_dots` tspan.
