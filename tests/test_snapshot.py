from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from nexstatus import collector


def provider(ok: bool = True, **values: object) -> dict[str, object]:
    return {"ok": ok, **values}


class SnapshotContractTests(unittest.TestCase):
    def test_resolve_grok_monthly_pool_prefers_api(self) -> None:
        pool = collector._resolve_grok_monthly_pool(15000.0)
        self.assertFalse(pool["limit_missing"])
        self.assertEqual(pool["limit_source"], "api")
        self.assertEqual(pool["monthly_limit"], 15000.0)
        self.assertEqual(pool["monthly_limit_api"], 15000.0)

    def test_resolve_grok_monthly_pool_history_then_default(self) -> None:
        """API limit=0 → last non-zero history; empty history → plan default."""
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "h.jsonl"
            hist.write_text(
                "\n".join([
                    json.dumps({"ts": "2026-08-01T00:00:00+00:00", "used": 100.0, "monthly_limit": 15000.0}),
                    json.dumps({"ts": "2026-08-11T00:00:00+00:00", "used": 175.0, "monthly_limit": 0.0}),
                ]) + "\n",
                encoding="utf-8",
            )
            pool = collector._resolve_grok_monthly_pool(0.0, history_path=hist)
            self.assertTrue(pool["limit_missing"])
            self.assertEqual(pool["limit_source"], "history_last_nonzero")
            self.assertEqual(pool["monthly_limit"], 15000.0)
            self.assertEqual(pool["monthly_limit_api"], 0.0)
            self.assertEqual(collector._grok_used_pct(175.0, pool["monthly_limit"]), 1)

            empty = Path(tmp) / "empty.jsonl"
            empty.write_text("", encoding="utf-8")
            pool2 = collector._resolve_grok_monthly_pool(0.0, history_path=empty)
            self.assertTrue(pool2["limit_missing"])
            self.assertEqual(pool2["limit_source"], "plan_default")
            self.assertEqual(pool2["monthly_limit"], collector.GROK_DEFAULT_MONTHLY_LIMIT)

    def test_grok_weekly_usage_extracts_pool_reset_and_product_breakdown(self) -> None:
        result = collector._grok_weekly_usage({
            "weeklyUsage": {
                "usedPercent": 42,
                "resetsAt": "2026-07-18T04:00:00Z",
                "breakdown": {"chat": 20, "build": {"usedPercent": 22}, "private": 99},
            }
        })
        self.assertTrue(result["weekly_available"])
        self.assertEqual(result["weekly_used_pct"], 42)
        self.assertEqual(result["weekly_reset_at"], "2026-07-18T04:00:00Z")
        self.assertEqual(result["weekly_breakdown"], {"chat": 20, "build": 22})

    def test_grok_chat_gate_detects_spending_limit_block(self) -> None:
        """Enforcement 403 spending-limit must surface as chat_gate=blocked."""
        body = json.dumps({
            "code": "personal-team-blocked:spending-limit",
            "error": "You have run out of credits or need a Grok subscription.",
        }).encode()

        err = urllib.error.HTTPError(
            url=collector.GROK_MODELS_URL,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )
        err.read = lambda: body  # type: ignore[method-assign]

        with mock.patch.object(urllib.request, "urlopen", side_effect=err):
            gate = collector._grok_chat_gate("tok-test")
        self.assertEqual(gate["chat_gate"], "blocked")
        self.assertIs(gate["chat_ok"], False)
        self.assertIn("spending-limit", gate["block_code"] or "")

    def test_annotate_flags_false_available_when_billing_has_room(self) -> None:
        """Billing 0/15000 + chat blocked → 帳務鎖 / false_available."""
        result = {
            "ok": True,
            "used": 0.0,
            "monthly_limit": 15000.0,
            "used_pct": 0,
        }
        with mock.patch.object(
            collector,
            "_grok_chat_gate",
            return_value={
                "chat_ok": False,
                "chat_gate": "blocked",
                "block_code": "personal-team-blocked:spending-limit",
                "block_message": "run out of credits",
                "http_status": 403,
            },
        ):
            out = collector._annotate_grok_enforcement(result, token="tok")
        self.assertIs(out["false_available"], True)
        self.assertIs(out["effective_available"], False)
        self.assertEqual(out["status_label"], "帳務鎖")
        self.assertEqual(out["chat_gate"], "blocked")

    def test_annotate_billing_exhausted_skips_network_probe(self) -> None:
        result = {"ok": True, "used": 16120.0, "monthly_limit": 15000.0, "used_pct": 100}
        with mock.patch.object(collector, "_grok_chat_gate") as probe:
            out = collector._annotate_grok_enforcement(result, token="tok")
        probe.assert_not_called()
        self.assertEqual(out["status_label"], "額度盡")
        self.assertEqual(out["chat_gate"], "billing_exhausted")
        self.assertIs(out["false_available"], False)

    def test_grok_weekly_estimate_uses_seat_history_not_shared_default(self) -> None:
        """Regression: multi-seat weekly bars must not share G1's baseline.

        Before the fix, seat collectors fell back to GROK_HISTORY (primary
        account). A high-used seat then showed inflated weekly burn
        (current_seat - baseline_g1), while a lower-used seat floored to 0.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seat1_hist = root / "hist-1.jsonl"
            seat2_hist = root / "hist-2.jsonl"
            # Week start is Monday 00:00 UTC; use timestamps clearly before/after.
            # Use fixed "now" via history rows relative to real week bounds is
            # brittle — instead write a baseline at a far-past ts so it is
            # always <= week_start, then compute delta from current_used.
            seat1_hist.write_text(
                json.dumps({
                    "ts": "2020-01-01T00:00:00+00:00",
                    "ts_unix": 1577836800,
                    "used": 9000.0,
                    "monthly_limit": 15000.0,
                }) + "\n",
                encoding="utf-8",
            )
            seat2_hist.write_text(
                json.dumps({
                    "ts": "2020-01-01T00:00:00+00:00",
                    "ts_unix": 1577836800,
                    "used": 12000.0,
                    "monthly_limit": 15000.0,
                }) + "\n",
                encoding="utf-8",
            )
            cfg_seat2 = {
                "used": 15000.0,
                "monthlyLimit": 15000.0,
                "billingPeriodStart": "2026-07-01T00:00:00+00:00",
                "billingPeriodEnd": "2026-08-01T00:00:00+00:00",
            }
            # Wrong (shared) path would use seat1 baseline → weekly=6000.
            wrong = collector._grok_weekly_usage(cfg_seat2, history_path=seat1_hist)
            right = collector._grok_weekly_usage(cfg_seat2, history_path=seat2_hist)
            self.assertEqual(wrong["weekly_source"], "billing_snapshot_delta")
            self.assertEqual(right["weekly_source"], "billing_snapshot_delta")
            self.assertAlmostEqual(wrong["weekly_used"], 6000.0)
            self.assertAlmostEqual(right["weekly_used"], 3000.0)
            self.assertNotEqual(wrong["weekly_used"], right["weekly_used"])

            # Seat path must thread history_path into _grok_weekly_usage.
            with mock.patch.object(
                collector,
                "_grok_weekly_usage",
                wraps=collector._grok_weekly_usage,
            ) as wrapped:
                # Simulate the seat billing tail without network.
                weekly = collector._grok_weekly_usage(cfg_seat2, history_path=seat2_hist)
                self.assertAlmostEqual(weekly["weekly_used"], 3000.0)
                # Also assert explicit call signature for seat isolation.
                weekly2 = collector._grok_weekly_from_history(
                    current_used=15000.0,
                    monthly_limit=15000.0,
                    period_start="2026-07-01T00:00:00+00:00",
                    period_end="2026-08-01T00:00:00+00:00",
                    history_path=seat2_hist,
                )
                self.assertAlmostEqual(weekly2["weekly_used"], 3000.0)
                _ = wrapped  # silence unused if wraps not invoked elsewhere

    def test_openrouter_history_requires_real_baselines(self) -> None:
        now = 1_787_500_800.0  # 2026-08-23 12:00 UTC
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "openrouter-history.jsonl"
            history.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in (
                        {
                            "seat": "dsh",
                            "ts_unix": now - 4 * 3600,
                            "total_usage": 1.0,
                        },
                        {
                            "seat": "dsh",
                            "ts_unix": now - 8 * 86400,
                            "total_usage": 0.0,
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            measured = collector._openrouter_usage_trends(
                "dsh", 2.0, history_path=history, now_ts=now
            )
            self.assertEqual(measured["delta_today"], 1.0)
            self.assertEqual(measured["delta_7d"], 2.0)
            self.assertAlmostEqual(float(measured["daily_avg"]), 2.0 / 7.0)

            # Negative control: current usage alone is not a trend baseline.
            empty = collector._openrouter_usage_trends(
                "global", 246.0, history_path=history, now_ts=now
            )
            self.assertIsNone(empty["delta_today"])
            self.assertIsNone(empty["delta_7d"])
            self.assertIsNone(empty["daily_avg"])

    def test_openrouter_30_day_baseline_is_not_a_7_day_trend(self) -> None:
        now = 1_787_500_800.0
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / "openrouter-history.jsonl"
            history.write_text(
                json.dumps({
                    "seat": "dsh",
                    "ts_unix": now - 30 * 86400,
                    "total_usage": 1.0,
                }) + "\n",
                encoding="utf-8",
            )
            result = collector._openrouter_usage_trends(
                "dsh", 2.0, history_path=history, now_ts=now
            )
            self.assertIsNone(result["delta_7d"])
            self.assertIsNone(result["daily_avg"])

    def test_openrouter_invalid_environment_key_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            history = cache / "openrouter-history.jsonl"
            key_file = root / "dsh.env"
            file_key = "sk-or-v1-" + ("f" * 32)
            key_file.write_text(f"DEEPSEEK_API_KEY={file_key}\n", encoding="utf-8")
            seats = ({"seat": "dsh", "path": key_file, "variable": "DEEPSEEK_API_KEY"},)
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                OPENROUTER_CACHE=cache / "openrouter.json",
                OPENROUTER_HISTORY=history,
                OPENROUTER_SEATS=seats,
                KNOWN_CACHE_FILES=(cache / "openrouter.json",),
            ), mock.patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "old garbage key with spaces"},
            ), mock.patch.object(
                collector,
                "_openrouter_fetch_json",
                side_effect=[
                    {"data": {"total_credits": 50, "total_usage": 1.0}},
                    {"data": {"label": "sk-or-v1-red...acted", "limit": 20, "limit_remaining": 19, "usage_monthly": 1.0}},
                ],
            ):
                result = collector.openrouter_usage(force=True)

            self.assertTrue(result["dsh"]["ok"])
            self.assertEqual(result["dsh"]["key_source"], "file")
            self.assertNotIn(file_key, json.dumps(result))

    def test_openrouter_revoked_environment_key_retries_with_file_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            history = cache / "openrouter-history.jsonl"
            key_file = root / "global.env"
            env_key = "sk-or-v1-" + ("e" * 32)
            file_key = "sk-or-v1-" + ("f" * 32)
            key_file.write_text(f"OPENROUTER_API_KEY={file_key}\n", encoding="utf-8")
            seats = ({"seat": "global", "path": key_file, "variable": "OPENROUTER_API_KEY"},)
            fetch = mock.Mock(
                side_effect=[
                    RuntimeError("HTTP 401"),
                    {"data": {"total_credits": 120, "total_usage": 30.0}},
                    {"data": {"label": "sk-or-v1-file...safe", "limit": 40, "limit_remaining": 10, "usage_monthly": 30.0}},
                ]
            )
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                OPENROUTER_CACHE=cache / "openrouter.json",
                OPENROUTER_HISTORY=history,
                OPENROUTER_SEATS=seats,
                KNOWN_CACHE_FILES=(cache / "openrouter.json",),
            ), mock.patch.dict(
                os.environ,
                {"OPENROUTER_API_KEY": env_key},
            ), mock.patch.object(
                collector,
                "_openrouter_fetch_json",
                fetch,
            ):
                result = collector.openrouter_usage(force=True)

            self.assertTrue(result["global"]["ok"])
            self.assertEqual(result["global"]["key_source"], "fallback")
            self.assertEqual(result["global"]["account_credits"], 120)
            self.assertEqual(result["global"]["used_pct"], 25)
            self.assertEqual(fetch.call_args_list[0].args[1], env_key)
            self.assertEqual(fetch.call_args_list[1].args[1], file_key)
            self.assertEqual(fetch.call_args_list[2].args[1], file_key)
            self.assertNotIn(env_key, json.dumps(result))

    def test_openrouter_ttl_second_read_makes_no_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            history = cache / "openrouter-history.jsonl"
            seats = (
                {"seat": "dsh", "path": root / "dsh.env", "variable": "DEEPSEEK_API_KEY"},
                {"seat": "global", "path": root / "global.env", "variable": "OPENROUTER_API_KEY"},
            )
            for seat in seats:
                seat["path"].write_text(
                    f'{seat["variable"]}=sk-or-v1-{"a" * 32}\n', encoding="utf-8"
                )
            responses = [
                {"data": {"total_credits": 50, "total_usage": 1.0}},
                {"data": {"label": "sk-or-v1-dsh...", "limit": 20, "limit_remaining": 19, "usage_monthly": 1.0}},
                {"data": {"total_credits": 100, "total_usage": 2.0}},
                {"data": {"label": "sk-or-v1-global...", "limit": None, "limit_remaining": None, "usage_monthly": 2.0}},
            ]
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                OPENROUTER_CACHE=cache / "openrouter.json",
                OPENROUTER_HISTORY=history,
                OPENROUTER_SEATS=seats,
                KNOWN_CACHE_FILES=(cache / "openrouter.json",),
            ), mock.patch.object(
                collector,
                "_openrouter_fetch_json",
                side_effect=responses,
            ) as fetch:
                first = collector.openrouter_usage(force=True)
                fetch.reset_mock()
                second = collector.openrouter_usage()

            self.assertEqual(fetch.call_count, 0)
            self.assertEqual(second, first)

    def test_openrouter_requests_have_per_seat_deadlines_inside_total_budget(self) -> None:
        seats = (
            {"seat": "dsh", "path": Path("/tmp/dsh.env"), "variable": "DEEPSEEK_API_KEY"},
            {"seat": "global", "path": Path("/tmp/global.env"), "variable": "OPENROUTER_API_KEY"},
        )
        responses = [
            {"data": {"total_credits": 50, "total_usage": 1.0}},
            {"data": {"label": "sk-or-v1-dsh...", "limit": 20, "limit_remaining": 19, "usage_monthly": 1.0}},
            {"data": {"total_credits": 100, "total_usage": 2.0}},
            {"data": {"label": "sk-or-v1-global...", "limit": None, "limit_remaining": None, "usage_monthly": 2.0}},
        ]
        fetch = mock.Mock(side_effect=responses)
        with mock.patch.multiple(
            collector,
            OPENROUTER_SEATS=seats,
            _openrouter_key=mock.Mock(return_value="sk-or-v1-" + ("a" * 32)),
            _openrouter_fetch_json=fetch,
            _write_cache_json=mock.Mock(),
        ), mock.patch.object(
            collector.time,
            "monotonic",
            side_effect=[100.0, 100.0, 100.5],
        ):
            collector.openrouter_usage(force=True)

        calls = fetch.call_args_list
        self.assertEqual(len(calls), 4)
        deadlines = [call.kwargs["deadline"] for call in calls]
        self.assertEqual(deadlines[:2], [101.5, 101.5])
        self.assertEqual(deadlines[2:], [102.0, 102.0])
        self.assertLessEqual(max(deadlines) - 100.0, collector.OPENROUTER_TOTAL_DEADLINE)

    def test_openrouter_requests_never_exceed_shared_collector_deadline(self) -> None:
        seats = (
            {"seat": "dsh", "path": Path("/tmp/dsh.env"), "variable": "DEEPSEEK_API_KEY"},
            {"seat": "global", "path": Path("/tmp/global.env"), "variable": "OPENROUTER_API_KEY"},
        )
        responses = [
            {"data": {"total_credits": 50, "total_usage": 1.0}},
            {"data": {"label": "sk-or-v1-dsh...", "limit": 20, "limit_remaining": 19, "usage_monthly": 1.0}},
            {"data": {"total_credits": 100, "total_usage": 2.0}},
            {"data": {"label": "sk-or-v1-global...", "limit": None, "limit_remaining": None, "usage_monthly": 2.0}},
        ]
        fetch = mock.Mock(side_effect=responses)
        collector_start = 1000.0
        shared_deadline = collector_start + collector.COLLECTOR_WATCHDOG_BUDGET_SECONDS
        openrouter_call_time = collector_start + 7.0
        with mock.patch.multiple(
            collector,
            OPENROUTER_SEATS=seats,
            _openrouter_key=mock.Mock(return_value="sk-or-v1-" + ("a" * 32)),
            _openrouter_fetch_json=fetch,
            _write_cache_json=mock.Mock(),
            _append_openrouter_history=mock.Mock(),
        ), mock.patch.object(
            collector.time,
            "monotonic",
            side_effect=[openrouter_call_time, openrouter_call_time, openrouter_call_time + 0.05],
        ):
            collector.openrouter_usage(force=True, deadline=shared_deadline)

        deadlines = [call.kwargs["deadline"] for call in fetch.call_args_list]
        self.assertEqual(len(deadlines), 4)
        for request_deadline in deadlines:
            self.assertLessEqual(request_deadline, shared_deadline)
        self.assertLess(
            max(deadlines) - openrouter_call_time,
            collector.OPENROUTER_SEAT_DEADLINE,
        )

    def test_openrouter_schema_keeps_null_key_limits_and_isolates_seat_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            history = cache / "openrouter-history.jsonl"
            openrouter_cache = cache / "openrouter.json"
            seats = (
                {"seat": "dsh", "path": root / "dsh.env", "variable": "DEEPSEEK_API_KEY"},
                {"seat": "global", "path": root / "global.env", "variable": "OPENROUTER_API_KEY"},
            )
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                OPENROUTER_CACHE=openrouter_cache,
                OPENROUTER_HISTORY=history,
                OPENROUTER_SEATS=seats,
                KNOWN_CACHE_FILES=(openrouter_cache,),
            ), mock.patch.object(
                collector,
                "_openrouter_key",
                side_effect=lambda seat: "test-key-" + str(seat["seat"]),
            ), mock.patch.object(
                collector,
                "_openrouter_fetch_json",
                side_effect=[
                    {"data": {"total_credits": 50, "total_usage": 0.4527}},
                    {"data": {"label": "sk-or-v1-cef...1b7", "limit": 20, "limit_remaining": 19.55, "usage_monthly": 0.4542}},
                    {"data": {"total_credits": 246, "total_usage": 231.30}},
                    RuntimeError("HTTP 403"),
                ],
            ):
                result = collector.openrouter_usage(force=True)

            self.assertTrue(result["dsh"]["ok"])
            self.assertEqual(result["dsh"]["label"], "sk-or-v1-cef...1b7")
            self.assertEqual(result["dsh"]["used_pct"], 1)
            for field in (
                "ok", "seat", "key_source", "label", "account_credits", "account_usage",
                "account_remaining", "key_limit", "key_limit_remaining",
                "key_usage_monthly", "used_pct", "delta_today", "delta_7d",
                "daily_avg", "_fetched_at", "_fetched_at_ts",
            ):
                self.assertIn(field, result["dsh"])
            self.assertTrue(result["global"]["ok"] is False)
            self.assertEqual(result["global"]["error"], "HTTP 403")
            self.assertIsNone(result["global"]["key_limit"])
            self.assertNotIn("test-key", json.dumps(result))

            # A successful null-limit response is valid and must not format or
            # calculate None as if it were a number.
            with mock.patch.object(collector, "_openrouter_key", return_value="test-key"), mock.patch.object(
                collector,
                "_openrouter_fetch_json",
                side_effect=[
                    {"data": {"total_credits": 246, "total_usage": 231.30}},
                    {"data": {"label": "sk-or...safe", "limit": None, "limit_remaining": None, "usage_monthly": 2.0}},
                ],
            ):
                null_limit = collector.openrouter_usage(force=True)
            self.assertTrue(null_limit["m5"]["ok"])
            self.assertIsNone(null_limit["m5"]["key_limit"])
            self.assertIsNone(null_limit["m5"]["key_limit_remaining"])

    def test_build_snapshot_passes_shared_deadline_to_openrouter(self) -> None:
        patches = self.base_patches()[:-1]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch.object(
            collector,
            "openrouter_usage",
            return_value={
                "dsh": {"ok": True, "seat": "dsh", "used_pct": 1},
                "global": {"ok": True, "seat": "global", "used_pct": 94},
            },
        ) as mocked:
            collector.build_snapshot()

        self.assertIn("deadline", mocked.call_args.kwargs)
        self.assertIsInstance(mocked.call_args.kwargs["deadline"], float)

    def base_patches(self) -> list[mock._patch]:
        return [
            mock.patch.object(collector, "host_metrics", return_value=provider(mem_pct=10, swap_mb=0)),
            mock.patch.object(collector, "claude_usage", return_value=provider(five_hour_pct=20)),
            mock.patch.object(collector, "codex_usage", return_value=provider(five_hour_pct=30)),
            mock.patch.object(collector, "grok_usage", return_value=provider(used_pct=40)),
            mock.patch.object(collector, "opencode_go_usage", return_value=provider(used_pct=50)),
            mock.patch.object(collector, "antigravity_usage", return_value=provider(used_pct=60)),
            mock.patch.object(
                collector,
                "tokentracker_usage",
                return_value=provider(
                    status="live",
                    today={"tokens": 10, "conversations": 1},
                    rolling_7d={"tokens": 20, "conversations": 2},
                    rolling_30d={"tokens": 30, "conversations": 3},
                    sources_30d=[],
                ),
            ),
            mock.patch.object(
                collector,
                "rag_status",
                return_value=provider(
                    status="online",
                    inventory_status="live",
                    documents={"total": 2, "completed": 2, "queued": 0, "processing": 0, "failed": 0},
                ),
            ),
            mock.patch.object(
                collector,
                "collect_ledger_summary",
                return_value={"schema_version": 2, "ok": True, "status": "live"},
            ),
            mock.patch.object(
                collector,
                "openrouter_usage",
                return_value={
                    "dsh": {"ok": True, "seat": "dsh", "used_pct": 1},
                    "global": {"ok": True, "seat": "global", "used_pct": 94},
                },
            ),
        ]

    def test_snapshot_contains_versioned_ledger_and_existing_sections(self) -> None:
        patches = self.base_patches()
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        snapshot = collector.build_snapshot()
        self.assertEqual(snapshot["schema_version"], 2)
        self.assertEqual(snapshot["ledger"]["schema_version"], 2)
        self.assertEqual(snapshot["ledger"]["status"], "live")
        for name in ("host", "claude", "codex", "opencode_go", "grok", "grok_seats", "openrouter", "antigravity", "tokentracker", "rag"):
            self.assertIn(name, snapshot)
        self.assertEqual(snapshot["openrouter"]["global"]["used_pct"], 94)
        self.assertEqual(snapshot["tokentracker"]["status"], "live")
        self.assertEqual(snapshot["rag"]["status"], "online")
        self.assertEqual(snapshot["rag"]["documents"]["total"], 2)
        self.assertIn("generated_at", snapshot)
        # Menu chips use 5h when present: C20% G30%
        self.assertIn("C20%", snapshot["title"])
        self.assertIn("G30%", snapshot["title"])

    def test_tokentracker_and_rag_exceptions_handled_gracefully(self) -> None:
        patches = self.base_patches()
        # Find index of tokentracker_usage and rag_status patches by object name
        patches[6] = mock.patch.object(collector, "tokentracker_usage", side_effect=RuntimeError("private tokentracker secret"))
        patches[7] = mock.patch.object(collector, "rag_status", side_effect=RuntimeError("private rag secret"))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        snapshot = collector.build_snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["tokentracker"], {"ok": False, "error": "tokentracker_unavailable"})
        self.assertEqual(snapshot["rag"], {"ok": False, "error": "rag_unavailable"})
        snapshot_json = json.dumps(snapshot)
        self.assertNotIn("private tokentracker secret", snapshot_json)
        self.assertNotIn("private rag secret", snapshot_json)

    def test_menu_title_falls_back_to_seven_day_when_five_hour_missing(self) -> None:
        patches = self.base_patches()
        patches[2] = mock.patch.object(
            collector,
            "codex_usage",
            return_value=provider(five_hour_pct=None, seven_day_pct=2, plan_type="pro"),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        snapshot = collector.build_snapshot()
        self.assertIsNone(snapshot["codex"]["five_hour_pct"])
        self.assertEqual(snapshot["codex"]["seven_day_pct"], 2)
        # G should show 7d 2% instead of blank G—%
        self.assertIn("G2%", snapshot["title"])
        self.assertIn("G2%", snapshot["title_full"])
        self.assertNotIn("G—%", snapshot["title"])

    def test_menu_quota_pct_prefers_five_hour(self) -> None:
        self.assertEqual(
            collector._menu_quota_pct({"ok": True, "five_hour_pct": 12, "seven_day_pct": 40}),
            12,
        )
        self.assertEqual(
            collector._menu_quota_pct({"ok": True, "five_hour_pct": None, "seven_day_pct": 7}),
            7,
        )
        self.assertIsNone(collector._menu_quota_pct({"ok": False, "seven_day_pct": 7}))
        self.assertIsNone(collector._menu_quota_pct({"ok": True}))

    def test_proc_short_name_strips_paths_and_helpers(self) -> None:
        self.assertEqual(
            collector._proc_short_name("/Users/ray/.local/ollama-runtime/llama-server --port 11434"),
            "llama-server",
        )
        self.assertEqual(
            collector._proc_short_name("Google Chrome Helper (Renderer)"),
            "Google Chrome",
        )
        self.assertEqual(
            collector._proc_short_name(
                "/Applications/Google Chrome.app/Contents/Frameworks/"
                "Google Chrome Framework.framework/Versions/149.0.7827.198/Helpers/"
                "Google Chrome Helper (Renderer).app/Contents/MacOS/"
                "Google Chrome Helper (Renderer)"
            ),
            "Google Chrome",
        )
        self.assertEqual(collector._proc_family("llama-server"), "本機模型")
        self.assertEqual(collector._proc_family("claude"), "AI CLI / 訂閱")
        self.assertEqual(collector._proc_family("Google Chrome"), "瀏覽器")

    def test_host_process_snapshot_shape(self) -> None:
        snap = collector._host_process_snapshot(limit_cpu=3, limit_mem=3, limit_families=3)
        self.assertIn("top_cpu", snap)
        self.assertIn("top_mem", snap)
        self.assertIn("top_families", snap)
        for row in snap["top_cpu"] + snap["top_mem"]:
            self.assertNotIn("/", row["name"])
            self.assertIn("cpu_pct", row)
            self.assertIn("rss_mb", row)
            self.assertIn("family", row)

    def test_one_provider_exception_does_not_abort_snapshot(self) -> None:
        patches = self.base_patches()
        patches[3] = mock.patch.object(collector, "grok_usage", side_effect=RuntimeError("private"))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        snapshot = collector.build_snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["grok"], {"ok": False, "error": "grok_unavailable"})
        self.assertTrue(snapshot["claude"]["ok"])
        self.assertEqual(snapshot["ledger"]["status"], "live")

    def test_atomic_cache_writer_forces_owner_only_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            out = cache / "status.json"
            grok = cache / "grok-billing.json"
            go = cache / "opencode-go.json"
            agy = cache / "antigravity.json"
            known = (out, grok, go, agy)
            old_umask = os.umask(0o022)
            try:
                with mock.patch.multiple(
                    collector,
                    CACHE_DIR=cache,
                    OUT=out,
                    GROK_CACHE=grok,
                    GO_CACHE=go,
                    AGY_CACHE=agy,
                    KNOWN_CACHE_FILES=known,
                ):
                    collector._write_cache_json(out, {"ok": True})
                    self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
                    collector._write_cache_json(out, {"ok": False})
                    self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
                    self.assertEqual(json.loads(out.read_text()), {"ok": False})
                    self.assertFalse(list(cache.glob("*.tmp")))
            finally:
                os.umask(old_umask)

    def test_writer_rejects_unknown_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            unknown = Path(directory) / "other.json"
            with self.assertRaisesRegex(ValueError, "unsupported_cache_path"):
                collector._write_cache_json(unknown, {"ok": True})

    def test_snapshot_has_no_secret_material_or_private_source_paths(self) -> None:
        patches = self.base_patches()
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        encoded = json.dumps(collector.build_snapshot()).lower()
        for forbidden in (
            "authorization",
            "bearer ",
            "access_token",
            "refresh_token",
            "cookie",
            "/users/ray/.codex/sessions",
            "/users/ray/.claude",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_real_ledger_failure_shape_does_not_break_build(self) -> None:
        patches = self.base_patches()[:8]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch.object(collector, "COST_DB", Path("/definitely/missing.db")):
            snapshot = collector.build_snapshot()
        self.assertEqual(snapshot["ledger"]["status"], "missing")
        self.assertTrue(snapshot["claude"]["ok"])


class AntigravityHardeningTests(unittest.TestCase):
    def test_discovery_uses_same_user_exact_process_and_lsof_intersection(self) -> None:
        def fake_check_output(cmd, **_kwargs):  # type: ignore[no-untyped-def]
            binary = cmd[0]
            if binary.endswith("pgrep") and cmd[-1] == "agy" and "-x" in cmd:
                return "123\n"
            if binary.endswith("pgrep"):
                return ""
            if binary.endswith("ps") or binary == "/bin/ps":
                return f"{os.getuid()} agy /usr/local/bin/agy\n"
            if "lsof" in binary:
                return "agy 123 user 1u IPv4 0t0 TCP 127.0.0.1:57277 (LISTEN)\n"
            raise subprocess.SubprocessError("unexpected")

        with mock.patch.object(collector.subprocess, "check_output", side_effect=fake_check_output) as call:
            ports = collector._find_agy_listen_ports(collector.time.monotonic() + 3)
        self.assertEqual(ports, [57277])
        lsof_calls = [c.args[0] for c in call.call_args_list if "lsof" in c.args[0][0]]
        self.assertTrue(lsof_calls)
        self.assertIn("-a", lsof_calls[0])
        self.assertIn("-p", lsof_calls[0])

    def test_stale_cache_keeps_quota_when_agy_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            agy = cache / "antigravity.json"
            good = {
                "ok": True,
                "source": "agy-local",
                "plan": "Pro",
                "used_pct": 55,
                "session_used_pct": 55,
                "models": [],
                "_fetched_at_ts": collector._now() - 120,
            }
            agy.write_text(json.dumps(good), encoding="utf-8")
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                AGY_CACHE=agy,
                KNOWN_CACHE_FILES=(agy,),
            ), mock.patch.object(collector, "_find_agy_listen_ports", return_value=[]):
                result = collector.antigravity_usage(force=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["used_pct"], 55)
        self.assertTrue(result.get("stale"))
        self.assertEqual(result.get("source"), "agy-cache-stale")

    def test_non_finite_antigravity_values_degrade_to_unknown(self) -> None:
        body = {
            "userStatus": {
                "planStatus": {"planInfo": {"planName": "Test"}},
                "cascadeModelConfigData": {
                    "clientModelConfigs": [
                        {"label": "bad", "quotaInfo": {"remainingFraction": float("inf")}}
                    ]
                },
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            out = cache / "status.json"
            grok = cache / "grok-billing.json"
            go = cache / "opencode-go.json"
            agy = cache / "antigravity.json"
            with mock.patch.multiple(
                collector,
                CACHE_DIR=cache,
                OUT=out,
                GROK_CACHE=grok,
                GO_CACHE=go,
                AGY_CACHE=agy,
                KNOWN_CACHE_FILES=(out, grok, go, agy),
            ), mock.patch.object(collector, "_find_agy_listen_ports", return_value=[57277]), mock.patch.object(
                collector, "_probe_agy_user_status", return_value=body
            ):
                result = collector.antigravity_usage(force=True)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["models"][0]["remaining_fraction"])
        self.assertIsNone(result["models"][0]["used_pct"])
        self.assertNotIn("ports", result)
        self.assertNotIn("email", result)


if __name__ == "__main__":
    unittest.main()
