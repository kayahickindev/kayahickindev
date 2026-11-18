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
historical changes, not the current codebase size. `loc_cache.json` keeps each
repository's totals at a head commit. An unchanged head is reused. A new head
counts only the commits since the cached one: the compare endpoint lists the
range, and the user's non-merge commits in it are summed in batches of 40. A
backlog longer than 2,000 commits is walked in steps, each ending on a commit
that descends from the cached head, and the cache is saved after every step.
When the cached head is no longer an ancestor (rewritten history), the
repository is recounted from scratch, 25 commits per page, shrinking to 5 or 1 after
persistent timeouts. Never go back to recounting whole histories on every new
commit: that is what froze the card from 2026-10-31 to 2026-11-18.

Each completed repository is checkpointed before moving on. A later failure
still prevents publishing partial card totals, but the workflow commits the
checkpoint so the next run resumes from it. The contributed-repositories lookup
times out often on GitHub's side; when it stays unavailable, the repositories
already in the cache stand in for it.
`language_stats.json` uses GitHub-detected bytes from the same repository set.

GitHub gateway failures may contain HTML or plain text instead of JSON. Preserve
the 5xx status so bounded retries run; persistent failure must stop publication,
never publish a partial total. Regression tests cover recovery and exhaustion.

## Layout

The 985 by 545 card has two columns. Left: the stipple portrait (430 by 412
one-pixel cells from `ascii_art_dark.txt` and `ascii_art_light.txt`), then the
language bar and its legend. Right: a 63-column monospace readout that ends on a
`kaya@myfutureself:~$` prompt.

Every dynamic value has a sibling `*_dots` span that absorbs length changes.
Change the builder and `LINE_GROUPS` together when adding or removing metrics.
The builder requires recorded values rather than silently inserting old numbers.
Keep the README free of refresh notes and date rows. Lines added use `addColor`
and lines removed use `delColor`; preserve those classes when updating values.
Name, role, company, location, contact links and follower count belong in
GitHub's sidebar and are intentionally absent from the card. The portrait stays
on the card: do not remove it when changing the readout. Regenerate it from
`headshot.png` with `ascii_v3.py`.

- **Uptime** is age from `BIRTHDATE` in `update_readme.py`, recorded on every
  refresh like the other values.
- **Language bar** leaves out `EXCLUDED_LANGUAGES` (SQL dialects and HTML):
  database dumps and exported pages are not hand-written code, and PLpgSQL used
  to lead the bar at 43%. `language_stats.json` still holds every language
  from repositories that are not forks. A fork's bytes are its upstream's code
  (the React Native fork alone was all of the C++), so forks count toward
  lines of code, which only sums this user's commits, but not toward the bar.
- **Downloads trend** draws the last 90 days of `metrics_history.json` where
  the leader dots would go, with the gain across that window. The product
  endpoint only serves the latest snapshot, so the refresh appends one point
  per day to that file. The series before 2026-11-18 was recovered from the
  values in past card commits.
- **Motion** is CSS inside the SVG, which GitHub keeps for images. A cover
  slides off the portrait on load (52 steps over 2.6 seconds) and the prompt's
  cursor blinks. The cover rests off the portrait, so a viewer that does not
  animate shows the finished card, and `prefers-reduced-motion` turns both off.
