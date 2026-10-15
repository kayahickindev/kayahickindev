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
The scheduled workflow uses the existing Actions secret and runs every six hours
at 00:40, 06:40, 12:40 and 18:40 UTC. The personal site's daily metrics workflow
also dispatches a refresh when its snapshot is ready. GitHub hosts both workflows;
they do not depend on a local process or an open conversation. Scheduled runs can
be delayed by GitHub; `profile_refresh_state.json` records the source and refresh
timestamps for freshness checks.

Do not enable `SKIP_IF_REFRESHED_TODAY` in the workflow: that legacy daily-fallback
gate would suppress the remaining refreshes after the first success each day.
The per-repository cache already avoids recounting unchanged histories.

## Data and freshness

Product metrics come from `https://kayahickin.com/api/profile-metrics`; fallback
snapshots and snapshots older than 48 hours are rejected. Downloads, paid
subscriptions and actions use exact raw counts. Paid subscriptions uses
`paidSubscribers`, not the legacy `paidSubscribersEver` display value. ARR keeps
the source's public display precision. Freshness timestamps stay in
`profile_refresh_state.json`, outside the visible card.

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

The 700 by 489 card uses 63 monospace columns and a full-width language bar.
Every dynamic value has a sibling `*_dots` span that absorbs length changes.
Change the builder and `LINE_GROUPS` together when adding or removing metrics.
The builder requires recorded values rather than silently inserting old numbers.
Keep the README free of refresh notes and date rows. Lines added use `addColor`
and lines removed use `delColor`; preserve those classes when updating values.
Name, role, portrait, company, location, contact links and follower count belong
in GitHub's sidebar and are intentionally absent from the card. The original
ASCII portrait source and generator remain available under `tools/`.
