"""Refresh the stats baked into dark_mode.svg / light_mode.svg.

Runs daily via GitHub Actions. Always updates the Uptime line. If an
ACCESS_TOKEN env var is present (a PAT with repo read access), also refreshes
repo/PR/follower/LOC numbers and the rolling contribution total shown by the
GitHub profile calendar. Without a token the stats are left at their last
committed values rather than being clobbered with public-only counts.

Layout invariant: every value tspan has a sibling dots tspan; when a value's
length changes, the dots shrink/grow by the same amount so the right edge of
each line stays aligned.
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date

BIRTHDATE = date(2004, 1, 19)
LOGIN = "kayahickindev"
SVGS = ["dark_mode.svg", "light_mode.svg"]
API = "https://api.github.com"

# value ids on one line -> the dots tspan that absorbs their length changes
LINE_GROUPS = [
    (("age_data",), "age_data_dots"),
    (("repo_data", "pr_data"), "pr_data_dots"),
    (("contribution_data", "follower_data"), "follower_data_dots"),
    (("loc_data", "loc_add", "loc_del"), "loc_data_dots"),
]


def uptime_string(today=None):
    today = today or date.today()
    y = today.year - BIRTHDATE.year
    m = today.month - BIRTHDATE.month
    d = today.day - BIRTHDATE.day
    if d < 0:
        m -= 1
        prev_month = (today.month - 1) or 12
        prev_year = today.year if today.month > 1 else today.year - 1
        days_in_prev = (date(prev_year + (prev_month == 12), prev_month % 12 + 1, 1)
                        - date(prev_year, prev_month, 1)).days
        d += days_in_prev
    if m < 0:
        y -= 1
        m += 12
    def plural(n, unit):
        return f"{n} {unit}" + ("" if n == 1 else "s")
    return f"{plural(y, 'year')}, {plural(m, 'month')}, {plural(d, 'day')}"


def gh(path, token, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        status = resp.status
        data = resp.read()
    return status, (json.loads(data) if data else None)


def fetch_stats(token):
    _, user = gh("/user", token)
    followers = user["followers"]

    owned = []
    page = 1
    while True:
        _, repos = gh(f"/user/repos?affiliation=owner&per_page=100&page={page}", token)
        owned.extend(repos)
        if len(repos) < 100:
            break
        page += 1

    _, pr_search = gh(f"/search/issues?q=type:pr+author:{LOGIN}+is:merged&per_page=1", token)
    prs_merged = pr_search["total_count"]

    _, gql = gh("/graphql", token, method="POST", body={"query": """
      query($login: String!) {
        user(login: $login) {
          contributionsCollection {
            startedAt
            endedAt
            contributionCalendar { totalContributions }
          }
        }
        viewer {
          repositoriesContributedTo(first: 100, contributionTypes: [COMMIT]) {
            nodes { nameWithOwner }
          }
        }
      }""", "variables": {"login": LOGIN}})
    if gql.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {gql['errors']}")
    collection = gql["data"]["user"]["contributionsCollection"]
    contribution_total = collection["contributionCalendar"]["totalContributions"]
    print(
        "GitHub contribution calendar: "
        f"{collection['startedAt']} to {collection['endedAt']} = "
        f"{contribution_total:,}"
    )
    contributed = gql["data"]["viewer"]["repositoriesContributedTo"]

    names = list(dict.fromkeys(
        [r["full_name"] for r in owned]
        + [n["nameWithOwner"] for n in contributed["nodes"]]
    ))
    adds = dels = 0
    loc_available = True
    for name in names:
        contributors = None
        for attempt in range(8):
            status, data = gh(f"/repos/{name}/stats/contributors", token)
            if status == 200 and isinstance(data, list):
                contributors = data
                break
            time.sleep(5 + attempt * 3)  # 202: stats cache still generating
        if contributors is None:
            # Partial data would understate LOC. Keep the last committed LOC,
            # but still publish the independently verified calendar total.
            print(f"stats for {name} unavailable; keeping previous LOC values")
            loc_available = False
            break
        for c in contributors:
            if (c.get("author") or {}).get("login") == LOGIN:
                for w in c["weeks"]:
                    adds += w["a"]
                    dels += w["d"]

    values = {
        "repo_data": f"{len(owned)}",
        "pr_data": f"{prs_merged:,}",
        "follower_data": f"{followers}",
        "contribution_data": f"{contribution_total:,}",
    }
    if loc_available:
        values.update({
            "loc_data": f"{adds - dels:,}",
            "loc_add": f"{adds:,}",
            "loc_del": f"{dels:,}",
        })
    return values


def tspan_pattern(tid):
    return re.compile(rf'(<tspan[^>]*id="{tid}"[^>]*>)([^<]*)(</tspan>)')


def update_svg(path, values):
    with open(path) as f:
        svg = f.read()
    for value_ids, dots_id in LINE_GROUPS:
        delta = 0
        for vid in value_ids:
            if vid not in values:
                continue
            pat = tspan_pattern(vid)
            m = pat.search(svg)
            if not m:
                print(f"warning: id {vid} not found in {path}")
                continue
            delta += len(m.group(2)) - len(values[vid])
            svg = pat.sub(lambda mm: mm.group(1) + values[vid] + mm.group(3), svg, count=1)
        if delta:
            pat = tspan_pattern(dots_id)
            m = pat.search(svg)
            if m:
                dots = max(1, m.group(2).count(".") + delta)
                svg = pat.sub(lambda mm: mm.group(1) + f" {'.' * dots} " + mm.group(3),
                              svg, count=1)
    with open(path, "w") as f:
        f.write(svg)


def main():
    values = {"age_data": uptime_string()}
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        stats = fetch_stats(token)
        if stats:
            values.update(stats)
    else:
        print("no ACCESS_TOKEN; updating uptime only")
    for path in SVGS:
        update_svg(path, values)
    print("updated:", ", ".join(f"{k}={v}" for k, v in sorted(values.items())))


if __name__ == "__main__":
    sys.exit(main())
