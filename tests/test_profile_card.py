import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import update_readme


ROOT = Path(__file__).resolve().parents[1]


class ProfileCardTests(unittest.TestCase):
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
    def site_html(generated_at="2026-07-14T04:15:41.262Z"):
        snapshot = {
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
        payload = f'10:["$","component",null,{{"metrics":{json.dumps(snapshot)}}}]'
        return (
            "<html><script>self.__next_f.push([1,"
            + json.dumps(payload)
            + "])</script></html>"
        )

    def test_personal_site_snapshot_drives_traction_values(self):
        now = datetime(2026, 7, 14, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_url", return_value=self.site_html()
        ):
            values = update_readme.fetch_site_stats(now=now)

        self.assertEqual(values["downloads_data"], "30K+")
        self.assertEqual(values["paid_data"], "2,737+")
        self.assertEqual(values["arr_data"], "$113K+")
        self.assertEqual(values["actions_data"], "163K+")
        self.assertEqual(values["rating_data"], "4.7")
        self.assertEqual(values["reviews_data"], "973")

    def test_stale_personal_site_snapshot_is_rejected(self):
        now = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
        with mock.patch.object(
            update_readme, "fetch_url", return_value=self.site_html()
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
                return 200, {
                    "data": {
                        "user": {
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
            if path == "/repos/kayahickindev/profile/stats/contributors":
                return 200, [
                    {
                        "author": {"login": "kayahickindev"},
                        "weeks": [{"a": 20, "d": 5}],
                    }
                ]
            raise AssertionError(path)

        with mock.patch.object(update_readme, "gh", side_effect=fake_gh):
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
                return 200, {
                    "data": {
                        "user": {
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
            if path.endswith("/stats/contributors"):
                return 202, {}
            raise AssertionError(path)

        with (
            mock.patch.object(update_readme, "gh", side_effect=fake_gh),
            mock.patch.object(update_readme.time, "sleep"),
        ):
            with self.assertRaisesRegex(RuntimeError, "contributor stats unavailable"):
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
                return 200, {
                    "data": {
                        "user": {
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
            if path == "/repos/kayahickindev/profile/stats/contributors":
                return 200, [
                    {
                        "author": {"login": "kayahickindev"},
                        "weeks": [{"a": 20, "d": 5}],
                    }
                ]
            raise AssertionError(path)

        with mock.patch.object(update_readme, "gh", side_effect=fake_gh):
            values = update_readme.fetch_stats("secret")

        self.assertEqual(values["loc_data"], "15")

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
