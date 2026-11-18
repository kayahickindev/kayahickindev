"""Refresh the live data baked into dark_mode.svg / light_mode.svg.

Runs every six hours and after kayahickin.com publishes its daily snapshot
through GitHub Actions. MyFutureSelf traction comes from the site's public
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
LANGUAGE_STATS_PATH = os.environ.get("LANGUAGE_STATS_PATH", "language_stats.json")
REFRESH_STATE_PATH = os.environ.get(
    "PROFILE_REFRESH_STATE_PATH", "profile_refresh_state.json"
)
METRICS_HISTORY_PATH = os.environ.get("METRICS_HISTORY_PATH", "metrics_history.json")
METRICS_HISTORY_DAYS = 400

REQUIRED_RAW_SITE_METRICS = (
    "appDownloads",
    "appStoreRating",
    "appStoreReviews",
    "futureSelfActions",
    "paidSubscribers",
)
REQUIRED_DISPLAY_SITE_METRICS = ("arr",)

# value ids on one line -> the dots tspan that absorbs their length changes
LINE_GROUPS = [
    (("age_data",), "age_data_dots"),
    (("downloads_data", "paid_data"), "paid_data_dots"),
    (("arr_data", "actions_data"), "actions_data_dots"),
    (("rating_data", "reviews_data"), "reviews_data_dots"),
    (("pr_data",), "pr_data_dots"),
    (("contribution_data",), "contribution_data_dots"),
    (("loc_add",), "loc_add_dots"),
    (("loc_del",), "loc_del_dots"),
]


def uptime_string(today=None):
    """Age as `22 years, 9 months, 30 days`, for the card's Uptime row."""
    today = today or datetime.now(timezone.utc).date()
    years = today.year - BIRTHDATE.year
    months = today.month - BIRTHDATE.month
    days = today.day - BIRTHDATE.day
    if days < 0:
        months -= 1
        days += (today.replace(day=1) - timedelta(days=1)).day
    if months < 0:
        years -= 1
        months += 12

    def plural(count, unit):
        return f"{count} {unit}" + ("" if count == 1 else "s")

    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"


def record_metric_history(path, generated_at, downloads):
    """Keep one downloads point per day, for the card's trend line.

    The product endpoint only serves the latest snapshot, so the history the
    sparkline draws has to be kept here. A day's point is replaced, not
    duplicated, and a missing or damaged file starts a new series.
    """
    if not path:
        return
    day = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).astimezone(
        timezone.utc
    ).date().isoformat()
    points = {}
    try:
        with open(path) as history_file:
            payload = json.load(history_file)
        for point in payload.get("downloads", []):
            if isinstance(point.get("date"), str) and isinstance(point.get("value"), int):
                points[point["date"]] = point["value"]
    except (OSError, json.JSONDecodeError, AttributeError):
        print(f"starting a new metrics history at {path}")
    points[day] = int(downloads)
    kept = sorted(points.items())[-METRICS_HISTORY_DAYS:]
    write_json(path, {
        "version": 1,
        "downloads": [{"date": date_, "value": value} for date_, value in kept],
    })


def gh(path, token, method="GET", body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code not in (500, 502, 503, 504):
            raise
        status = exc.code
        data = exc.read()
    if status >= 500 and path != "/graphql":
        # REST callers expect complete results. In particular, a failed
        # languages request must never look like an empty code repository.
        raise RuntimeError(f"GitHub {path} unavailable: HTTP {status}")
    try:
        payload = json.loads(data) if data else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        if status not in (500, 502, 503, 504):
            raise
        # Gateways can return HTML or plain text. Preserve the HTTP status so
        # graphql() can retry instead of aborting before its retry loop runs.
        payload = None
    return status, payload


def gh_read(path, token, attempts=4):
    """GET with bounded retries, for the paginated reads behind incremental LOC.

    One gateway error among a few hundred compare pages should not cost the
    whole refresh. Persistent failure still raises, so nothing partial ships.
    """
    for attempt in range(attempts):
        try:
            return gh(path, token)
        except RuntimeError as exc:
            if "unavailable: HTTP 5" not in str(exc) or attempt == attempts - 1:
                raise
            print(f"{exc}; retry {attempt + 2}/{attempts}")
            time.sleep(3 + attempt * 3)


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

    def display(name):
        metric = metrics.get(name)
        value = metric.get("display") if isinstance(metric, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"invalid profile metric {name}: {metric!r}")
        return value

    for name in REQUIRED_RAW_SITE_METRICS:
        raw(name)
    for name in REQUIRED_DISPLAY_SITE_METRICS:
        display(name)

    values = {
        "downloads_data": f'{raw("appDownloads"):,.0f}',
        "paid_data": f'{raw("paidSubscribers"):,.0f}',
        "arr_data": display("arr"),
        "actions_data": f'{raw("futureSelfActions"):,.0f}',
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


def save_language_stats(path, totals):
    """Persist GitHub-detected language bytes for the card's language bar.

    The same repository walk that totals lines of code already asks each
    repository for its languages, so the bar covers exactly the repositories
    behind the LOC figure instead of a public-only subset.
    """
    if not path:
        return
    write_json(path, {
        "version": 1,
        "languages": [
            {"name": name, "bytes": count}
            for name, count in sorted(totals.items(), key=lambda item: -item[1])
        ],
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
    page_size = 25
    while True:
        try:
            data = graphql("""
              query($owner: String!, $name: String!, $author: ID!, $cursor: String, $pageSize: Int!) {
                repository(owner: $owner, name: $name) {
                  defaultBranchRef {
                    target {
                      ... on Commit {
                        history(first: $pageSize, after: $cursor, author: {id: $author}) {
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
                "pageSize": page_size,
            }, token, f"commit history for {name}")
        except RuntimeError as exc:
            if page_size > 1 and "unavailable: HTTP 50" in str(exc):
                page_size = max(1, page_size // 5)
                print(f"Reducing {name} commit-history page to {page_size} commits")
                continue
            raise
        page_size = 25
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


# GitHub's compare endpoint lists at most this many commits for one range.
COMPARE_LIMIT = 10000
COMPARE_PAGE = 100
# A long backlog is walked this many commits at a time, saving after each step,
# so a run that is cut off resumes from the last step instead of starting over.
CHUNK_COMMITS = 2000
STATS_BATCH = 40


def compare_page(name, base, head, token, page, per_page=COMPARE_PAGE):
    _, payload = gh_read(
        f"/repos/{name}/compare/{base}...{head}?per_page={per_page}&page={page}",
        token,
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("commits"), list):
        raise RuntimeError(f"invalid compare response for {name} {base[:12]}...{head[:12]}")
    return payload


def range_size(name, base, head, token):
    """Commits reachable from `head` but not `base`, or None when not exact.

    None covers a base that is gone (404) and a base that is not an ancestor
    of `head`, which is what rewritten history looks like.
    """
    try:
        probe = compare_page(name, base, head, token, 1, per_page=1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    ahead = probe.get("ahead_by")
    if not isinstance(ahead, int) or ahead < 1 or probe.get("behind_by") != 0:
        return None
    return ahead


def commit_at_offset(name, head, token, offset):
    """The commit `offset` entries behind `head` in GitHub's listing, or None."""
    _, commits = gh_read(
        f"/repos/{name}/commits?sha={head}&per_page=1&page={offset + 1}", token
    )
    if isinstance(commits, list) and commits:
        return commits[0].get("sha")
    return None


def next_step(name, base, head, token):
    """Where to advance to from `base`: (commit, range size), or None.

    Usually that is `head`. A backlog longer than one chunk stops at a commit M
    partway there. M is taken from `head`'s own history and must have `base` as
    an ancestor, so base..M and M..head are disjoint and together are exactly
    base..head.
    """
    ahead = range_size(name, base, head, token)
    if ahead is None:
        return None
    if ahead <= CHUNK_COMMITS:
        return head, ahead
    for nudge in range(5):
        middle = commit_at_offset(name, head, token, ahead - CHUNK_COMMITS + nudge)
        if not middle or middle in (base, head):
            continue
        size = range_size(name, base, middle, token)
        if size is not None and size <= COMPARE_LIMIT:
            return middle, size
    return (head, ahead) if ahead <= COMPARE_LIMIT else None


def fetch_range_commits(name, base, head, token, ahead):
    """All `ahead` commits of base..head, or None if the listing is not exact."""
    commits = []
    page = 0
    while len(commits) < ahead:
        page += 1
        batch = compare_page(name, base, head, token, page)["commits"]
        if not batch:
            break
        commits.extend(batch)
    if len(commits) != ahead or len({commit["sha"] for commit in commits}) != ahead:
        return None
    return commits


def fetch_commit_stats(name, oids, token):
    """Sum additions and deletions of specific commits, in shrinkable batches."""
    owner, repo_name = name.split("/", 1)
    adds = dels = 0
    index = 0
    size = STATS_BATCH
    while index < len(oids):
        batch = oids[index:index + size]
        fields = " ".join(
            f'c{i}: object(oid: "{oid}") {{ ... on Commit {{ additions deletions }} }}'
            for i, oid in enumerate(batch)
        )
        try:
            data = graphql(
                "query($owner: String!, $name: String!) {"
                f" repository(owner: $owner, name: $name) {{ {fields} }} }}",
                {"owner": owner, "name": repo_name}, token,
                f"commit stats for {name}",
            )
        except RuntimeError as exc:
            if size > 1 and "unavailable: HTTP 50" in str(exc):
                size = max(1, size // 4)
                print(f"Reducing {name} commit-stats batch to {size} commits")
                continue
            raise
        repository = data.get("repository") or {}
        for i, oid in enumerate(batch):
            commit = repository.get(f"c{i}")
            if not isinstance(commit, dict) or "additions" not in commit:
                raise RuntimeError(f"missing commit stats for {name}@{oid[:12]}")
            adds += commit["additions"]
            dels += commit["deletions"]
        index += len(batch)
        size = STATS_BATCH
    return adds, dels


def fetch_incremental_loc(name, author_id, token, base_oid, head_oid, ahead):
    """Lines this user added and removed across one listed range, or None.

    Counts the same commits the full walk does: authored by the user, not a
    merge. None means the range could not be listed exactly.
    """
    commits = fetch_range_commits(name, base_oid, head_oid, token, ahead)
    if commits is None:
        return None
    mine = [
        commit["sha"] for commit in commits
        if (commit.get("author") or {}).get("node_id") == author_id
        and len(commit.get("parents") or []) <= 1
    ]
    adds, dels = fetch_commit_stats(name, mine, token)
    return adds, dels, len(mine)


def advance_repo_loc(name, author_id, token, cached, head_oid, checkpoint=None):
    """Bring cached totals up to `head_oid` by counting only the new commits.

    Returns (additions, deletions), or None when the cached head cannot be
    advanced exactly and the repository needs a full recount. `checkpoint`
    receives the cache entry after each intermediate step.
    """
    adds, dels, base = cached["additions"], cached["deletions"], cached["headOid"]
    listed = counted = 0
    while base != head_oid:
        step = next_step(name, base, head_oid, token)
        if step is None:
            return None
        target, ahead = step
        delta = fetch_incremental_loc(name, author_id, token, base, target, ahead)
        if delta is None:
            return None
        adds += delta[0]
        dels += delta[1]
        listed += ahead
        counted += delta[2]
        base = target
        if base != head_oid:
            if checkpoint:
                checkpoint({"headOid": base, "additions": adds, "deletions": dels})
            print(f"LOC cache checkpoint: {name}@{base[:12]} ({listed:,} commits in)")
    print(f"LOC cache advanced: {name}@{head_oid[:12]} "
          f"({counted:,} of {listed:,} new commits counted)")
    return adds, dels


def fetch_cached_repo_loc(name, author_id, token, loc_cache, checkpoint=None):
    head_oid = fetch_repo_head(name, token)
    if not head_oid:
        return None
    cached = loc_cache.get(name)
    usable = (
        isinstance(cached, dict)
        and isinstance(cached.get("headOid"), str)
        and isinstance(cached.get("additions"), int)
        and isinstance(cached.get("deletions"), int)
    )
    if usable and cached["headOid"] == head_oid:
        repo_adds = cached["additions"]
        repo_dels = cached["deletions"]
        print(f"LOC cache hit: {name}@{head_oid[:12]}")
    else:
        # Recounting a whole history on every new commit is what made the
        # refresh outgrow its time limit. Count only what landed since the
        # cached head; recount from scratch when that range is not exact.
        advanced = None
        if usable:
            advanced = advance_repo_loc(
                name, author_id, token, cached, head_oid, checkpoint
            )
        if advanced is not None:
            repo_adds, repo_dels = advanced
        else:
            repo_adds, repo_dels = fetch_repo_loc(name, author_id, token)
            print(f"LOC cache refreshed: {name}@{head_oid[:12]}")
    return repo_adds, repo_dels, {
        "headOid": head_oid,
        "additions": repo_adds,
        "deletions": repo_dels,
    }


def fetch_stats(token, loc_cache_path=None, language_stats_path=None):
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
      }""", {"login": LOGIN}, token, "profile summary")
    collection = data["user"]["contributionsCollection"]
    author_id = data["user"]["id"]
    contribution_total = collection["contributionCalendar"]["totalContributions"]
    print(
        "GitHub contribution calendar: "
        f"{collection['startedAt']} to {collection['endedAt']} = "
        f"{contribution_total:,}"
    )
    loc_cache = load_loc_cache(loc_cache_path)
    # This lookup is slow on GitHub's side and times out often, which used to
    # fail the whole refresh. It runs on its own, and when it stays unavailable
    # the repositories already counted stand in for it.
    try:
        contributed_data = graphql("""
          query {
            viewer {
              repositoriesContributedTo(first: 100, contributionTypes: [COMMIT]) {
                nodes { nameWithOwner }
              }
            }
          }""", {}, token, "contributed repositories")
        contributed_names = [
            node["nameWithOwner"]
            for node in contributed_data["viewer"]["repositoriesContributedTo"]["nodes"]
        ]
    except RuntimeError as exc:
        if "unavailable: HTTP 5" not in str(exc) or not loc_cache:
            raise
        contributed_names = list(loc_cache)
        print(f"{exc}; using the {len(contributed_names)} repositories already counted")

    names = list(dict.fromkeys(
        [r["full_name"] for r in owned] + contributed_names
    ))
    refreshed_cache = {}
    language_totals = {}
    adds = dels = 0
    for name in names:
        _, languages = gh(f"/repos/{name}/languages", token)
        if not languages:
            print(f"skipping {name}: no GitHub-detected source languages")
            continue
        for language, byte_count in languages.items():
            language_totals[language] = language_totals.get(language, 0) + byte_count
        def checkpoint(entry, name=name):
            save_loc_cache(loc_cache_path, {**loc_cache, **refreshed_cache, name: entry})

        repo_loc = fetch_cached_repo_loc(name, author_id, token, loc_cache, checkpoint)
        if not repo_loc:
            print(f"skipping {name}: no default-branch commit")
            continue
        repo_adds, repo_dels, cache_entry = repo_loc
        refreshed_cache[name] = cache_entry
        # Checkpoint only complete repository totals. A later failure still
        # aborts card publication, but the next attempt can reuse this work.
        save_loc_cache(loc_cache_path, {**loc_cache, **refreshed_cache})
        adds += repo_adds
        dels += repo_dels

    save_loc_cache(loc_cache_path, refreshed_cache)
    save_language_stats(language_stats_path, language_totals)

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
    record_metric_history(
        METRICS_HISTORY_PATH, metrics_generated_at,
        site_values["downloads_data"].replace(",", ""),
    )
    token = os.environ.get("ACCESS_TOKEN")
    if token:
        stats = fetch_stats(token, LOC_CACHE_PATH, LANGUAGE_STATS_PATH)
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
