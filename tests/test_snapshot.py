from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexstatus import collector


def provider(ok: bool = True, **values: object) -> dict[str, object]:
    return {"ok": ok, **values}


class SnapshotContractTests(unittest.TestCase):
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
                "collect_ledger_summary",
                return_value={"schema_version": 2, "ok": True, "status": "live"},
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
        for name in ("host", "claude", "codex", "opencode_go", "grok", "antigravity"):
            self.assertIn(name, snapshot)
        self.assertIn("generated_at", snapshot)
        # Menu chips use 5h when present: C20% G30%
        self.assertIn("C20%", snapshot["title"])
        self.assertIn("G30%", snapshot["title"])

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
        patches = self.base_patches()[:-1]
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
