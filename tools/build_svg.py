"""Build dark_mode.svg and light_mode.svg for the kayahickindev profile README."""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

CARD_W, CARD_H = 985, 545

# ---- left column: portrait, language bar, legend ----
COLS, ROWS = 86, 67
ART_X, ART_Y0 = 15, 24
ART_FS, ART_ADVANCE, ART_LINE_H = 5, 3.0, 6.25
ART_W = COLS * ART_ADVANCE

BAR_X, BAR_Y, BAR_W, BAR_H = ART_X, 462, 260, 9
LEGEND_FS = 10.5
LEGEND_COLS = (ART_X, ART_X + 135)
LEGEND_ROWS = (492, 512, 532)
LEGEND_SLOTS = len(LEGEND_COLS) * len(LEGEND_ROWS)

# ---- right column: the terminal readout ----
WIDTH = 63  # right-column line width in chars
X_RIGHT = 318
FS = 17
LINE_H = 21
Y0 = 30

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
parser.add_argument("--art-dark", type=Path, default=HERE / "ascii_art_dark.txt")
parser.add_argument("--art-light", type=Path, default=HERE / "ascii_art_light.txt")
parser.add_argument("--output-dir", type=Path, default=ROOT)
parser.add_argument("--stats-from", type=Path, default=ROOT / "dark_mode.svg")
parser.add_argument("--languages", type=Path, default=ROOT / "language_stats.json")
args = parser.parse_args()

def read_art(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= ROWS, (path, len(lines))
    assert max(len(line) for line in lines) <= COLS, (path, max(map(len, lines)))
    return lines + [""] * (ROWS - len(lines))


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---- palettes ----
DARK = dict(bg="#161b22", fg="#c9d1d9", art="#8b949e", key="#ffa657",
            value="#a5d6ff", add="#3fb950", dele="#f85149", cc="#616e7f",
            track="#21262d", art_source=args.art_dark)
LIGHT = dict(bg="#fffefe", fg="#24292f", art="#57606a", key="#953800",
             value="#0a3069", add="#1a7f37", dele="#cf222e", cc="#6e7781",
             track="#eaeef2", art_source=args.art_light)

# ---- right-column content ----
STATS = {
    "age": "22 years, 5 months, 21 days",
    "downloads": "30K+", "paid": "2,737+",
    "arr": "$113K+", "actions": "163K+",
    "rating": "4.7", "reviews": "973",
    "repos": "10", "prs": "591",
    "contributions": "4,360", "followers": "9",
    "loc": "1,173,763", "loc_add": "1,978,907", "loc_del": "805,144",
}

# Rebuilding the card should preserve the most recently refreshed dynamic
# values instead of resetting them to the fallback snapshot above.
ID_TO_STAT = {
    "age_data": "age",
    "downloads_data": "downloads",
    "paid_data": "paid",
    "arr_data": "arr",
    "actions_data": "actions",
    "rating_data": "rating",
    "reviews_data": "reviews",
    "repo_data": "repos",
    "pr_data": "prs",
    "contribution_data": "contributions",
    "follower_data": "followers",
    "loc_data": "loc",
    "loc_add": "loc_add",
    "loc_del": "loc_del",
}
if args.stats_from.exists():
    for element in ET.parse(args.stats_from).getroot().iter():
        stat = ID_TO_STAT.get(element.attrib.get("id"))
        if stat and element.text:
            STATS[stat] = element.text


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


def kv(pairs, ids=None):
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
                     f'<tspan class="value"{vid}>{vmk}</tspan>')
        if i < len(pairs) - 1:
            parts.append(" | ")
    return "".join(parts)


def key(name):
    """Markup + display length for a dotted key like Stack.Languages."""
    segs = name.split(".")
    mk = ".".join(f'<tspan class="key">{esc(s)}</tspan>' for s in segs)
    return mk, len(name)


def line_kv(name, value, dots_id=None):
    kmk, klen = key(name)
    return kv([(kmk, klen, esc(value), len(value), dots_id)])


def line_kv2(n1, v1, id1, n2, v2, id2):
    k1, l1 = key(n1)
    k2, l2 = key(n2)
    return kv([(k1, l1, esc(v1), len(v1), id1), (k2, l2, esc(v2), len(v2), id2)])


LOC_LABEL = "Lines of Code"


def loc_line():
    k = f'<tspan class="key">{LOC_LABEL}</tspan>' 
    tail = (f'<tspan class="value" id="loc_data">{STATS["loc"]}</tspan> '
            f'(<tspan class="addColor" id="loc_add">{STATS["loc_add"]}</tspan>'
            f'<tspan class="addColor">++</tspan>, '
            f'<tspan class="delColor" id="loc_del">{STATS["loc_del"]}</tspan>'
            f'<tspan class="delColor">--</tspan>)')
    tail_len = (len(STATS["loc"]) + 2 + len(STATS["loc_add"]) + 4
                + len(STATS["loc_del"]) + 3)
    fixed = 2 + len(LOC_LABEL) + 1 + 2 + tail_len
    dots = WIDTH - fixed
    # Silently clamping here is what pushed the old card's widest line two
    # characters past the panel, so the totals were clipped off the right edge.
    assert dots >= 1, f"lines-of-code row needs {fixed + 1} columns, have {WIDTH}"
    return (f'<tspan x="{X_RIGHT}" y="{{y}}" class="cc">. </tspan>{k}:'
            f'<tspan class="cc" id="loc_data_dots"> {"." * dots} </tspan>{tail}')


rows = [
    header("kaya@myfutureself"),
    line_kv("Role", "Co-founder & CTO"),
    line_kv("Location", "Cleveland, OH"),
    line_kv("Uptime", STATS["age"], "age_data"),
    line_kv("Company", "MyFutureSelf, Inc."),
    line_kv("Focus", "consumer AI, behavior change, voice"),
    line_kv("Toolchain", "Claude Code, Codex, Ghostty, OpenClaw"),
    None,
    line_kv("Stack.Languages", "Swift, TypeScript"),
    line_kv("Stack.Frameworks", "SwiftUI, Next.js, Firebase"),
    None,
    header("─ MyFutureSelf"),
    line_kv2("Downloads", STATS["downloads"], "downloads_data",
             "Paid Subs", STATS["paid"], "paid_data"),
    line_kv2("Annual Run Rate", STATS["arr"], "arr_data",
             "Actions", STATS["actions"], "actions_data"),
    line_kv2("Rating", STATS["rating"], "rating_data",
             "Reviews", STATS["reviews"], "reviews_data"),
    None,
    header("─ Contact"),
    line_kv("Email.Work", "successai@myfutureselfapp.com"),
    line_kv("Website", "kayahickin.com"),
    line_kv("X", "@KayaHickin"),
    None,
    header("─ GitHub Stats"),
    line_kv2("Repos", STATS["repos"], "repo_data",
             "PRs Merged", STATS["prs"], "pr_data"),
    line_kv2("Contributions (1y)", STATS["contributions"], "contribution_data",
             "Followers", STATS["followers"], "follower_data"),
    loc_line(),
]
assert len(rows) == 25, len(rows)


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
    art_lines = read_art(pal["art_source"])
    out.append(f'<text x="{ART_X}" y="{ART_Y0}" fill="{pal["art"]}" '
               f'font-size="{ART_FS}px" class="ascii">')
    for i in range(ROWS):
        y = ART_Y0 + i * ART_LINE_H
        out.append(f'<tspan x="{ART_X}" y="{y}">{esc(art_lines[i])}</tspan>')
    out.append("</text>")
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

# sanity: the portrait, the language block and the readout must all stay inside
# the card, and every right-column line must end on the same column.
assert ART_X + ART_W <= X_RIGHT, (ART_X + ART_W, X_RIGHT)
assert X_RIGHT + WIDTH * (FS * 0.6) <= CARD_W, X_RIGHT + WIDTH * (FS * 0.6)
assert ART_Y0 + (ROWS - 1) * ART_LINE_H < BAR_Y, BAR_Y
assert max(LEGEND_ROWS) < CARD_H and Y0 + 24 * LINE_H < CARD_H
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
