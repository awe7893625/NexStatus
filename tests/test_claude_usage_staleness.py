"""Tests for claude_usage() staleness checking based on source file mtime.

Ensures that reset times and percentages older than their respective window lengths
are properly nulled out to prevent stale data from being displayed as current.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from nexstatus import collector


class ClaudeUsageStalenessTests(unittest.TestCase):
    """Test staleness detection based on source file modification time."""

    def _create_temp_claude_file(self, content: dict, age_seconds: float = 0.0) -> Path:
        """Create a temporary Claude status file with specific age."""
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as f:
            json.dump(content, f)
            temp_path = Path(f.name)

        # Set the file's mtime to the desired age
        if age_seconds > 0:
            target_mtime = time.time() - age_seconds
            os.utime(temp_path, (target_mtime, target_mtime))

        return temp_path

    def tearDown(self) -> None:
        """Clean up any temp files created during tests."""
        pass

    def test_stale_five_hour_window_becomes_unknown_while_seven_day_still_trusted(self) -> None:
        """BUG-1/BUG-2 repro: 5h stale, 7d fresh → 5h nulled, 7d passed through.

        Source file is 4 days old (240 hours).
        5-hour window (18000 sec) should be nulled.
        7-day window (604800 sec) should pass through (4 days < 7 days).
        """
        temp_file = self._create_temp_claude_file(
            {
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 45.0,
                        "resets_at": int(time.time() + 2 * 3600),  # 2 hours from now
                    },
                    "seven_day": {
                        "used_percentage": 30.0,
                        "resets_at": int(time.time() + 3 * 86400),  # 3 days from now
                    },
                },
            },
            age_seconds=4 * 24 * 3600,  # 4 days old
        )

        try:
            with mock.patch.object(
                collector, "CLAUDE_STATUS", temp_file
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", Path("/nonexistent")
            ), mock.patch.object(
                collector, "CLAUDE_TT", Path("/nonexistent")
            ):
                result = collector.claude_usage()

            self.assertTrue(result.get("ok"))
            # 5-hour window should be nulled (4 days > 5 hour threshold)
            self.assertIsNone(result.get("five_hour_resets_at"))
            self.assertIsNone(result.get("five_hour_pct"))
            # 7-day window should still be present (4 days < 7 day threshold)
            self.assertIsNotNone(result.get("seven_day_resets_at"))
            self.assertEqual(result.get("seven_day_pct"), 30)
            # result["stale"] should be True because mtime staleness was detected
            self.assertTrue(result.get("stale"))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_stale_both_windows_become_unknown(self) -> None:
        """Source file is 8 days old → both 5h and 7d windows nulled."""
        temp_file = self._create_temp_claude_file(
            {
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 45.0,
                        "resets_at": int(time.time() + 2 * 3600),
                    },
                    "seven_day": {
                        "used_percentage": 30.0,
                        "resets_at": int(time.time() + 3 * 86400),
                    },
                },
            },
            age_seconds=8 * 24 * 3600,  # 8 days old
        )

        try:
            # Use a new list to ensure all paths use the temp file
            paths_to_try = [temp_file, Path("/nonexistent"), Path("/nonexistent")]
            with mock.patch.object(
                collector, "CLAUDE_STATUS", paths_to_try[0]
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", paths_to_try[1]
            ), mock.patch.object(
                collector, "CLAUDE_TT", paths_to_try[2]
            ), mock.patch.object(
                collector, "_claude_from_cache", return_value=None
            ):
                result = collector.claude_usage()

            # When both windows are stale and nulled, ok should be False (rate_limits_missing)
            # because five_pct and seven_pct will both be None
            self.assertFalse(result.get("ok"))
            self.assertEqual(result.get("error"), "rate_limits_missing")
        finally:
            temp_file.unlink(missing_ok=True)

    def test_fresh_source_file_passes_values_through(self) -> None:
        """Source file is fresh (now) → both windows pass through unchanged.

        Negative control: proves the staleness check doesn't false-positive.
        """
        reset_5h = int(time.time() + 2 * 3600)
        reset_7d = int(time.time() + 3 * 86400)
        temp_file = self._create_temp_claude_file(
            {
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 45.0,
                        "resets_at": reset_5h,
                    },
                    "seven_day": {
                        "used_percentage": 30.0,
                        "resets_at": reset_7d,
                    },
                },
            },
            age_seconds=0.0,  # Fresh (now)
        )

        try:
            with mock.patch.object(
                collector, "CLAUDE_STATUS", temp_file
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", Path("/nonexistent")
            ), mock.patch.object(
                collector, "CLAUDE_TT", Path("/nonexistent")
            ):
                result = collector.claude_usage()

            self.assertTrue(result.get("ok"))
            # Both windows should pass through unchanged
            self.assertEqual(result.get("five_hour_pct"), 45)
            self.assertEqual(result.get("seven_day_pct"), 30)
            self.assertEqual(result.get("five_hour_resets_at"), reset_5h)
            self.assertEqual(result.get("seven_day_resets_at"), reset_7d)
            # result["stale"] should be False because source file is fresh
            self.assertFalse(result.get("stale"))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_already_past_resets_at_with_fresh_mtime_applies_existing_zero_logic(self) -> None:
        """Regression guard: already-past resets_at with FRESH mtime still zeros percentage.

        The existing per-value check (resets_at < now → pct=0) should run AFTER
        the staleness check and still apply even for fresh data.
        """
        temp_file = self._create_temp_claude_file(
            {
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 45.0,
                        "resets_at": int(time.time() - 60),  # 60 sec in the past
                    },
                    "seven_day": {
                        "used_percentage": 30.0,
                        "resets_at": int(time.time() + 3 * 86400),  # Still in future
                    },
                },
            },
            age_seconds=0.0,  # Fresh
        )

        try:
            with mock.patch.object(
                collector, "CLAUDE_STATUS", temp_file
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", Path("/nonexistent")
            ), mock.patch.object(
                collector, "CLAUDE_TT", Path("/nonexistent")
            ):
                result = collector.claude_usage()

            self.assertTrue(result.get("ok"))
            # 5h reset is in the past → percentage should be zeroed
            self.assertEqual(result.get("five_hour_pct"), 0)
            # 7d reset is still in future → percentage should be unchanged
            self.assertEqual(result.get("seven_day_pct"), 30)
        finally:
            temp_file.unlink(missing_ok=True)

    def test_five_hour_window_exactly_at_threshold_still_trusted(self) -> None:
        """Boundary test: source_age == CLAUDE_FIVE_HOUR_WINDOW_SEC (exactly, not approximately)
        must still be trusted, because the staleness check is strict `>`, not `>=`.

        A naive version of this test that only sets the file's mtime relative to
        `time.time()` at setup time and lets `claude_usage()` call a fresh `time.time()`
        internally cannot reliably hit the exact threshold: wall-clock time elapses
        between file creation and the staleness check inside `claude_usage()`, so
        `source_age` always ends up a little *larger* than the `age_seconds` requested
        at setup, and a test aimed at "exactly 18000" would flake across the >/>= line
        depending on scheduling jitter. To make the boundary deterministic, this test
        pins both the file's mtime and `claude_usage()`'s notion of "now" 18000.0
        seconds apart with no real-clock dependency in between, via
        `mock.patch.object(collector, "_now", ...)`.
        """
        fixed_now = time.time()
        reset_5h = int(fixed_now + 2 * 3600)
        reset_7d = int(fixed_now + 3 * 86400)
        temp_file = self._create_temp_claude_file(
            {
                "rate_limits": {
                    "five_hour": {
                        "used_percentage": 45.0,
                        "resets_at": reset_5h,
                    },
                    "seven_day": {
                        "used_percentage": 30.0,
                        "resets_at": reset_7d,
                    },
                },
            },
        )
        # Force the file's mtime so that (fixed_now - mtime) == CLAUDE_FIVE_HOUR_WINDOW_SEC
        # exactly, once claude_usage() is also pinned to `fixed_now` below.
        target_mtime = fixed_now - collector.CLAUDE_FIVE_HOUR_WINDOW_SEC
        os.utime(temp_file, (target_mtime, target_mtime))

        try:
            with mock.patch.object(
                collector, "_now", return_value=fixed_now
            ), mock.patch.object(
                collector, "CLAUDE_STATUS", temp_file
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", Path("/nonexistent")
            ), mock.patch.object(
                collector, "CLAUDE_TT", Path("/nonexistent")
            ):
                result = collector.claude_usage()

            self.assertTrue(result.get("ok"))
            # source_age is exactly CLAUDE_FIVE_HOUR_WINDOW_SEC; strict `>` means the
            # window is still trusted at the exact boundary (only *past* the boundary
            # should it flip to unknown).
            self.assertEqual(result.get("five_hour_pct"), 45)
            self.assertEqual(result.get("five_hour_resets_at"), reset_5h)
            # 7-day window is nowhere near its own threshold, must pass through too.
            self.assertEqual(result.get("seven_day_pct"), 30)
            self.assertEqual(result.get("seven_day_resets_at"), reset_7d)
            # result["stale"] should be False because mtime is exactly at, not past,
            # the threshold.
            self.assertFalse(result.get("stale"))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_unreadable_source_file_mtime_nulls_both_windows(self) -> None:
        """If source file mtime cannot be read, treat both windows as unknown/too stale."""
        # This test uses a lambda to simulate a path whose stat() fails
        class FailingPath:
            def __init__(self, p: Path):
                self.path = p

            def read_text(self, encoding: str = "utf-8") -> str:
                return self.path.read_text(encoding=encoding)

            def stat(self):
                raise OSError("Permission denied")

            def is_file(self) -> bool:
                return self.path.is_file()

        data_obj = {
            "rate_limits": {
                "five_hour": {
                    "used_percentage": 45.0,
                    "resets_at": int(time.time() + 2 * 3600),
                },
                "seven_day": {
                    "used_percentage": 30.0,
                    "resets_at": int(time.time() + 3 * 86400),
                },
            },
        }

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump(data_obj, f)
                temp_path = Path(f.name)

            failing_path = FailingPath(temp_path)

            with mock.patch.object(
                collector, "CLAUDE_STATUS", failing_path
            ), mock.patch.object(
                collector, "CLAUDE_LEGACY", Path("/nonexistent")
            ), mock.patch.object(
                collector, "CLAUDE_TT", Path("/nonexistent")
            ), mock.patch.object(
                collector, "_claude_from_cache", return_value=None
            ):
                result = collector.claude_usage()

            # When mtime is unreadable, both windows should be nulled
            # and ok should be False (rate_limits_missing)
            self.assertFalse(result.get("ok"))
            self.assertEqual(result.get("error"), "rate_limits_missing")
        finally:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
