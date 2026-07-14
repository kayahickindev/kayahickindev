"""Build dark_mode.svg and light_mode.svg for the kayahickindev profile README."""
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

COLS, ROWS = 37, 25
WIDTH = 63  # right-column line width in chars
X_RIGHT = 375
FS = 16
LINE_H = 20
Y0 = 30

# ---- ASCII portrait ----
parser = argparse.ArgumentParser()
parser.add_argument("--art", type=Path, default=HERE / "ascii_art_C.txt")
parser.add_argument("--output-dir", type=Path, default=ROOT)
parser.add_argument("--stats-from", type=Path, default=ROOT / "dark_mode.svg")
args = parser.parse_args()

art_lines = args.art.read_text(encoding="utf-8").splitlines()
while len(art_lines) < ROWS:
    art_lines.append("")

def blank(row, start, end=None):
    line = art_lines[row]
    end = len(line) if end is None else min(end, len(line))
    if start >= len(line):
        return
    art_lines[row] = (line[:start] + " " * (end - start) + line[end:]).rstrip()

# (curation now lives in make_variants.py; art file arrives pre-cleaned)

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---- palettes ----
DARK = dict(bg="#161b22", fg="#c9d1d9", key="#ffa657", value="#a5d6ff",
            add="#3fb950", dele="#f85149", cc="#616e7f")
LIGHT = dict(bg="#fffefe", fg="#24292f", key="#953800", value="#0a3069",
             add="#1a7f37", dele="#cf222e", cc="#6e7781")

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
    """Markup + display length for a dotted key like Languages.Programming."""
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

def dot_line():
    return f'<tspan x="{X_RIGHT}" y="{{y}}" class="cc">. </tspan>'

def loc_line():
    k = ('<tspan class="key">Lines of Code on GitHub</tspan>')
    tail = (f'<tspan class="value" id="loc_data">{STATS["loc"]}</tspan> '
            f'(<tspan class="addColor" id="loc_add">{STATS["loc_add"]}</tspan>'
            f'<tspan class="addColor">++</tspan>, '
            f'<tspan class="delColor" id="loc_del">{STATS["loc_del"]}</tspan>'
            f'<tspan class="delColor">--</tspan>)')
    tail_len = (len(STATS["loc"]) + 2 + len(STATS["loc_add"]) + 4
                + len(STATS["loc_del"]) + 3)
    fixed = 2 + 23 + 1 + 2 + tail_len
    dots = max(1, WIDTH - fixed)
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
    header("- MyFutureSelf"),
    line_kv2("Downloads", STATS["downloads"], "downloads_data",
             "Paid Subs", STATS["paid"], "paid_data"),
    line_kv2("ARR", STATS["arr"], "arr_data",
             "Actions", STATS["actions"], "actions_data"),
    line_kv2("Rating", STATS["rating"], "rating_data",
             "Reviews", STATS["reviews"], "reviews_data"),
    None,
    header("- Contact"),
    line_kv("Email.Work", "kaya@successai.app"),
    line_kv("Website", "kayahickin.com"),
    line_kv("X", "@KayaHickin"),
    None,
    header("- GitHub Stats"),
    line_kv2("Repos", STATS["repos"], "repo_data",
             "PRs Merged", STATS["prs"], "pr_data"),
    line_kv2("Contributions (1y)", STATS["contributions"], "contribution_data",
             "Followers", STATS["followers"], "follower_data"),
    loc_line(),
]
assert len(rows) == ROWS, len(rows)

def build(pal):
    out = []
    out.append("<?xml version='1.0' encoding='UTF-8'?>")
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="985px" height="530px" font-size="{FS}px">')
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
    out.append(f'<rect width="985px" height="530px" fill="{pal["bg"]}" rx="15"/>')
    out.append(f'<text x="15" y="{Y0}" fill="{pal["fg"]}" class="ascii">')
    for i in range(ROWS):
        y = Y0 + i * LINE_H
        out.append(f'<tspan x="15" y="{y}">{esc(art_lines[i])}</tspan>')
    out.append("</text>")
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

# sanity: report rendered char width of each right-column line
plain = re.compile(r"<[^>]+>")
for i, row in enumerate(rows):
    if row is None:
        continue
    txt = plain.sub("", row.replace("{y}", "0"))
    txt = txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if txt != ". ":
        assert len(txt) == WIDTH, (i, len(txt), txt)
    print(f"{i:2d} len={len(txt):3d} |{txt}")
