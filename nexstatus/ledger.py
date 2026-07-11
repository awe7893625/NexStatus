"""Read-only cost ledger summary for NexStatus.

The canonical source is ``cost.db``.  This module deliberately has no write
path: it opens SQLite with ``mode=ro`` and returns a stable, redacted contract
even when the database is missing, busy, or from an older schema.
"""

from __future__ import annotations

import math
import hashlib
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = 2
STALE_AFTER_SECONDS = 6 * 60 * 60

CLASS_ORDER = (
    "subscription",
    "free_cloud",
    "local_compute",
    "metered_paid",
    "unknown",
)

SUBSCRIPTION_SOURCES = frozenset(
    {
        "claude-code-oauth-quota",
        "codex-plus-subscription",
        "opencode-go-subscription",
        "grok-build-subscription",
        "antigravity-google-ai-pro-subscription",
    }
)
FREE_CLOUD_SOURCES = frozenset(
    {
        "nim-free-quota",
        "gemini-free-quota",
        "openrouter-free-quota",
        "opencode-zen-free",
        "cerebras-free",
        "groq-free",
    }
)
METERED_PAID_SOURCES = frozenset(
    {
        "anthropic-api-paid",
        "openai-api-paid",
        "openrouter-paid",
        "opencode-zen-paid",
        "cerebras-paid",
        "paid-api",
        "xai-grok-api-paid",
    }
)
UNKNOWN_SOURCES = frozenset({"", "unknown-quota", "legacy-unattributed"})


def classify_quota_source(value: Any) -> str:
    """Return an explicit cost class; never infer from vague substrings."""

    source = str(value or "").strip()
    if source.startswith("local-"):
        return "local_compute"
    if source in SUBSCRIPTION_SOURCES:
        return "subscription"
    if source in FREE_CLOUD_SOURCES:
        return "free_cloud"
    if source in METERED_PAID_SOURCES:
        return "metered_paid"
    return "unknown"


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _empty_bucket(identifier: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "events": 0,
        "tokens": 0,
        "cash_usd": 0.0,
        "shadow_usd": 0.0,
    }


def _error_contract(status: str, warning: str, timezone_name: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": status,
        "period": None,
        "period_timezone": timezone_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_event_at": None,
        "freshness_seconds": None,
        "totals": None,
        "classes": [],
        "machines": [],
        "sources": [],
        "projects": [],
        "windows": {},
        "compute_capacity": None,
        "quality": {
            "level": "error",
            "unknown_quota_events": 0,
            "missing_machine_events": 0,
            "unverified_fixed_rows": 0,
            "stale": False,
            "warnings": [warning],
        },
    }


def _parse_event_time(value: Any, local_tz: ZoneInfo) -> tuple[datetime | None, bool]:
    if not isinstance(value, str) or not value.strip():
        return None, False
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None, False
    assumed_local = parsed.tzinfo is None
    if assumed_local:
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed.astimezone(local_tz), assumed_local


def _has_table(connection: sqlite3.Connection, name: str, kind: str = "table") -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ? LIMIT 1",
        (kind, name),
    ).fetchone()
    return row is not None


def _sum_optional_allocations(
    connection: sqlite3.Connection, event_ids: set[int]
) -> tuple[float | None, bool]:
    if not _has_table(connection, "v_cost_events_amortized", "view"):
        return None, False
    try:
        rows = connection.execute(
            "SELECT id, fixed_amortized_cost_usd FROM v_cost_events_amortized"
        )
        total = sum(
            _finite_number(row["fixed_amortized_cost_usd"])
            for row in rows
            if _integer(row["id"]) in event_ids
        )
    except sqlite3.Error:
        return None, False
    return round(total, 6), True


def _sorted_buckets(buckets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(buckets, key=lambda item: (-item["tokens"], item["id"]))


def _anonymous_key_id(value: str) -> str:
    """Return an internal digest used only to group equal key identifiers."""

    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def collect_ledger_summary(
    db_path: Path,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Taipei",
) -> dict[str, Any]:
    """Return the current-month ledger summary without modifying SQLite."""

    try:
        local_tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return _error_contract("error", "timezone_invalid", timezone_name)

    current = now or datetime.now(local_tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=local_tz)
    else:
        current = current.astimezone(local_tz)
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    window_cutoffs = {
        "today": current.replace(hour=0, minute=0, second=0, microsecond=0),
        "3d": current - timedelta(days=3),
        "7d": current - timedelta(days=7),
        "30d": current - timedelta(days=30),
    }
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    if not Path(db_path).is_file():
        return _error_contract("missing", "ledger_missing", timezone_name)

    try:
        connection = sqlite3.connect(
            f"file:{Path(db_path).resolve()}?mode=ro",
            uri=True,
            timeout=0.2,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
    except sqlite3.OperationalError as exc:
        status = "busy" if "locked" in str(exc).lower() or "busy" in str(exc).lower() else "error"
        return _error_contract(status, f"ledger_{status}", timezone_name)
    except sqlite3.Error:
        return _error_contract("error", "ledger_error", timezone_name)

    warnings: list[str] = []
    try:
        if not _has_table(connection, "cost_events"):
            return _error_contract("incompatible", "cost_events_missing", timezone_name)

        class_buckets = {name: _empty_bucket(name) for name in CLASS_ORDER}
        machine_buckets = {name: _empty_bucket(name) for name in ("m5", "m4", "unknown")}
        source_buckets: dict[str, dict[str, Any]] = {}
        project_buckets: dict[str, dict[str, Any]] = {}
        window_buckets: dict[str, dict[str, Any]] = {
            name: {"tokens": 0, "events": 0, "local_tokens": 0, "sources": {}, "projects": {}}
            for name in window_cutoffs
        }
        trend_start = (current - timedelta(days=29)).date()
        daily_tokens = {
            (trend_start + timedelta(days=offset)).isoformat(): {
                "tokens": 0, "claude": 0, "codex": 0,
                "free_cloud": 0, "local_compute": 0, "other": 0,
            }
            for offset in range(30)
        }
        free_key_buckets: dict[str, dict[str, Any]] = {}
        free_unattributed_events = 0
        free_unattributed_tokens = 0
        selected_ids: set[int] = set()
        latest_time: datetime | None = None
        naive_count = 0
        invalid_time_count = 0
        unknown_quota_events = 0
        missing_machine_events = 0
        input_tokens = 0
        output_tokens = 0
        cash_total = 0.0
        shadow_total = 0.0
        event_count = 0

        rows = connection.execute(
            """
            SELECT id, ts, quota_source, machine, project, task_class, provider, model,
                   api_key_id, input_tokens, output_tokens,
                   cost_usd, shadow_cost_usd
            FROM cost_events
            """
        )
        for row in rows:
            event_time, assumed_local = _parse_event_time(row["ts"], local_tz)
            if event_time is None:
                invalid_time_count += 1
                continue
            if assumed_local:
                naive_count += 1
            event_input = _integer(row["input_tokens"])
            event_output = _integer(row["output_tokens"])
            event_tokens = event_input + event_output
            event_cash = _finite_number(row["cost_usd"])
            event_shadow = _finite_number(row["shadow_cost_usd"])
            quota_source = str(row["quota_source"] or "unknown").strip() or "unknown"
            cost_class = classify_quota_source(quota_source)
            project_id = str(row["project"] or "未歸屬專案").strip() or "未歸屬專案"
            project_id = project_id[:80]

            event_day = event_time.date().isoformat()
            if event_day in daily_tokens and event_time <= current:
                daily_tokens[event_day]["tokens"] += event_tokens
                if quota_source == "claude-code-oauth-quota":
                    trend_class = "claude"
                elif quota_source == "codex-plus-subscription":
                    trend_class = "codex"
                elif cost_class in {"free_cloud", "local_compute"}:
                    trend_class = cost_class
                else:
                    trend_class = "other"
                daily_tokens[event_day][trend_class] += event_tokens

            if window_cutoffs["30d"] <= event_time <= current and cost_class == "free_cloud":
                raw_key_id = str(row["api_key_id"] or "").strip()
                if not raw_key_id:
                    free_unattributed_events += 1
                    free_unattributed_tokens += event_tokens
                else:
                    anonymous_id = _anonymous_key_id(raw_key_id)
                    key_bucket = free_key_buckets.setdefault(
                        anonymous_id,
                        {"id": anonymous_id, "tokens": 0, "events": 0, "sources": {}, "scenarios": {}},
                    )
                    key_bucket["tokens"] += event_tokens
                    key_bucket["events"] += 1
                    key_bucket["sources"][quota_source] = key_bucket["sources"].get(quota_source, 0) + event_tokens
                    scenario_parts = [
                        str(row["task_class"] or "").strip(),
                        str(row["provider"] or "").strip(),
                        str(row["model"] or "").strip(),
                        project_id,
                    ]
                    scenario = " · ".join(part[:48] for part in scenario_parts if part)[:160] or "未標記用途"
                    key_bucket["scenarios"][scenario] = key_bucket["scenarios"].get(scenario, 0) + event_tokens

            for window_name, cutoff in window_cutoffs.items():
                if cutoff <= event_time <= current:
                    window = window_buckets[window_name]
                    window["tokens"] += event_tokens
                    window["events"] += 1
                    if cost_class == "local_compute":
                        window["local_tokens"] += event_tokens
                    source = window["sources"].setdefault(quota_source, _empty_bucket(quota_source))
                    source["class"] = cost_class
                    source["tokens"] += event_tokens
                    source["events"] += 1
                    project = window["projects"].setdefault(project_id, _empty_bucket(project_id))
                    project["tokens"] += event_tokens
                    project["events"] += 1

            if not (month_start <= event_time < next_month):
                continue

            event_id = _integer(row["id"])
            selected_ids.add(event_id)
            latest_time = max(latest_time, event_time) if latest_time else event_time
            if cost_class == "unknown":
                unknown_quota_events += 1

            raw_machine = str(row["machine"] or "").strip().lower()
            machine_id = raw_machine if raw_machine in {"m4", "m5"} else "unknown"
            if machine_id == "unknown":
                missing_machine_events += 1

            source = source_buckets.setdefault(quota_source, _empty_bucket(quota_source))
            source["class"] = cost_class
            project = project_buckets.setdefault(project_id, _empty_bucket(project_id))
            for bucket in (class_buckets[cost_class], machine_buckets[machine_id], source, project):
                bucket["events"] += 1
                bucket["tokens"] += event_tokens
                bucket["cash_usd"] += event_cash
                bucket["shadow_usd"] += event_shadow

            input_tokens += event_input
            output_tokens += event_output
            cash_total += event_cash
            shadow_total += event_shadow
            event_count += 1

        for bucket in (*class_buckets.values(), *machine_buckets.values(), *source_buckets.values(), *project_buckets.values()):
            bucket["cash_usd"] = round(bucket["cash_usd"], 6)
            bucket["shadow_usd"] = round(bucket["shadow_usd"], 6)

        fixed_commitment: float | None = None
        fixed_verified = False
        unverified_fixed_rows = 0
        if _has_table(connection, "fixed_subscription_costs"):
            fixed_rows = list(
                connection.execute(
                    """
                    SELECT monthly_cost_usd
                    FROM fixed_subscription_costs
                    WHERE month = ? AND active = 1
                    """,
                    (month_start.strftime("%Y-%m"),),
                )
            )
            unverified_fixed_rows = sum(row["monthly_cost_usd"] is None for row in fixed_rows)
            if fixed_rows and unverified_fixed_rows == 0:
                fixed_commitment = round(
                    sum(_finite_number(row["monthly_cost_usd"]) for row in fixed_rows), 6
                )
                fixed_verified = True
            elif not fixed_rows:
                warnings.append("fixed_subscription_missing")
            else:
                warnings.append("fixed_subscription_unverified")
        else:
            warnings.append("fixed_subscription_table_missing")

        allocated_fixed, allocation_available = _sum_optional_allocations(
            connection, selected_ids
        )
        if not allocation_available:
            warnings.append("fixed_allocation_unavailable")
        if naive_count:
            warnings.append("naive_timestamps_assumed_local")
        if invalid_time_count:
            warnings.append("invalid_timestamps_skipped")
        if unknown_quota_events:
            warnings.append("unknown_quota_source")
        if missing_machine_events:
            warnings.append("machine_attribution_missing")

        freshness_seconds: int | None = None
        stale = False
        if latest_time:
            freshness_seconds = max(0, int((current - latest_time).total_seconds()))
            stale = freshness_seconds > STALE_AFTER_SECONDS
            if stale:
                warnings.append("ledger_stale")
        elif event_count == 0:
            warnings.append("period_has_no_events")

        quality_level = "warning" if warnings else "ok"
        thirty_day_tokens = window_buckets["30d"]["tokens"]
        windows: dict[str, Any] = {}
        for name in ("today", "3d", "7d", "30d"):
            window = window_buckets[name]
            total = window["tokens"]
            windows[name] = {
                "tokens": total,
                "events": window["events"],
                "share_of_30d_pct": round(total * 100 / thirty_day_tokens, 1) if thirty_day_tokens else None,
                "local_tokens": window["local_tokens"],
                "local_share_pct": round(window["local_tokens"] * 100 / total, 1) if total else None,
                "sources": _sorted_buckets(window["sources"].values()),
                "projects": _sorted_buckets(window["projects"].values()),
            }
        month_window = windows["30d"]
        free_tokens = sum(
            item["tokens"] for item in month_window["sources"]
            if item.get("class") == "free_cloud"
        )
        local_tokens = month_window["local_tokens"]
        combined_tokens = free_tokens + local_tokens
        free_keys: list[dict[str, Any]] = []
        sorted_key_buckets = sorted(free_key_buckets.values(), key=lambda item: (-item["tokens"], item["id"]))
        for key_index, bucket in enumerate(sorted_key_buckets, start=1):
            sources = sorted(bucket["sources"].items(), key=lambda item: (-item[1], item[0]))
            scenarios = sorted(bucket["scenarios"].items(), key=lambda item: (-item[1], item[0]))
            free_keys.append(
                {
                    "id": f"Slot {key_index:02d}",
                    "tokens": bucket["tokens"],
                    "events": bucket["events"],
                    "share_pct": round(bucket["tokens"] * 100 / free_tokens, 1) if free_tokens else None,
                    "sources": [{"id": source, "tokens": tokens} for source, tokens in sources[:6]],
                    "scenarios": [{"label": label, "tokens": tokens} for label, tokens in scenarios[:6]],
                }
            )
        free_events = sum(item.get("events", 0) for item in month_window["sources"] if item.get("class") == "free_cloud")
        attributed_events = max(0, free_events - free_unattributed_events)
        coverage_score = round(attributed_events * 100 / free_events, 1) if free_events else None
        compute_capacity = {
            "window": "30d",
            "free_cloud": {
                "tokens": free_tokens,
                "share_pct": round(free_tokens * 100 / combined_tokens, 1) if combined_tokens else None,
                # Keep api_key_count for snapshot compatibility; credential slots
                # are the actual semantic unit and must not be confused with providers.
                "api_key_count": len(free_keys),
                "credential_slot_count": len(free_keys),
                "unattributed_events": free_unattributed_events,
                "unattributed_tokens": free_unattributed_tokens,
                "coverage_score": coverage_score,
                "confidence_state": "confirmed" if coverage_score == 100 else ("partial" if free_events else "unknown"),
                "keys": free_keys,
                "sources": [item for item in month_window["sources"] if item.get("class") == "free_cloud"],
            },
            "local_compute": {
                "tokens": local_tokens,
                "share_pct": round(local_tokens * 100 / combined_tokens, 1) if combined_tokens else None,
                "sources": [item for item in month_window["sources"] if item.get("class") == "local_compute"],
            },
            "combined": {"tokens": combined_tokens},
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "status": "live",
            "period": month_start.strftime("%Y-%m"),
            "period_timezone": timezone_name,
            "generated_at": current.isoformat(),
            "latest_event_at": latest_time.isoformat() if latest_time else None,
            "freshness_seconds": freshness_seconds,
            "totals": {
                "cash_metered_usd": round(cash_total, 6),
                "fixed_commitment_usd": fixed_commitment,
                "fixed_verified": fixed_verified,
                "allocated_fixed_usd": allocated_fixed,
                "shadow_value_usd": round(shadow_total, 6),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "events": event_count,
            },
            "classes": [class_buckets[name] for name in CLASS_ORDER],
            "machines": [machine_buckets[name] for name in ("m5", "m4", "unknown")],
            "sources": _sorted_buckets(source_buckets.values()),
            "projects": _sorted_buckets(project_buckets.values()),
            "windows": windows,
            "trend_30d": [
                {"date": day, **values}
                for day, values in daily_tokens.items()
            ],
            "compute_capacity": compute_capacity,
            "quality": {
                "level": quality_level,
                "unknown_quota_events": unknown_quota_events,
                "missing_machine_events": missing_machine_events,
                "unverified_fixed_rows": unverified_fixed_rows,
                "stale": stale,
                "warnings": list(dict.fromkeys(warnings)),
            },
        }
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        status = "busy" if "locked" in text or "busy" in text else "incompatible"
        return _error_contract(status, f"ledger_{status}", timezone_name)
    except sqlite3.Error:
        return _error_contract("error", "ledger_error", timezone_name)
    finally:
        connection.close()
