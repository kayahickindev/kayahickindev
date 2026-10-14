# Profile card

`update_readme.py` fetches the product snapshot and authenticated GitHub stats.
`build_svg.py` renders the light and dark terminal cards. Both use only Python's
standard library; neither calls an AI service.

```bash
python3 update_readme.py
python3 tools/build_svg.py
python3 -m unittest discover -s tests
```

The refresh needs `ACCESS_TOKEN` with private-repository read access.
Set `REQUIRE_GITHUB_STATS=1` and `WRITE_REFRESH_STATE=1` for a complete refresh.
The scheduled workflow uses the existing Actions secret and updates daily after
the personal site's metrics publish, with a late fallback schedule.

## Data and freshness

Product metrics come from `https://kayahickin.com/api/profile-metrics`; fallback
snapshots and snapshots older than 48 hours are rejected. Downloads, paid
subscriptions and actions use exact raw counts. Paid subscriptions uses
`paidSubscribers`, not the legacy `paidSubscribersEver` display value. ARR keeps
the source's public display precision. The card shows separate product-source
and GitHub-fetch timestamps.

GitHub activity includes private repositories. Lines added and removed sum the
user's non-merge commits on code repositories' default branches. They describe
historical changes, not the current codebase size. Repository-head caches avoid
recounting unchanged histories. History requests start at 25 commits per page and
shrink to 5 or 1 after persistent timeouts. Each completed repository is
checkpointed before moving on. A later failure still prevents publishing partial card totals.
`language_stats.json` uses GitHub-detected bytes from the same repository set.

GitHub gateway failures may contain HTML or plain text instead of JSON. Preserve
the 5xx status so bounded retries run; persistent failure must stop publication,
never publish a partial total. Regression tests cover recovery and exhaustion.

## Layout

The 700 by 535 card uses 63 monospace columns and a full-width language bar.
Every dynamic value has a sibling `*_dots` span that absorbs length changes.
Change the builder and `LINE_GROUPS` together when adding or removing metrics.
The builder requires recorded values rather than silently inserting old numbers.
Name, role, portrait, company, location, contact links and follower count belong
in GitHub's sidebar and are intentionally absent from the card. The original
ASCII portrait source and generator remain available under `tools/`.
