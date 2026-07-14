# Card generators

The committed `avatar.png` is the exact public-avatar source used for the
portrait. Its SHA-256 is
`d31f8862e6f2a4be9aa1d1c9b287107e9191d32c06a64446051b3f0678a22967`.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python tools/ascii_v3.py --preset balanced
.venv/bin/python tools/build_svg.py
.venv/bin/cairosvg dark_mode.svg -o dark_mode.png -s 1
.venv/bin/cairosvg light_mode.svg -o light_mode.png -s 1
```

`ascii_v3.py` also exposes the `legacy`, `open`, and `tight` presets so the
same crop/density comparison can be regenerated with `--preset` and
`--output`. `build_svg.py` accepts `--art` and `--output-dir` for rendering a
candidate without changing the committed card. By default it reads the latest
dynamic values from the committed `dark_mode.svg`, so rebuilding the portrait
does not reset daily statistics; `--stats-from` can select another snapshot.

Layout constraints: real character advance is 9.6px at font size 16 (the
`size-adjust: 109%` rule), so art stays at or below 37 columns at x=15 and the
right column sits at x=375 with 63-character content lines. The builder asserts
that alignment. `update_readme.py` rewrites the dynamic tspan values by id each
night. Product traction is read from the fresh snapshot rendered by
`kayahickin.com`; GitHub activity and LOC are refreshed with an authenticated
GitHub token. The update fails instead of publishing fallback site data or a
partial LOC total. LOC is summed from the authenticated user's non-merge commit
history on each code repository's default branch, avoiding GitHub's delayed
aggregate contributor-stat cache. If a stat is renamed, update `LINE_GROUPS`
and keep its sibling `*_dots` tspan.
