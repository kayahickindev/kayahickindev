# Card generators

Everything runs from this directory.

1. Fetch the source portrait (the GitHub avatar):
   `curl -sL "$(gh api user --jq .avatar_url)" -o avatar.png`
2. Regenerate the ASCII portrait (needs `pip install Pillow numpy`):
   `python3 ascii_v3.py` writes `ascii_art_C.txt` and prints the art.
3. Rebuild the SVGs:
   `cp ascii_art_C.txt ascii_art.txt && python3 build_svg.py`
   then `cp dark_mode.svg light_mode.svg ..` and commit.

Layout constraints: real char advance is 9.6px at font-size 16 (the
`size-adjust: 109%` trick), so art stays <= 37 cols at x=15 and the right
column sits at x=375 with 63-char lines. `update_readme.py` (repo root)
rewrites the tspan values by id nightly; if you add or rename a stat,
update its LINE_GROUPS and keep the sibling `*_dots` tspan.
