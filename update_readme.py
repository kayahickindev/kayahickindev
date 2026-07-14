"""Refresh the live data baked into dark_mode.svg / light_mode.svg.

Runs daily via GitHub Actions. MyFutureSelf traction comes from the fresh
snapshot rendered by kayahickin.com; GitHub activity comes from the GitHub API.
The workflow requires an ACCESS_TOKEN with private-repo read access so that the
GitHub and lines-of-code totals cannot silently degrade to public-only data.

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
from datetime import date, datetime, timedelta, timezone

BIRTHDATE = date(2004, 1, 19)
LOGIN = "kayahickindev"
SVGS = ["dark_mode.svg", "light_mode.svg"]
API = "https://api.github.com"
SITE_URL = os.environ.get("PROFILE_SITE_URL", "https://www.kayahickin.com")
SITE_MAX_AGE_HOURS = int(os.environ.get("PROFILE_SITE_MAX_AGE_HOURS", "48"))

REQUIRED_SITE_METRICS = (
    "appDownloads",
    "appStoreRating",
    "appStoreReviews",
    "futureSelfActions",
    "paidSubscribersEver",
    "arr",
)

# Next.js serializes server-component props into these script fragments. The
# personal site intentionally owns the upstream metrics fetch; this repo reads
# the already-rendered snapshot instead of duplicating its backend contract.
NEXT_PAYLOAD_PATTERN = re.compile(
    r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)</script>',
    re.DOTALL,
)

# value ids on one line -> the dots tspan that absorbs their length changes
LINE_GROUPS = [
    (("age_data",), "age_data_dots"),
    (("downloads_data", "paid_data"), "paid_data_dots"),
    (("arr_data", "actions_data"), "actions_data_dots"),
    (("rating_data", "reviews_data"), "reviews_data_dots"),
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


def fetch_url(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "text/html,application/xhtml+xml")
    req.add_header("Cache-Control", "no-cache")
    req.add_header("User-Agent", "kayahickindev-profile-updater/1.0")
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"personal site returned HTTP {resp.status}")
        return resp.read().decode("utf-8")


def extract_site_snapshot(page_html):
    """Extract the MarketingMetricsSnapshot rendered into the Next.js page."""
    chunks = []
    for match in NEXT_PAYLOAD_PATTERN.finditer(page_html):
        try:
            chunks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    payload = "".join(chunks)
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        cursor = payload.find('"metrics":', cursor)
        if cursor < 0:
            break
        start = cursor + len('"metrics":')
        try:
            candidate, _ = decoder.raw_decode(payload[start:])
        except json.JSONDecodeError:
            cursor = start
            continue
        if (
            isinstance(candidate, dict)
            and isinstance(candidate.get("generatedAt"), str)
            and isinstance(candidate.get("metrics"), dict)
        ):
            return candidate
        cursor = start
    raise RuntimeError("fresh metrics snapshot not found in personal-site HTML")


def compact_thousands(value):
    return f"{round(value / 1000):,}K+"


def fetch_site_stats(url=SITE_URL, now=None):
    snapshot = extract_site_snapshot(fetch_url(url))
    generated_at = snapshot["generatedAt"]
    if generated_at == "fallback":
        raise RuntimeError("personal site rendered its fallback metrics")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"invalid personal-site generatedAt: {generated_at}") from exc
    now = now or datetime.now(timezone.utc)
    age = now - generated.astimezone(timezone.utc)
    if age < timedelta(minutes=-5) or age > timedelta(hours=SITE_MAX_AGE_HOURS):
        raise RuntimeError(
            f"personal-site metrics are not fresh: generatedAt={generated_at}, age={age}"
        )

    metrics = snapshot["metrics"]

    def raw(name):
        metric = metrics.get(name)
        value = metric.get("raw") if isinstance(metric, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise RuntimeError(f"invalid personal-site metric {name}: {metric!r}")
        return value

    for name in REQUIRED_SITE_METRICS:
        raw(name)

    values = {
        "downloads_data": compact_thousands(raw("appDownloads")),
        "paid_data": f'{round(raw("paidSubscribersEver")):,}+',
        "arr_data": f'${compact_thousands(raw("arr"))}',
        "actions_data": compact_thousands(raw("futureSelfActions")),
        "rating_data": f'{raw("appStoreRating"):.1f}',
        "reviews_data": f'{round(raw("appStoreReviews")):,}',
    }
    print(f"personal-site metrics: generatedAt={generated_at}")
    return values


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
    for name in names:
        _, languages = gh(f"/repos/{name}/languages", token)
        if not languages:
            print(f"skipping {name}: no GitHub-detected source languages")
            continue
        contributors = None
        for attempt in range(8):
            status, data = gh(f"/repos/{name}/stats/contributors", token)
            if status == 200 and isinstance(data, list):
                contributors = data
                break
            time.sleep(5 + attempt * 3)  # 202: stats cache still generating
        if contributors is None:
            # Never publish a partial LOC total. A failed workflow is visible;
            # a plausible-looking stale or understated number is not.
            raise RuntimeError(f"contributor stats unavailable for {name}")
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
        "loc_data": f"{adds - dels:,}",
        "loc_add": f"{adds:,}",
        "loc_del": f"{dels:,}",
    }
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
    values.update(fetch_site_stats())
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        stats = fetch_stats(token)
        if stats:
            values.update(stats)
    elif os.environ.get("REQUIRE_GITHUB_STATS") == "1":
        raise RuntimeError("ACCESS_TOKEN is required for complete GitHub and LOC stats")
    else:
        print("no ACCESS_TOKEN; keeping the last committed GitHub-only values")
    for path in SVGS:
        update_svg(path, values)
    print("updated:", ", ".join(f"{k}={v}" for k, v in sorted(values.items())))


if __name__ == "__main__":
    sys.exit(main())
