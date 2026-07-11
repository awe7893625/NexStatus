from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from nexstatus.ledger import collect_ledger_summary


COST_SCHEMA = """
CREATE TABLE cost_events (
  id INTEGER PRIMARY KEY,
  ts TEXT,
  task_id TEXT,
  agent TEXT,
  model TEXT,
  tier INTEGER,
  provider TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  cost_usd REAL,
  project TEXT,
  task_class TEXT,
  quota_source TEXT,
  shadow_cost_usd REAL,
  idempotency_key TEXT,
  machine TEXT,
  api_key_id TEXT,
  task_desc TEXT
);
CREATE TABLE fixed_subscription_costs (
  month TEXT NOT NULL,
  quota_source TEXT NOT NULL,
  label TEXT NOT NULL,
  monthly_cost_usd REAL,
  currency TEXT NOT NULL DEFAULT 'USD',
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (month, quota_source, label)
);
"""


class LedgerSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.db_path = Path(self.tempdir.name) / "ledger.db"
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(COST_SCHEMA)
            connection.commit()

    def insert_event(
        self,
        *,
        ts: str,
        quota: str | None,
        machine: str | None,
        input_tokens: int = 10,
        output_tokens: int = 2,
        cash: float = 0.0,
        shadow: float = 0.0,
        project: str | None = None,
        api_key_id: str | None = None,
        task_class: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO cost_events
                  (ts, quota_source, machine, project, api_key_id, task_class, provider, model,
                   input_tokens, output_tokens, cost_usd, shadow_cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (ts, quota, machine, project, api_key_id, task_class, provider, model,
                 input_tokens, output_tokens, cash, shadow),
            )
            connection.commit()

    def now(self) -> datetime:
        return datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("Asia/Taipei"))

    def test_normal_contract_conserves_group_totals_and_does_not_write(self) -> None:
        self.insert_event(
            ts="2026-06-30T16:00:00Z",
            quota="codex-plus-subscription",
            machine="M5",
            input_tokens=100,
            output_tokens=20,
            shadow=3.5,
        )
        self.insert_event(
            ts="2026-07-15T08:00:00",
            quota="nim-free-quota",
            machine="M4",
            input_tokens=50,
            output_tokens=5,
            shadow=1.25,
        )
        self.insert_event(
            ts="2026-07-16T00:00:00+08:00",
            quota="new-provider",
            machine=None,
            input_tokens=7,
            output_tokens=1,
            cash=0.25,
        )
        self.insert_event(
            ts="2026-06-30T15:59:59Z",
            quota="local-ollama",
            machine="M5",
            input_tokens=999,
        )
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()

        result = collect_ledger_summary(self.db_path, now=self.now())

        after = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertTrue(result["ok"])
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["period"], "2026-07")
        self.assertEqual(result["totals"]["events"], 3)
        self.assertEqual(result["totals"]["input_tokens"], 157)
        self.assertEqual(result["totals"]["output_tokens"], 26)
        self.assertEqual(result["totals"]["cash_metered_usd"], 0.25)
        self.assertEqual(result["totals"]["shadow_value_usd"], 4.75)
        expected_tokens = 183
        for key in ("classes", "machines", "sources"):
            self.assertEqual(sum(item["events"] for item in result[key]), 3)
            self.assertEqual(sum(item["tokens"] for item in result[key]), expected_tokens)
        self.assertTrue(all("class" in item for item in result["sources"]))
        self.assertEqual(result["quality"]["unknown_quota_events"], 1)
        self.assertEqual(result["quality"]["missing_machine_events"], 1)
        self.assertIn("naive_timestamps_assumed_local", result["quality"]["warnings"])
        self.assertEqual(result["windows"]["today"]["tokens"], 55)
        self.assertEqual(result["windows"]["30d"]["tokens"], 1176)

    def test_token_windows_group_platform_local_compute_and_projects(self) -> None:
        self.insert_event(
            ts="2026-07-15T10:00:00+08:00", quota="local-mlx", machine="M5",
            input_tokens=80, output_tokens=20, project="NexStatus",
        )
        self.insert_event(
            ts="2026-07-13T10:00:00+08:00", quota="codex-plus-subscription", machine="M4",
            input_tokens=180, output_tokens=20, project="NexStatus",
        )
        self.insert_event(
            ts="2026-06-20T10:00:00+08:00", quota="nim-free-quota", machine="M5",
            input_tokens=270, output_tokens=30, project="Research",
        )

        result = collect_ledger_summary(self.db_path, now=self.now())

        self.assertEqual(result["windows"]["today"]["tokens"], 100)
        self.assertEqual(result["windows"]["3d"]["tokens"], 300)
        self.assertEqual(result["windows"]["7d"]["tokens"], 300)
        self.assertEqual(result["windows"]["30d"]["tokens"], 600)
        self.assertEqual(result["windows"]["7d"]["local_tokens"], 100)
        self.assertEqual(result["windows"]["7d"]["local_share_pct"], 33.3)
        self.assertEqual(result["windows"]["7d"]["share_of_30d_pct"], 50.0)
        self.assertEqual(result["windows"]["7d"]["sources"][0]["id"], "codex-plus-subscription")
        self.assertEqual(result["windows"]["7d"]["projects"][0]["id"], "NexStatus")
        self.assertEqual(result["projects"][0]["tokens"], 300)

    def test_compute_capacity_anonymizes_free_keys_and_conserves_totals(self) -> None:
        self.insert_event(
            ts="2026-07-14T10:00:00+08:00", quota="nim-free-quota", machine="M5",
            api_key_id="secret-key-material-a", task_class="coding", provider="nim",
            model="qwen", project="NexStatus", input_tokens=90, output_tokens=10,
        )
        self.insert_event(
            ts="2026-07-13T10:00:00+08:00", quota="cerebras-free", machine="M5",
            api_key_id="secret-key-material-b", task_class="research", provider="cerebras",
            model="qwen", project="Research", input_tokens=180, output_tokens=20,
        )
        self.insert_event(
            ts="2026-07-12T10:00:00+08:00", quota="nim-free-quota", machine="M5",
            api_key_id=None, project="Unattributed", input_tokens=45, output_tokens=5,
        )
        self.insert_event(
            ts="2026-07-11T10:00:00+08:00", quota="local-ollama", machine="M5",
            project="Local", input_tokens=135, output_tokens=15,
        )

        result = collect_ledger_summary(self.db_path, now=self.now())
        compute = result["compute_capacity"]

        self.assertEqual(compute["free_cloud"]["tokens"], 350)
        self.assertEqual(compute["free_cloud"]["api_key_count"], 2)
        self.assertEqual(compute["free_cloud"]["unattributed_tokens"], 50)
        self.assertEqual(compute["local_compute"]["tokens"], 150)
        self.assertEqual(compute["combined"]["tokens"], 500)
        self.assertEqual(compute["free_cloud"]["share_pct"], 70.0)
        self.assertEqual(compute["local_compute"]["share_pct"], 30.0)
        encoded = json.dumps(compute)
        self.assertNotIn("secret-key-material", encoded)
        self.assertEqual(compute["free_cloud"]["credential_slot_count"], 2)
        self.assertEqual(compute["free_cloud"]["coverage_score"], 66.7)
        self.assertEqual(compute["free_cloud"]["confidence_state"], "partial")
        self.assertEqual([item["id"] for item in compute["free_cloud"]["keys"]], ["Slot 01", "Slot 02"])
        self.assertNotRegex(encoded, r"[a-f0-9]{32,}")
        self.assertIn("coding", encoded)
        self.assertIn("NexStatus", encoded)

    def test_missing_database_uses_fixed_redacted_error(self) -> None:
        missing = Path(self.tempdir.name) / "private-name.db"
        result = collect_ledger_summary(missing, now=self.now())
        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["totals"])
        encoded = json.dumps(result)
        self.assertNotIn(str(missing), encoded)
        self.assertNotIn("private-name", encoded)

    def test_missing_required_table_is_incompatible(self) -> None:
        empty_path = Path(self.tempdir.name) / "empty.db"
        with closing(sqlite3.connect(empty_path)):
            pass
        result = collect_ledger_summary(empty_path, now=self.now())
        self.assertEqual(result["status"], "incompatible")
        self.assertEqual(result["quality"]["warnings"], ["cost_events_missing"])

    def test_locked_database_is_busy_without_exception_text(self) -> None:
        with mock.patch(
            "nexstatus.ledger.sqlite3.connect",
            side_effect=sqlite3.OperationalError("database is locked: /private/path"),
        ):
            result = collect_ledger_summary(self.db_path, now=self.now())
        self.assertEqual(result["status"], "busy")
        self.assertNotIn("private", json.dumps(result))

    def test_fixed_commitment_requires_all_active_rows_to_be_verified(self) -> None:
        self.insert_event(
            ts="2026-07-10T10:00:00+08:00",
            quota="claude-code-oauth-quota",
            machine="M5",
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO fixed_subscription_costs
                  (month, quota_source, label, monthly_cost_usd, active, updated_at)
                VALUES ('2026-07', 'codex-plus-subscription', 'Codex', 20, 1, '2026-07-01')
                """
            )
            connection.execute(
                """
                INSERT INTO fixed_subscription_costs
                  (month, quota_source, label, monthly_cost_usd, active, updated_at)
                VALUES ('2026-07', 'claude-code-oauth-quota', 'Claude', NULL, 1, '2026-07-01')
                """
            )
            connection.commit()
        result = collect_ledger_summary(self.db_path, now=self.now())
        self.assertFalse(result["totals"]["fixed_verified"])
        self.assertIsNone(result["totals"]["fixed_commitment_usd"])
        self.assertEqual(result["quality"]["unverified_fixed_rows"], 1)

    def test_optional_allocation_view_is_summed_without_double_counting(self) -> None:
        self.insert_event(
            ts="2026-07-10T10:00:00+08:00",
            quota="codex-plus-subscription",
            machine="M5",
            cash=1.5,
            shadow=4.0,
        )
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO fixed_subscription_costs
                  (month, quota_source, label, monthly_cost_usd, active, updated_at)
                VALUES ('2026-07', 'codex-plus-subscription', 'Codex', 20, 1, '2026-07-01')
                """
            )
            connection.execute(
                """
                CREATE VIEW v_cost_events_amortized AS
                SELECT id, 2.5 AS fixed_amortized_cost_usd FROM cost_events
                """
            )
            connection.commit()
        result = collect_ledger_summary(self.db_path, now=self.now())
        self.assertEqual(result["totals"]["cash_metered_usd"], 1.5)
        self.assertEqual(result["totals"]["fixed_commitment_usd"], 20.0)
        self.assertEqual(result["totals"]["allocated_fixed_usd"], 2.5)
        self.assertEqual(result["totals"]["shadow_value_usd"], 4.0)


if __name__ == "__main__":
    unittest.main()
