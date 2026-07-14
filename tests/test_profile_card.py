import io
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import update_readme


ROOT = Path(__file__).resolve().parents[1]


class ProfileCardTests(unittest.TestCase):
    def test_github_server_error_is_returned_for_bounded_retry(self):
        error = urllib.error.HTTPError(
            "https://api.github.com/test",
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"message":"try again"}'),
        )
        with mock.patch.object(update_readme.urllib.request, "urlopen", side_effect=error):
            status, body = update_readme.gh("/test", "secret")

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "try again"})

    def test_generated_svgs_have_expected_dynamic_fields(self):
        for name in ("dark_mode.svg", "light_mode.svg"):
            path = ROOT / name
            ET.parse(path)
            svg = path.read_text(encoding="utf-8")
            self.assertIn("Co-founder &amp; CTO", svg)
            self.assertIn("Cleveland, OH", svg)
            self.assertIn("Claude Code, Codex, Ghostty, OpenClaw", svg)
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
                "paidSubscribersEver": {"raw": 2737},
                "arr": {"raw": 113032},
            },
        }

    def test_personal_site_snapshot_drives_traction_values(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_json_url", return_value=self.site_snapshot()
        ):
            values, generated_at = update_readme.fetch_site_stats(now=now)

        self.assertEqual(generated_at, "2026-07-14T04:15:41.262Z")
        self.assertEqual(values["downloads_data"], "30K+")
        self.assertEqual(values["paid_data"], "2,737+")
        self.assertEqual(values["arr_data"], "$113K+")
        self.assertEqual(values["actions_data"], "163K+")
        self.assertEqual(values["rating_data"], "4.7")
        self.assertEqual(values["reviews_data"], "973")

    def test_stale_personal_site_snapshot_is_rejected(self):
        now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_json_url", return_value=self.site_snapshot()
        ):
            with self.assertRaisesRegex(RuntimeError, "not fresh"):
                update_readme.fetch_site_stats(now=now)

    def test_portrait_source_fits_the_left_panel(self):
        lines = (ROOT / "tools" / "ascii_art_C.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertEqual(len(lines), 25)
        self.assertLessEqual(max(map(len, lines)), 37)
        self.assertTrue(any(lines[:4]))

    def test_uptime_handles_month_boundary(self):
        self.assertEqual(
            update_readme.uptime_string(date(2026, 3, 1)),
            "22 years, 1 month, 10 days",
        )

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

        with (
            mock.patch.object(update_readme, "gh", side_effect=fake_gh),
            mock.patch.object(update_readme, "fetch_repo_head", return_value="head-1"),
        ):
            values = update_readme.fetch_stats("secret")

        self.assertEqual(values["contribution_data"], "4,360")
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
                    "follower_data": "10",
                },
            )
            svg = target.read_text(encoding="utf-8")
            self.assertIn('id="paid_data">12,345+</tspan>', svg)
            self.assertIn('id="contribution_data">12,345</tspan>', svg)
            self.assertIn('id="follower_data">10</tspan>', svg)
            ET.parse(target)


if __name__ == "__main__":
    unittest.main()
