import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
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
            self.assertIn("Toolchain", svg)
            self.assertIn("Claude Code, Codex, Ghostty", svg)
            self.assertIn("Contributions (1y)", svg)
            self.assertIn('id="contribution_data"', svg)
            self.assertNotIn("Xcode", svg)
            self.assertNotIn("Contributed", svg)
            self.assertNotIn('id="contrib_data"', svg)
            self.assertNotIn('id="commit_data"', svg)

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

    def test_unavailable_loc_does_not_block_calendar_refresh(self):
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
            if path.endswith("/stats/contributors"):
                return 202, {}
            raise AssertionError(path)

        with (
            mock.patch.object(update_readme, "gh", side_effect=fake_gh),
            mock.patch.object(update_readme.time, "sleep"),
        ):
            values = update_readme.fetch_stats("secret")

        self.assertEqual(values["contribution_data"], "4,360")
        self.assertNotIn("loc_data", values)

    def test_svg_value_update_preserves_line_width(self):
        source = ROOT / "dark_mode.svg"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "card.svg"
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            update_readme.update_svg(
                target,
                {"contribution_data": "12,345", "follower_data": "10"},
            )
            svg = target.read_text(encoding="utf-8")
            self.assertIn('id="contribution_data">12,345</tspan>', svg)
            self.assertIn('id="follower_data">10</tspan>', svg)
            ET.parse(target)


if __name__ == "__main__":
    unittest.main()
