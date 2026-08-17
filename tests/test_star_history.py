from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import star_history  # noqa: E402

UTC = timezone.utc


class FixedClock:
    def __init__(self, value: str) -> None:
        self._value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    def now(self) -> datetime:
        return self._value


def sample_state(snapshots=None):
    return {
        "schema_version": 1,
        "repository": "lintsinghua/DeepAudit",
        "timezone": "UTC",
        "ongoing_interval_days": 13,
        "reconstruction": {
            "method": "current_stargazers_starred_at",
            "generated_at": "2026-07-01T00:00:00Z",
            "daily": [
                {"date": "2026-06-01", "stars": 10},
                {"date": "2026-06-20", "stars": 100},
            ],
        },
        "snapshots": snapshots or [],
    }


class StarHistoryTests(unittest.TestCase):
    def test_due_boundary_matches_configured_interval(self):
        latest = datetime(2026, 7, 20, 5, 0, 0, tzinfo=UTC)
        state = sample_state([{"at": "2026-07-20T05:00:00Z", "stars": 120}])
        boundary = latest + timedelta(days=star_history.INTERVAL_DAYS)
        cases = [
            ((boundary - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), False),
            (boundary.strftime("%Y-%m-%dT%H:%M:%SZ"), True),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(star_history._snapshot_due(state, FixedClock(now).now()), expected)

    def test_record_before_due_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            state = sample_state([{"at": "2026-07-20T05:00:00Z", "stars": 120}])
            star_history._write_outputs(workspace, state)
            before = tuple(
                path.read_bytes()
                for path in (
                    workspace / star_history.STATE_RELATIVE,
                    workspace / star_history.LIGHT_SVG_RELATIVE,
                    workspace / star_history.DARK_SVG_RELATIVE,
                )
            )
            latest = datetime(2026, 7, 20, 5, 0, 0, tzinfo=UTC)
            before_due = latest + timedelta(days=star_history.INTERVAL_DAYS, seconds=-1)
            result = star_history.execute(
                "record",
                workspace=workspace,
                clock=FixedClock(before_due.strftime("%Y-%m-%dT%H:%M:%SZ")),
                star_count=121,
            )
            after = tuple(
                path.read_bytes()
                for path in (
                    workspace / star_history.STATE_RELATIVE,
                    workspace / star_history.LIGHT_SVG_RELATIVE,
                    workspace / star_history.DARK_SVG_RELATIVE,
                )
            )
            self.assertFalse(result.changed)
            self.assertFalse(result.due)
            self.assertEqual(before, after)

    def test_record_writes_snapshot_and_both_themes(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            star_history._write_outputs(workspace, sample_state())
            result = star_history.execute(
                "record",
                workspace=workspace,
                clock=FixedClock("2026-07-20T05:00:00Z"),
                star_count=150,
            )
            self.assertTrue(result.changed)
            state = json.loads((workspace / star_history.STATE_RELATIVE).read_text())
            self.assertEqual(state["snapshots"], [{"at": "2026-07-20T05:00:00Z", "stars": 150}])
            light = (workspace / star_history.LIGHT_SVG_RELATIVE).read_text()
            dark = (workspace / star_history.DARK_SVG_RELATIVE).read_text()
            self.assertIn("#dd4528", light)
            self.assertIn("#ffffff", light)
            self.assertIn("#ff6b6b", dark)
            self.assertIn("#0d1117", dark)
            self.assertIn("xkcdify", light)
            self.assertIn("DeepAudit Star History", light)
            self.assertIn("lintsinghua/DeepAudit", light)
            ET.fromstring(light)
            ET.fromstring(dark)

    def test_render_is_deterministic_and_self_contained(self):
        state = sample_state([{"at": "2026-07-20T05:00:00Z", "stars": 150}])
        first = star_history.render_svg(state, "light")
        second = star_history.render_svg(state, "light")
        self.assertEqual(first, second)
        text = first.decode("utf-8")
        self.assertNotIn("http://", text.replace("http://www.w3.org/2000/svg", ""))
        self.assertNotIn("https://", text)
        self.assertIn("data:image/jpeg;base64,", text)
        self.assertIn("data:image/png;base64,", text)

    def test_backfill_builds_daily_totals(self):
        stamps = [
            datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 6, 3, 8, 0, tzinfo=UTC),
        ]
        state = star_history.build_backfill_state(stamps, datetime(2026, 6, 4, 0, 0, tzinfo=UTC))
        self.assertEqual(
            state["reconstruction"]["daily"],
            [
                {"date": "2026-06-01", "stars": 2},
                {"date": "2026-06-03", "stars": 3},
            ],
        )

    def test_workflow_uses_twice_monthly_schedule(self):
        workflow = (ROOT / ".github/workflows/update-star-history.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 3 1,16 * *'", workflow)
        self.assertNotIn("cron: '17 3 * * 1'", workflow)
        self.assertIn("scripts/star_history.py update", workflow)

    def test_readmes_use_local_svgs(self):
        for name in ("README.md", "README_EN.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("docs/images/star-history-light.svg", text)
            self.assertIn("docs/images/star-history-dark.svg", text)
            self.assertNotIn("api.star-history.com", text)


if __name__ == "__main__":
    unittest.main()
