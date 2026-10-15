import io
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import update_readme


ROOT = Path(__file__).resolve().parents[1]


class ProfileCardTests(unittest.TestCase):
    def test_graphql_retries_non_json_gateway_errors(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/graphql", 502, "Bad Gateway", {},
            io.BytesIO(b"<html>upstream request timeout</html>"),
        )
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"data":{"viewer":{"login":"kayahickindev"}}}'
        with (
            mock.patch.object(update_readme.urllib.request, "urlopen",
                              side_effect=[error, response]) as request,
            mock.patch.object(update_readme.time, "sleep"),
        ):
            result = update_readme.graphql("query { viewer { login } }", {},
                                           "secret", "profile")
        self.assertEqual(result["viewer"]["login"], "kayahickindev")
        self.assertEqual(request.call_count, 2)

    def test_graphql_persistent_gateway_errors_fail_after_bounded_retries(self):
        errors = [urllib.error.HTTPError(
            "https://api.github.com/graphql", 502, "Bad Gateway", {},
            io.BytesIO(b"Bad Gateway"),
        ) for _ in range(4)]
        with (
            mock.patch.object(update_readme.urllib.request, "urlopen",
                              side_effect=errors) as request,
            mock.patch.object(update_readme.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "unavailable: HTTP 502"):
                update_readme.graphql("query {}", {}, "secret", "profile")
        self.assertEqual(request.call_count, 4)

    def test_github_server_error_is_returned_for_bounded_retry(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/test",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"message":"try again"}'),
        )
        with mock.patch.object(update_readme.urllib.request, "urlopen", side_effect=error):
            status, body = update_readme.gh("/graphql", "secret")

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "try again"})

    def test_language_gateway_failure_cannot_look_like_an_empty_repository(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/repos/owner/repo/languages", 502,
            "Bad Gateway", {}, io.BytesIO(b"Bad Gateway"),
        )
        with mock.patch.object(update_readme.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "unavailable: HTTP 502"):
                update_readme.gh("/repos/owner/repo/languages", "secret")

    def test_generated_svgs_have_expected_dynamic_fields(self):
        for name in ("dark_mode.svg", "light_mode.svg"):
            path = ROOT / name
            ET.parse(path)
            svg = path.read_text(encoding="utf-8")
            self.assertIn("Claude Code, Codex, Ghostty, Wispr Flow, Herdr", svg)
            self.assertNotIn("OpenClaw", svg)
            self.assertNotIn("Product data", svg)
            self.assertNotIn("GitHub data", svg)
            self.assertIn('class="addColor" id="loc_add"', svg)
            self.assertIn('class="delColor" id="loc_del"', svg)
            for duplicate in ("Co-founder", "Cleveland", "Email.Work", "Website",
                              "@KayaHickin", "Followers", 'class="ascii"'):
                self.assertNotIn(duplicate, svg)
            self.assertIn('id="downloads_data"', svg)
            self.assertIn('id="paid_data"', svg)
            self.assertIn('id="arr_data"', svg)
            self.assertIn('id="actions_data"', svg)
            self.assertIn('id="rating_data"', svg)
            self.assertIn('id="reviews_data"', svg)
            self.assertIn("Contributions (1y)", svg)
            self.assertIn('id="contribution_data"', svg)
            self.assertNotIn("Xcode", svg)
            self.assertNotIn("Contributed", svg)
            self.assertNotIn('id="contrib_data"', svg)
            self.assertNotIn('id="commit_data"', svg)

    @staticmethod
    def site_snapshot(generated_at="2026-07-14T04:15:41.262Z"):
        return {
            "generatedAt": generated_at,
            "metrics": {
                "appDownloads": {"raw": 30000},
                "appStoreRating": {"raw": 4.72},
                "appStoreReviews": {"raw": 973},
                "futureSelfActions": {"raw": 163363},
                "coachingValueDelivered": {"raw": 10618595},
                "paidSubscribers": {"raw": 2737, "label": "Paid Subscriptions"},
                "paidSubscribersEver": {
                    "display": "2.7K+",
                    "label": "Active Paid Subscribers",
                },
                "arr": {"display": "$113K+", "label": "Annual Run Rate"},
            },
        }

    def test_personal_site_snapshot_drives_traction_values(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_json_url", return_value=self.site_snapshot()
        ):
            values, generated_at = update_readme.fetch_site_stats(now=now)

        self.assertEqual(generated_at, "2026-07-14T04:15:41.262Z")
        self.assertEqual(values["downloads_data"], "30,000")
        self.assertEqual(values["paid_data"], "2,737")
        self.assertEqual(values["arr_data"], "$113K+")
        self.assertEqual(values["actions_data"], "163,363")
        self.assertEqual(values["rating_data"], "4.7")
        self.assertEqual(values["reviews_data"], "973")

    def test_stale_personal_site_snapshot_is_rejected(self):
        now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_json_url", return_value=self.site_snapshot()
        ):
            with self.assertRaisesRegex(RuntimeError, "not fresh"):
                update_readme.fetch_site_stats(now=now)

    def test_sensitive_profile_metrics_require_public_display_values(self):
        snapshot = self.site_snapshot()
        del snapshot["metrics"]["arr"]["display"]

        with mock.patch.object(
            update_readme, "fetch_json_url", return_value=snapshot
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid profile metric arr"):
                update_readme.fetch_site_stats(
                    now=datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
                )

    def test_portrait_sources_fit_the_left_panel(self):
        for polarity in ("dark", "light"):
            lines = (ROOT / "tools" / f"ascii_art_{polarity}.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertLessEqual(len(lines), 412, polarity)
            self.assertLessEqual(max(map(len, lines)), 430, polarity)
            # The crop should start on the subject, not well above it. Counted
            # as a fraction of the grid so it survives a density change.
            head = max(1, round(len(lines) * 0.08))
            self.assertTrue(any(lines[:head]), polarity)

    def test_cards_scale_instead_of_clipping(self):
        for name in ("dark_mode.svg", "light_mode.svg"):
            root = ET.parse(ROOT / name).getroot()
            self.assertEqual(root.attrib.get("viewBox"), "0 0 700 489", name)

    def test_language_bar_segments_fill_the_track(self):
        totals = json.loads(
            (ROOT / "language_stats.json").read_text(encoding="utf-8")
        )
        self.assertTrue(totals["languages"])
        for name in ("dark_mode.svg", "light_mode.svg"):
            svg = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn('clip-path="url(#barClip)"', svg)
            group = svg.split('<g clip-path="url(#barClip)">')[1].split("</g>")[0]
            segments = re.findall(
                r'<rect x="([\d.]+)" y="414" width="([\d.]+)"', group
            )
            self.assertGreaterEqual(len(segments), 2, name)
            covered = sum(float(width) for _, width in segments)
            self.assertAlmostEqual(covered, 652.0, delta=0.5, msg=name)
            self.assertIn(totals["languages"][0]["name"], svg, name)

    def test_widest_readout_line_stays_inside_the_card(self):
        """The lines-of-code row is the one that outgrows the panel.

        It used to be clamped to a single leader dot and allowed to run two
        columns long, which pushed the totals off the right edge of the card.
        """
        for name in ("dark_mode.svg", "light_mode.svg"):
            svg = (ROOT / name).read_text(encoding="utf-8")
            rows = re.findall(r'<tspan x="24" y="(\d+)" class="cc">\. </tspan>', svg)
            self.assertTrue(rows)
            for row_y in rows:
                line = svg.split(f'<tspan x="24" y="{row_y}" class="cc">. </tspan>')[1]
                line = line.split('<tspan x="24" y=')[0]
                text = re.sub(r"<[^>]+>", "", line).replace("\n", "")
                text = (text.replace("&amp;", "&").replace("&lt;", "<")
                        .replace("&gt;", ">"))
                self.assertEqual(len(text) + 2, 63, (name, row_y, text))

    def test_rebuild_is_stable_and_preserves_refreshed_values(self):
        """The nightly job runs the builder right after the refresh.

        If a rebuild did not round-trip the values it just wrote, every night
        would reset the card to the fallback snapshot in the builder.
        """
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "build_svg.py"),
                 "--output-dir", directory],
                check=True, capture_output=True, cwd=ROOT,
            )
            rebuilt = (Path(directory) / "dark_mode.svg").read_text(encoding="utf-8")
        self.assertEqual(rebuilt, (ROOT / "dark_mode.svg").read_text(encoding="utf-8"))

    def test_calendar_total_is_used_without_contributed_repo_count(self):
        graphql_queries = []

        def fake_gh(path, _token, method="GET", body=None):
            if path == "/user":
                return 200, {"followers": 9}
            if path.startswith("/user/repos"):
                return 200, [{"full_name": "kayahickindev/profile"}]
            if path.startswith("/search/issues"):
                return 200, {"total_count": 591}
            if path.endswith("/languages"):
                return 200, {"Python": 100}
            if path == "/graphql":
                graphql_queries.append(body["query"])
                if "history(" in body["query"]:
                    return 200, {
                        "data": {
                            "repository": {
                                "defaultBranchRef": {
                                    "target": {
                                        "history": {
                                            "nodes": [
                                                {
                                                    "additions": 20,
                                                    "deletions": 5,
                                                    "parents": {"totalCount": 1},
                                                }
                                            ],
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                return 200, {
                    "data": {
                        "user": {
                            "id": "U_1",
                            "contributionsCollection": {
                                "startedAt": "2025-07-06T07:00:00Z",
                                "endedAt": "2026-07-11T06:59:59Z",
                                "contributionCalendar": {
                                    "totalContributions": 4360
                                },
                            }
                        },
                        "viewer": {
                            "repositoriesContributedTo": {"nodes": []}
                        },
                    }
                }
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as directory:
            language_path = Path(directory) / "language_stats.json"
            with (
                mock.patch.object(update_readme, "gh", side_effect=fake_gh),
                mock.patch.object(
                    update_readme, "fetch_repo_head", return_value="head-1"
                ),
            ):
                values = update_readme.fetch_stats(
                    "secret", language_stats_path=language_path
                )
            language_totals = json.loads(language_path.read_text(encoding="utf-8"))

        self.assertEqual(values["contribution_data"], "4,360")
        self.assertEqual(language_totals["languages"], [{"name": "Python", "bytes": 100}])
        self.assertNotIn("commit_data", values)
        self.assertNotIn("contrib_data", values)
        self.assertEqual(values["loc_data"], "15")
        self.assertIn("contributionsCollection", graphql_queries[0])
        self.assertNotIn("totalCount", graphql_queries[0])

    def test_unavailable_loc_fails_instead_of_publishing_partial_total(self):
        responses = {
            "/user": (200, {"followers": 9}),
            "/user/repos?affiliation=owner&per_page=100&page=1": (
                200,
                [{"full_name": "kayahickindev/profile"}],
            ),
        }

        def fake_gh(path, _token, method="GET", body=None):
            if path in responses:
                return responses[path]
            if path.startswith("/search/issues"):
                return 200, {"total_count": 591}
            if path == "/graphql":
                if "history(" in body["query"]:
                    return 200, {"errors": [{"message": "history unavailable"}]}
                return 200, {
                    "data": {
                        "user": {
                            "id": "U_1",
                            "contributionsCollection": {
                                "startedAt": "start",
                                "endedAt": "end",
                                "contributionCalendar": {
                                    "totalContributions": 4360
                                },
                            }
                        },
                        "viewer": {
                            "repositoriesContributedTo": {"nodes": []}
                        },
                    }
                }
            if path.endswith("/languages"):
                return 200, {"Python": 100}
            raise AssertionError(path)

        with (
            mock.patch.object(update_readme, "gh", side_effect=fake_gh),
            mock.patch.object(update_readme, "fetch_repo_head", return_value="head-1"),
        ):
            with self.assertRaisesRegex(RuntimeError, "GraphQL error"):
                update_readme.fetch_stats("secret")

    def test_repository_without_source_languages_is_excluded_from_loc(self):
        def fake_gh(path, _token, method="GET", body=None):
            if path == "/user":
                return 200, {"followers": 9}
            if path.startswith("/user/repos"):
                return 200, [
                    {"full_name": "kayahickindev/profile"},
                    {"full_name": "kayahickindev/calendar-fixture"},
                ]
            if path.startswith("/search/issues"):
                return 200, {"total_count": 591}
            if path == "/graphql":
                if "history(" in body["query"]:
                    return 200, {
                        "data": {
                            "repository": {
                                "defaultBranchRef": {
                                    "target": {
                                        "history": {
                                            "nodes": [
                                                {
                                                    "additions": 20,
                                                    "deletions": 5,
                                                    "parents": {"totalCount": 1},
                                                }
                                            ],
                                            "pageInfo": {
                                                "hasNextPage": False,
                                                "endCursor": None,
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                return 200, {
                    "data": {
                        "user": {
                            "id": "U_1",
                            "contributionsCollection": {
                                "startedAt": "start",
                                "endedAt": "end",
                                "contributionCalendar": {"totalContributions": 4360},
                            }
                        },
                        "viewer": {"repositoriesContributedTo": {"nodes": []}},
                    }
                }
            if path == "/repos/kayahickindev/profile/languages":
                return 200, {"Python": 100}
            if path == "/repos/kayahickindev/calendar-fixture/languages":
                return 200, {}
            raise AssertionError(path)

        with (
            mock.patch.object(update_readme, "gh", side_effect=fake_gh),
            mock.patch.object(update_readme, "fetch_repo_head", return_value="head-1"),
        ):
            values = update_readme.fetch_stats("secret")

        self.assertEqual(values["loc_data"], "15")

    def test_graphql_loc_paginates_and_skips_merge_commits(self):
        def fake_gh(path, _token, method="GET", body=None):
            if path != "/graphql":
                raise AssertionError(path)
            if body["variables"]["cursor"] is None:
                return 200, {
                    "data": {
                        "repository": {
                            "defaultBranchRef": {
                                "target": {
                                    "history": {
                                        "nodes": [
                                            {
                                                "additions": 20,
                                                "deletions": 5,
                                                "parents": {"totalCount": 1},
                                            },
                                            {
                                                "additions": 100,
                                                "deletions": 100,
                                                "parents": {"totalCount": 2},
                                            },
                                        ],
                                        "pageInfo": {
                                            "hasNextPage": True,
                                            "endCursor": "next",
                                        },
                                    }
                                }
                            }
                        }
                    }
                }
            return 200, {
                "data": {
                    "repository": {
                        "defaultBranchRef": {
                            "target": {
                                "history": {
                                    "nodes": [
                                        {
                                            "additions": 8,
                                            "deletions": 3,
                                            "parents": {"totalCount": 1},
                                        }
                                    ],
                                    "pageInfo": {
                                        "hasNextPage": False,
                                        "endCursor": None,
                                    },
                                }
                            }
                        }
                    }
                }
            }

        with mock.patch.object(update_readme, "gh", side_effect=fake_gh):
            additions, deletions = update_readme.fetch_repo_loc(
                "kayahickindev/kayahickindev", "U_1", "secret"
            )

        self.assertEqual(additions, 28)
        self.assertEqual(deletions, 8)

    def test_unchanged_repository_reuses_cached_loc(self):
        cache = {
            "kayahickindev/example": {
                "headOid": "same-head",
                "additions": 120,
                "deletions": 20,
            }
        }
        with (
            mock.patch.object(
                update_readme, "fetch_repo_head", return_value="same-head"
            ),
            mock.patch.object(update_readme, "fetch_repo_loc") as fetch_repo_loc,
        ):
            result = update_readme.fetch_cached_repo_loc(
                "kayahickindev/example", "U_1", "secret", cache
            )

        self.assertEqual(result[:2], (120, 20))
        fetch_repo_loc.assert_not_called()

    def test_history_timeout_reduces_page_size_without_recounting_prior_page(self):
        def page(additions, deletions, cursor):
            return {"repository": {"defaultBranchRef": {"target": {"history": {
                "nodes": [{"additions": additions, "deletions": deletions,
                           "parents": {"totalCount": 1}}],
                "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
            }}}}}

        with mock.patch.object(update_readme, "graphql", side_effect=[
            page(20, 5, "next"),
            RuntimeError("GitHub GraphQL history unavailable: HTTP 502"),
            page(8, 3, None),
        ]) as query:
            result = update_readme.fetch_repo_loc("owner/repo", "U_1", "secret")
        self.assertEqual(result, (28, 8))
        variables = [call.args[1] for call in query.call_args_list]
        self.assertEqual([v["pageSize"] for v in variables], [25, 25, 5])
        self.assertEqual([v["cursor"] for v in variables], [None, "next", "next"])

    def test_completed_repository_is_cached_when_later_repository_fails(self):
        summary = {
            "user": {"id": "U_1", "contributionsCollection": {
                "startedAt": "start", "endedAt": "end",
                "contributionCalendar": {"totalContributions": 10},
            }},
            "viewer": {"repositoriesContributedTo": {"nodes": []}},
        }

        def fake_gh(path, _token):
            if path == "/user":
                return 200, {"followers": 9}
            if path.startswith("/user/repos"):
                return 200, [{"full_name": "owner/first"}, {"full_name": "owner/second"}]
            if path.startswith("/search/issues"):
                return 200, {"total_count": 10}
            if path.endswith("/languages"):
                return 200, {"Python": 100}
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "loc.json"
            with (
                mock.patch.object(update_readme, "gh", side_effect=fake_gh),
                mock.patch.object(update_readme, "graphql", return_value=summary),
                mock.patch.object(update_readme, "fetch_repo_head", return_value="head"),
                mock.patch.object(update_readme, "fetch_repo_loc", side_effect=[
                    (120, 20), RuntimeError("history unavailable"),
                ]),
            ):
                with self.assertRaisesRegex(RuntimeError, "history unavailable"):
                    update_readme.fetch_stats("secret", loc_cache_path=cache_path)
            cache = update_readme.load_loc_cache(cache_path)
        self.assertEqual(cache, {"owner/first": {
            "headOid": "head", "additions": 120, "deletions": 20,
        }})

    def test_changed_repository_refreshes_cached_loc(self):
        cache = {
            "kayahickindev/example": {
                "headOid": "old-head",
                "additions": 120,
                "deletions": 20,
            }
        }
        with (
            mock.patch.object(
                update_readme, "fetch_repo_head", return_value="new-head"
            ),
            mock.patch.object(
                update_readme, "fetch_repo_loc", return_value=(150, 30)
            ) as fetch_repo_loc,
        ):
            result = update_readme.fetch_cached_repo_loc(
                "kayahickindev/example", "U_1", "secret", cache
            )

        self.assertEqual(result[:2], (150, 30))
        self.assertEqual(result[2]["headOid"], "new-head")
        fetch_repo_loc.assert_called_once()

    def test_refresh_state_gates_same_day_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                '{"refreshedOn":"2026-07-14"}\n', encoding="utf-8"
            )

            self.assertTrue(
                update_readme.refreshed_today(
                    state_path, today=date(2026, 7, 14)
                )
            )
            self.assertFalse(
                update_readme.refreshed_today(
                    state_path, today=date(2026, 7, 15)
                )
            )

    def test_svg_value_update_preserves_line_width(self):
        source = ROOT / "dark_mode.svg"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "card.svg"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            update_readme.update_svg(
                target,
                {
                    "paid_data": "12,345+",
                    "contribution_data": "12,345",
                    "loc_add": "15,000,000",
                    "loc_del": "6,000,000",
                },
            )
            svg = target.read_text(encoding="utf-8")
            self.assertIn('id="paid_data">12,345+</tspan>', svg)
            self.assertIn('id="contribution_data">12,345</tspan>', svg)
            self.assertIn('class="addColor" id="loc_add">15,000,000</tspan>', svg)
            self.assertIn('class="delColor" id="loc_del">6,000,000</tspan>', svg)
            ET.parse(target)


if __name__ == "__main__":
    unittest.main()
