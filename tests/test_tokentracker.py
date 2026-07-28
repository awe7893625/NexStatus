from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from nexstatus import local_integrations


class TestTokenTracker(unittest.TestCase):
    def setUp(self):
        self.tz = ZoneInfo("Asia/Taipei")
        self.now = datetime(2026, 7, 28, 12, 0, 0, tzinfo=self.tz)

    def test_deduplication_and_counts_and_sorting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_file = Path(tmpdir) / "queue.jsonl"

            # Create data:
            # 1. Deduplication check: same (source, model, hour_start) - last record should win.
            # 2. Taipei timezone today / rolling 7d / rolling 30d tests.
            # 3. Source sorting check by tokens desc, convs desc, id asc.
            records = [
                # First record for src-b hour 11:00
                {
                    "source": "src-b",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 100,
                    "conversation_count": 1,
                },
                # Duplicate record for src-b, model-a, 11:00 (should overwrite 100 -> 200, 1 -> 2)
                {
                    "source": "src-b",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 200,
                    "conversation_count": 2,
                },
                # Today record for src-a (500 tokens, 5 convs)
                {
                    "source": "src-a",
                    "model": "model-a",
                    "hour_start": "2026-07-28T10:00:00+08:00",
                    "total_tokens": 500,
                    "conversation_count": 5,
                },
                # 3 days ago record (within 7d and 30d) for src-c (500 tokens, 10 convs)
                {
                    "source": "src-c",
                    "model": "model-b",
                    "hour_start": "2026-07-25T12:00:00+08:00",
                    "total_tokens": 500,
                    "conversation_count": 10,
                },
                # 15 days ago record (within 30d, outside 7d) for src-d (300 tokens, 3 convs)
                {
                    "source": "src-d",
                    "model": "model-b",
                    "hour_start": "2026-07-13T12:00:00+08:00",
                    "total_tokens": 300,
                    "conversation_count": 3,
                },
                # 40 days ago record (outside 30d) for src-e (1000 tokens, 1 conv)
                {
                    "source": "src-e",
                    "model": "model-b",
                    "hour_start": "2026-06-10T12:00:00+08:00",
                    "total_tokens": 1000,
                    "conversation_count": 1,
                },
            ]

            with open(queue_file, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            res = local_integrations.tokentracker_usage(
                queue_path=queue_file, now=self.now
            )

            self.assertTrue(res["ok"])
            self.assertIsNone(res["error"])
            self.assertEqual(res["status"], "live")

            # Today: src-b (200, 2) + src-a (500, 5) = (700, 7)
            self.assertEqual(res["today"]["tokens"], 700)
            self.assertEqual(res["today"]["conversations"], 7)

            # Rolling 7d: Today (700, 7) + 3 days ago src-c (500, 10) = (1200, 17)
            self.assertEqual(res["rolling_7d"]["tokens"], 1200)
            self.assertEqual(res["rolling_7d"]["conversations"], 17)

            # Rolling 30d: 7d (1200, 17) + 15 days ago src-d (300, 3) = (1500, 20)
            self.assertEqual(res["rolling_30d"]["tokens"], 1500)
            self.assertEqual(res["rolling_30d"]["conversations"], 20)

            # Sorting check for sources_30d:
            # src-a: 500, convs: 5
            # src-c: 500, convs: 10
            # src-d: 300, convs: 3
            # src-b: 200, convs: 2
            # Expected order:
            # 1. src-c (500 tokens, 10 convs) - higher convs than src-a
            # 2. src-a (500 tokens, 5 convs)
            # 3. src-d (300 tokens, 3 convs)
            # 4. src-b (200 tokens, 2 convs)
            expected_sources = [
                {"id": "src-c", "tokens": 500, "conversations": 10},
                {"id": "src-a", "tokens": 500, "conversations": 5},
                {"id": "src-d", "tokens": 300, "conversations": 3},
                {"id": "src-b", "tokens": 200, "conversations": 2},
            ]
            self.assertEqual(res["sources_30d"], expected_sources)

    def test_missing_all_malformed_and_stale(self):
        # Missing file test
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = Path(tmpdir) / "non_existent.jsonl"
            res = local_integrations.tokentracker_usage(
                queue_path=non_existent, now=self.now
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "missing")
            self.assertEqual(res["error"], "tokentracker_missing")

        # All malformed test
        with tempfile.TemporaryDirectory() as tmpdir:
            malformed_file = Path(tmpdir) / "queue.jsonl"
            with open(malformed_file, "w", encoding="utf-8") as f:
                f.write("not json\n")
                f.write("{}\n")
                f.write('{"source": "ok"}\n')

            res = local_integrations.tokentracker_usage(
                queue_path=malformed_file, now=self.now
            )
            self.assertFalse(res["ok"])
            self.assertEqual(res["status"], "incompatible")
            self.assertEqual(res["error"], "tokentracker_malformed")
            self.assertEqual(res["malformed_rows"], 3)
            self.assertIn("tokentracker_malformed_rows", res["warnings"])

        # Stale test (> 24 hours ago)
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_file = Path(tmpdir) / "queue.jsonl"
            stale_record = {
                "source": "src-a",
                "model": "model-a",
                "hour_start": "2026-07-26T10:00:00+08:00",  # > 24 hours before now (2026-07-28 12:00:00)
                "total_tokens": 100,
                "conversation_count": 1,
            }
            with open(stale_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(stale_record) + "\n")

            res = local_integrations.tokentracker_usage(
                queue_path=stale_file, now=self.now
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["status"], "stale")
            self.assertTrue(res["is_stale"])
            self.assertFalse(res["is_live"])

    def test_extra_fields_ignored_malicious_source_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_file = Path(tmpdir) / "queue.jsonl"
            records = [
                # Record with extra fields: prompt, response, path, session, secret_key
                {
                    "source": "src-valid",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 100,
                    "conversation_count": 1,
                    "prompt": "secret prompt info",
                    "response": "secret response info",
                    "path": "/sensitive/path",
                    "session": "secret_session_id",
                    "secret_key": "api_key_12345",
                },
                # Malicious sources with paths or control characters
                {
                    "source": "../etc/passwd",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 100,
                    "conversation_count": 1,
                },
                {
                    "source": "src\x00bad",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 100,
                    "conversation_count": 1,
                },
                {
                    "source": "/absolute/path",
                    "model": "model-a",
                    "hour_start": "2026-07-28T11:00:00+08:00",
                    "total_tokens": 100,
                    "conversation_count": 1,
                },
            ]

            with open(queue_file, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            res = local_integrations.tokentracker_usage(
                queue_path=queue_file, now=self.now
            )

            self.assertTrue(res["ok"])
            # 3 malicious sources skipped
            self.assertEqual(res["malformed_rows"], 3)
            # Only fixed warning added
            self.assertEqual(res["warnings"], ["tokentracker_malformed_rows"])

            # Verify output dictionary keys and values do not contain extra fields or secrets
            res_str = json.dumps(res)
            self.assertNotIn("prompt", res_str)
            self.assertNotIn("response", res_str)
            self.assertNotIn("path", res_str)
            self.assertNotIn("session", res_str)
            self.assertNotIn("secret_key", res_str)
            self.assertNotIn("api_key_12345", res_str)
            self.assertNotIn("secret prompt info", res_str)

    def test_oversized_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            queue_file = Path(tmpdir) / "queue.jsonl"
            with open(queue_file, "w", encoding="utf-8") as f:
                f.write("a" * 100)

            # Patch MAX_QUEUE_FILE_SIZE to a small value (e.g. 50 bytes)
            with patch("nexstatus.local_integrations.MAX_QUEUE_FILE_SIZE", 50):
                res = local_integrations.tokentracker_usage(
                    queue_path=queue_file, now=self.now
                )
                self.assertFalse(res["ok"])
                self.assertEqual(res["status"], "incompatible")
                self.assertEqual(res["error"], "tokentracker_oversized")

    def test_duck_typed_path_oversized_growth(self):
        class DummyStatInfo:
            st_size = 10

        class DuckPath:
            def __init__(self, target_path: Path):
                self._target_path = target_path

            def exists(self) -> bool:
                return True

            def is_file(self) -> bool:
                return True

            def stat(self):
                return DummyStatInfo()

            def __fspath__(self) -> str:
                return str(self._target_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            real_file = Path(tmpdir) / "queue.jsonl"
            with open(real_file, "w", encoding="utf-8") as f:
                f.write("a" * 100)

            duck_path = DuckPath(real_file)
            with patch("nexstatus.local_integrations.MAX_QUEUE_FILE_SIZE", 50):
                res = local_integrations.tokentracker_usage(
                    queue_path=duck_path, now=self.now
                )
                self.assertFalse(res["ok"])
                self.assertEqual(res["status"], "incompatible")
                self.assertEqual(res["error"], "tokentracker_oversized")


if __name__ == "__main__":
    unittest.main()
