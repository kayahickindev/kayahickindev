"""Refresh the live data baked into dark_mode.svg / light_mode.svg.

Runs after kayahickin.com publishes its daily snapshot, with a late-day
fallback in GitHub Actions. MyFutureSelf traction comes from the site's public
JSON snapshot; GitHub activity comes from the GitHub API.
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
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

BIRTHDATE = date(2004, 1, 19)
LOGIN = "kayahickindev"
SVGS = ["dark_mode.svg", "light_mode.svg"]
API = "https://api.github.com"
METRICS_URL = os.environ.get(
    "PROFILE_METRICS_URL", "https://kayahickin.com/api/profile-metrics"
)
SITE_MAX_AGE_HOURS = int(os.environ.get("PROFILE_SITE_MAX_AGE_HOURS", "48"))
LOC_CACHE_PATH = os.environ.get("LOC_CACHE_PATH", "loc_cache.json")
REFRESH_STATE_PATH = os.environ.get(
    "PROFILE_REFRESH_STATE_PATH", "profile_refresh_state.json"
)

REQUIRED_SITE_METRICS = (
    "appDownloads",
    "appStoreRating",
    "appStoreReviews",
    "futureSelfActions",
    "paidSubscribersEver",
    "arr",
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
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (500, 502, 503, 504):
            raise
        status = exc.code
        data = exc.read()
    return status, (json.loads(data) if data else None)


def graphql(query, variables, token, label):
    for attempt in range(4):
        status, payload = gh(
            "/graphql",
            token,
            method="POST",
            body={"query": query, "variables": variables},
        )
        if status == 200 and isinstance(payload, dict):
            if payload.get("errors"):
                raise RuntimeError(f"GitHub GraphQL error for {label}: {payload['errors']}")
            data = payload.get("data")
            if isinstance(data, dict):
                return data
        if attempt < 3:
            print(
                f"GitHub GraphQL {label} returned HTTP {status}; "
                f"retry {attempt + 2}/4"
            )
            time.sleep(3 + attempt * 3)
    raise RuntimeError(f"GitHub GraphQL {label} unavailable: HTTP {status}")


def fetch_json_url(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("Cache-Control", "no-cache")
    req.add_header("User-Agent", "kayahickindev-profile-updater/1.0")
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status != 200:
            raise RuntimeError(f"profile metrics endpoint returned HTTP {resp.status}")
        try:
            return json.loads(resp.read())
        except json.JSONDecodeError as exc:
            raise RuntimeError("profile metrics endpoint returned invalid JSON") from exc


def compact_thousands(value):
    return f"{round(value / 1000):,}K+"


def fetch_site_stats(url=METRICS_URL, now=None):
    snapshot = fetch_json_url(url)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("metrics"), dict):
        raise RuntimeError("profile metrics endpoint returned an invalid snapshot")
    generated_at = snapshot.get("generatedAt")
    if not isinstance(generated_at, str):
        raise RuntimeError("profile metrics endpoint omitted generatedAt")
    if generated_at == "fallback":
        raise RuntimeError("profile metrics endpoint returned fallback metrics")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"invalid profile metrics generatedAt: {generated_at}") from exc
    now = now or datetime.now(timezone.utc)
    age = now - generated.astimezone(timezone.utc)
    if age < timedelta(minutes=-5) or age > timedelta(hours=SITE_MAX_AGE_HOURS):
        raise RuntimeError(
            f"profile metrics are not fresh: generatedAt={generated_at}, age={age}"
        )

    metrics = snapshot["metrics"]

    def raw(name):
        metric = metrics.get(name)
        value = metric.get("raw") if isinstance(metric, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise RuntimeError(f"invalid profile metric {name}: {metric!r}")
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
    print(f"profile metrics: generatedAt={generated_at}")
    return values, generated_at


def load_loc_cache(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as cache_file:
            payload = json.load(cache_file)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ignoring unreadable LOC cache {path}: {exc}")
        return {}
    if payload.get("version") != 1 or not isinstance(payload.get("repositories"), dict):
        print(f"ignoring unsupported LOC cache {path}")
        return {}
    return payload["repositories"]


def write_json(path, payload):
    temporary = f"{path}.tmp"
    with open(temporary, "w") as output:
        json.dump(payload, output, indent=2, sort_keys=True)
        output.write("\n")
    os.replace(temporary, path)


def save_loc_cache(path, repositories):
    if not path:
        return
    write_json(path, {
        "version": 1,
        "repositories": repositories,
    })


def fetch_repo_head(name, token):
    owner, repo_name = name.split("/", 1)
    data = graphql("""
      query($owner: String!, $name: String!) {
        repository(owner: $owner, name: $name) {
          defaultBranchRef {
            target { ... on Commit { oid } }
          }
        }
      }""", {"owner": owner, "name": repo_name}, token, f"default branch for {name}")
    repository = data.get("repository")
    default_ref = repository.get("defaultBranchRef") if repository else None
    if not default_ref:
        return None
    oid = default_ref.get("target", {}).get("oid")
    return oid if isinstance(oid, str) and oid else None


def fetch_repo_loc(name, author_id, token):
    """Sum non-merge commits by this user on a repo's default branch."""
    owner, repo_name = name.split("/", 1)
    adds = dels = 0
    cursor = None
    while True:
        data = graphql("""
          query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
            repository(owner: $owner, name: $name) {
              defaultBranchRef {
                target {
                  ... on Commit {
                    history(first: 100, after: $cursor, author: {id: $author}) {
                      nodes {
                        additions
                        deletions
                        parents(first: 2) { totalCount }
                      }
                      pageInfo { hasNextPage endCursor }
                    }
                  }
                }
              }
            }
          }""", {
            "owner": owner,
            "name": repo_name,
            "author": author_id,
            "cursor": cursor,
        }, token, f"commit history for {name}")
        repository = data.get("repository")
        default_ref = repository.get("defaultBranchRef") if repository else None
        if not default_ref:
            return adds, dels
        history = default_ref.get("target", {}).get("history")
        if not isinstance(history, dict):
            raise RuntimeError(f"default branch is not a commit history for {name}")
        for commit in history["nodes"]:
            if commit["parents"]["totalCount"] > 1:
                # The branch commits are already reachable from the default
                # branch; counting the merge diff would duplicate their LOC.
                continue
            adds += commit["additions"]
            dels += commit["deletions"]
        page_info = history["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]
    return adds, dels


def fetch_cached_repo_loc(name, author_id, token, loc_cache):
    head_oid = fetch_repo_head(name, token)
    if not head_oid:
        return None
    cached = loc_cache.get(name)
    if (
        isinstance(cached, dict)
        and cached.get("headOid") == head_oid
        and isinstance(cached.get("additions"), int)
        and isinstance(cached.get("deletions"), int)
    ):
        repo_adds = cached["additions"]
        repo_dels = cached["deletions"]
        print(f"LOC cache hit: {name}@{head_oid[:12]}")
    else:
        repo_adds, repo_dels = fetch_repo_loc(name, author_id, token)
        print(f"LOC cache refreshed: {name}@{head_oid[:12]}")
    return repo_adds, repo_dels, {
        "headOid": head_oid,
        "additions": repo_adds,
        "deletions": repo_dels,
    }


def fetch_stats(token, loc_cache_path=None):
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

    data = graphql("""
      query($login: String!) {
        user(login: $login) {
          id
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
      }""", {"login": LOGIN}, token, "profile summary")
    collection = data["user"]["contributionsCollection"]
    author_id = data["user"]["id"]
    contribution_total = collection["contributionCalendar"]["totalContributions"]
    print(
        "GitHub contribution calendar: "
        f"{collection['startedAt']} to {collection['endedAt']} = "
        f"{contribution_total:,}"
    )
    contributed = data["viewer"]["repositoriesContributedTo"]

    names = list(dict.fromkeys(
        [r["full_name"] for r in owned]
        + [n["nameWithOwner"] for n in contributed["nodes"]]
    ))
    loc_cache = load_loc_cache(loc_cache_path)
    refreshed_cache = {}
    adds = dels = 0
    for name in names:
        _, languages = gh(f"/repos/{name}/languages", token)
        if not languages:
            print(f"skipping {name}: no GitHub-detected source languages")
            continue
        repo_loc = fetch_cached_repo_loc(name, author_id, token, loc_cache)
        if not repo_loc:
            print(f"skipping {name}: no default-branch commit")
            continue
        repo_adds, repo_dels, cache_entry = repo_loc
        refreshed_cache[name] = cache_entry
        adds += repo_adds
        dels += repo_dels

    save_loc_cache(loc_cache_path, refreshed_cache)

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


def refreshed_today(path=REFRESH_STATE_PATH, today=None):
    today = today or datetime.now(timezone.utc).date()
    try:
        with open(path) as state_file:
            state = json.load(state_file)
    except (OSError, json.JSONDecodeError):
        return False
    return state.get("refreshedOn") == today.isoformat()


def save_refresh_state(metrics_generated_at, path=REFRESH_STATE_PATH):
    now = datetime.now(timezone.utc)
    write_json(path, {
        "metricsGeneratedAt": metrics_generated_at,
        "refreshedAt": now.isoformat().replace("+00:00", "Z"),
        "refreshedOn": now.date().isoformat(),
        "trigger": os.environ.get("REFRESH_TRIGGER", "local"),
    })


def main():
    if (
        os.environ.get("SKIP_IF_REFRESHED_TODAY", "").lower() == "true"
        and refreshed_today()
    ):
        print("combined website/profile refresh already completed today; skipping fallback")
        return 0

    values = {"age_data": uptime_string()}
    site_values, metrics_generated_at = fetch_site_stats()
    values.update(site_values)
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        stats = fetch_stats(token, LOC_CACHE_PATH)
        if stats:
            values.update(stats)
    elif os.environ.get("REQUIRE_GITHUB_STATS") == "1":
        raise RuntimeError("ACCESS_TOKEN is required for complete GitHub and LOC stats")
    else:
        print("no ACCESS_TOKEN; keeping the last committed GitHub-only values")
    for path in SVGS:
        update_svg(path, values)
    if os.environ.get("WRITE_REFRESH_STATE") == "1":
        save_refresh_state(metrics_generated_at)
    print("updated:", ", ".join(f"{k}={v}" for k, v in sorted(values.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
