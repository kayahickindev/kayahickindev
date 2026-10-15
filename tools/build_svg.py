"""Build dark_mode.svg and light_mode.svg for the kayahickindev profile README."""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CARD_W, CARD_H = 700, 489

# Full-width terminal readout. Identity and contact details live in the sidebar.
WIDTH = 63
X_RIGHT = 24
FS = 17
LINE_H = 23
Y0 = 32
BAR_X, BAR_Y, BAR_W, BAR_H = 24, 414, 652, 9
LEGEND_FS = 11
LEGEND_COLS = (24, 247, 470)
LEGEND_ROWS = (449, 472)
LEGEND_SLOTS = len(LEGEND_COLS) * len(LEGEND_ROWS)

# GitHub linguist colours, so the bar matches what each repo page shows.
LANGUAGE_COLORS = {
    "Swift": "#F05138", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Python": "#3572A5", "Kotlin": "#A97BFF", "Java": "#b07219",
    "Objective-C": "#438eff", "PLpgSQL": "#336790", "Shell": "#89e051",
    "HTML": "#e34c26", "CSS": "#663399", "SCSS": "#c6538c", "Ruby": "#701516",
    "Go": "#00ADD8", "Rust": "#dea584", "C++": "#f34b7d", "C": "#555555",
    "Dart": "#00B4AB", "MDX": "#fcb32c", "Dockerfile": "#384d54",
    "Makefile": "#427819", "Vim Script": "#199f4b", "Handlebars": "#f7931e",
}
OTHER_COLOR = "#8b949e"

parser = argparse.ArgumentParser()
parser.add_argument("--output-dir", type=Path, default=ROOT)
parser.add_argument("--stats-from", type=Path, default=ROOT / "dark_mode.svg")
parser.add_argument("--languages", type=Path, default=ROOT / "language_stats.json")
args = parser.parse_args()

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---- palettes ----
DARK = dict(bg="#161b22", fg="#c9d1d9", art="#8b949e", key="#ffa657",
            value="#a5d6ff", add="#3fb950", dele="#f85149", cc="#616e7f",
            track="#21262d")
LIGHT = dict(bg="#fffefe", fg="#24292f", art="#57606a", key="#953800",
             value="#0a3069", add="#1a7f37", dele="#cf222e", cc="#6e7781",
             track="#eaeef2")

# ---- right-column content ----
ID_TO_STAT = {
    "downloads_data": "downloads", "paid_data": "paid",
    "arr_data": "arr", "actions_data": "actions",
    "rating_data": "rating", "reviews_data": "reviews",
    "pr_data": "prs", "contribution_data": "contributions",
    "loc_add": "loc_add", "loc_del": "loc_del",
}
STATS = {}
for element in ET.parse(args.stats_from).getroot().iter():
    stat = ID_TO_STAT.get(element.attrib.get("id"))
    if stat and element.text:
        STATS[stat] = element.text

missing = set(ID_TO_STAT.values()) - STATS.keys()
if missing:
    raise RuntimeError(f"Refresh profile data before building: missing {sorted(missing)}")


def load_languages(path):
    """Top languages by GitHub-detected bytes, tail folded into `Other`.

    `update_readme.py` writes the byte totals it already collects while walking
    the repositories for lines of code, so the bar covers the same repository
    set as the LOC figure rather than a public-only subset.
    """
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("languages") or []
    total = sum(entry["bytes"] for entry in entries)
    if total <= 0:
        return []
    ranked = sorted(entries, key=lambda entry: -entry["bytes"])
    head, tail = ranked[: LEGEND_SLOTS - 1], ranked[LEGEND_SLOTS - 1 :]
    shown = [
        (entry["name"], entry["bytes"] / total * 100,
         LANGUAGE_COLORS.get(entry["name"], OTHER_COLOR))
        for entry in head
    ]
    tail_bytes = sum(entry["bytes"] for entry in tail)
    if tail_bytes:
        shown.append(("Other", tail_bytes / total * 100, OTHER_COLOR))
    return shown


LANGUAGES = load_languages(args.languages)


def header(label):
    # label + space + rule to full width
    rule = "─" * (WIDTH - len(label) - 1)
    return f'<tspan x="{X_RIGHT}" y="{{y}}">{esc(label)}</tspan> {rule}'


def kv(pairs, value_class="value"):
    """One line of `. Key: <dots> Value [| Key: <dots> Value]`, right edge at WIDTH.

    pairs: list of (key_markup, key_len, value_markup, value_len, dots_id)
    Dots are distributed so the line ends exactly at WIDTH chars.
    """
    fixed = 2  # ". "
    for i, (_, klen, _, vlen, _) in enumerate(pairs):
        fixed += klen + 1 + 2 + vlen  # key + ':' + two spaces around dots + value
        if i < len(pairs) - 1:
            fixed += 3  # " | "
    total_dots = max(len(pairs), WIDTH - fixed)
    parts = [f'<tspan x="{X_RIGHT}" y="{{y}}" class="cc">. </tspan>']
    for i, (kmk, klen, vmk, vlen, dots_id) in enumerate(pairs):
        if i < len(pairs) - 1:
            dots = min(4, total_dots - (len(pairs) - 1 - i))
        else:
            dots = total_dots
        total_dots -= dots
        idattr = f' id="{dots_id}_dots"' if dots_id else ""
        vid = f' id="{dots_id}"' if dots_id else ""
        parts.append(f'{kmk}:<tspan class="cc"{idattr}> {"." * dots} </tspan>'
                     f'<tspan class="{value_class}"{vid}>{vmk}</tspan>')
        if i < len(pairs) - 1:
            parts.append(" | ")
    return "".join(parts)


def key(name):
    """Markup + display length for a dotted key like Stack.Languages."""
    segs = name.split(".")
    mk = ".".join(f'<tspan class="key">{esc(s)}</tspan>' for s in segs)
    return mk, len(name)


def line_kv(name, value, dots_id=None, value_class="value"):
    kmk, klen = key(name)
    return kv([(kmk, klen, esc(value), len(value), dots_id)], value_class)


def line_kv2(n1, v1, id1, n2, v2, id2):
    k1, l1 = key(n1)
    k2, l2 = key(n2)
    return kv([(k1, l1, esc(v1), len(v1), id1), (k2, l2, esc(v2), len(v2), id2)])


rows = [
    header("Engineering"),
    line_kv("Platforms", "iOS, Android, Web"),
    line_kv("Languages", "Swift, TypeScript, Python"),
    line_kv("Frameworks", "SwiftUI, React Native, Next.js"),
    line_kv("Toolchain", "Claude Code, Codex, Ghostty, Wispr Flow, Herdr"),
    None,
    header("MyFutureSelf"),
    line_kv2("Downloads", STATS["downloads"], "downloads_data",
             "Paid subscriptions", STATS["paid"], "paid_data"),
    line_kv2("ARR", STATS["arr"], "arr_data",
             "Actions", STATS["actions"], "actions_data"),
    line_kv2("Rating", STATS["rating"], "rating_data",
             "Ratings", STATS["reviews"], "reviews_data"),
    None,
    header("GitHub"),
    line_kv("PRs merged", STATS["prs"], "pr_data"),
    line_kv("Contributions (1y)", STATS["contributions"], "contribution_data"),
    line_kv("Lines added", STATS["loc_add"], "loc_add", "addColor"),
    line_kv("Lines removed", STATS["loc_del"], "loc_del", "delColor"),
]


def language_markup(pal):
    """Rounded segmented bar plus a two-column legend, clipped to the bar."""
    if not LANGUAGES:
        return []
    out = [
        f'<clipPath id="barClip"><rect x="{BAR_X}" y="{BAR_Y}" '
        f'width="{BAR_W}" height="{BAR_H}" rx="{BAR_H / 2}"/></clipPath>',
        f'<rect x="{BAR_X}" y="{BAR_Y}" width="{BAR_W}" height="{BAR_H}" '
        f'rx="{BAR_H / 2}" fill="{pal["track"]}"/>',
        '<g clip-path="url(#barClip)">',
    ]
    offset = 0.0
    for _, percent, color in LANGUAGES:
        span = BAR_W * percent / 100.0
        out.append(f'<rect x="{BAR_X + offset:.2f}" y="{BAR_Y}" '
                   f'width="{span:.2f}" height="{BAR_H}" fill="{color}"/>')
        offset += span
    out.append("</g>")

    out.append(f'<g font-size="{LEGEND_FS}px" fill="{pal["fg"]}">')
    for index, (name, percent, color) in enumerate(LANGUAGES):
        x = LEGEND_COLS[index % len(LEGEND_COLS)]
        y = LEGEND_ROWS[index // len(LEGEND_COLS)]
        out.append(f'<circle cx="{x + 4}" cy="{y - 4}" r="4" fill="{color}"/>')
        out.append(f'<text x="{x + 14}" y="{y}">{esc(name)} '
                   f'<tspan class="cc">{percent:.1f}%</tspan></text>')
    out.append("</g>")
    return out


def build(pal):
    out = []
    out.append("<?xml version='1.0' encoding='UTF-8'?>")
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'font-family="ConsolasFallback,Consolas,monospace" '
        f'width="{CARD_W}px" height="{CARD_H}px" '
        f'viewBox="0 0 {CARD_W} {CARD_H}" font-size="{FS}px">'
    )
    out.append(f"""<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.key {{fill: {pal['key']};}}
.value {{fill: {pal['value']};}}
.addColor {{fill: {pal['add']};}}
.delColor {{fill: {pal['dele']};}}
.cc {{fill: {pal['cc']};}}
text, tspan {{white-space: pre;}}
</style>""")
    out.append(f'<rect width="{CARD_W}px" height="{CARD_H}px" fill="{pal["bg"]}" rx="15"/>')
    out.extend(language_markup(pal))
    out.append(f'<text x="{X_RIGHT}" y="{Y0}" fill="{pal["fg"]}">')
    for i, row in enumerate(rows):
        if row is None:
            continue
        y = Y0 + i * LINE_H
        out.append(row.replace("{y}", str(y)))
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


args.output_dir.mkdir(parents=True, exist_ok=True)
for filename, palette in (("dark_mode.svg", DARK), ("light_mode.svg", LIGHT)):
    (args.output_dir / filename).write_text(build(palette), encoding="utf-8")
print(f"wrote {args.output_dir / 'dark_mode.svg'}, {args.output_dir / 'light_mode.svg'}")

# All content stays inside the card; readout rows end on the same column.
assert X_RIGHT + WIDTH * (FS * 0.6) <= CARD_W
assert BAR_X + BAR_W <= CARD_W
assert max(LEGEND_ROWS) < CARD_H
assert Y0 + (len(rows) - 1) * LINE_H < BAR_Y
plain = re.compile(r"<[^>]+>")
for i, row in enumerate(rows):
    if row is None:
        continue
    txt = plain.sub("", row.replace("{y}", "0"))
    txt = txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if txt != ". ":
        assert len(txt) == WIDTH, (i, len(txt), txt)
    print(f"{i:2d} len={len(txt):3d} |{txt}")
for name, percent, color in LANGUAGES:
    print(f"lang {name:12s} {percent:6.2f}%  {color}")
