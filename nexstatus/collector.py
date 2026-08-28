#!/usr/bin/env python3
"""NexStatus collector — Claude / Codex / OpenCode Go / Grok / OpenRouter / host metrics.

Writes a JSON snapshot for the Hammerspoon MenuBar UI.
No secrets are written to disk (tokens are only used in-memory for API calls).
"""
from __future__ import annotations

import json
import math
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from nexstatus.ledger import collect_ledger_summary
except ModuleNotFoundError:  # direct ``python nexstatus/collector.py`` execution
    from ledger import collect_ledger_summary

try:
    from nexstatus.local_integrations import rag_status, tokentracker_usage
except ModuleNotFoundError:
    from local_integrations import rag_status, tokentracker_usage

CACHE_DIR = Path(os.environ.get("NEXSTATUS_CACHE", os.path.expanduser("~/.cache/nexstatus")))
OUT = CACHE_DIR / "status.json"
GROK_CACHE = CACHE_DIR / "grok-billing.json"
GROK_HISTORY = CACHE_DIR / "grok-billing-history.jsonl"
OPENROUTER_CACHE = CACHE_DIR / "openrouter.json"
OPENROUTER_HISTORY = CACHE_DIR / "openrouter-history.jsonl"
GO_CACHE = CACHE_DIR / "opencode-go.json"
CLAUDE_CACHE = CACHE_DIR / "claude-usage.json"
CLAUDE_STATUS = Path(os.path.expanduser("~/.claude/usage-status.json"))
CLAUDE_LEGACY = Path(os.path.expanduser("~/.claude/usag-status.json"))
CLAUDE_TT = Path(os.path.expanduser("~/.claude/tt-status.json"))
CODEX_SESSIONS = Path(os.path.expanduser("~/.codex/sessions"))
GROK_AUTH = Path(os.path.expanduser("~/.grok/auth.json"))
OPENCODE_AUTH = Path(os.path.expanduser("~/.local/share/opencode/auth.json"))
COST_DB = Path(os.environ.get("NEXSTATUS_COST_DB", os.path.expanduser("~/.claude/state/cost.db")))
GROK_SEATS_ROOT = Path(os.path.expanduser(os.environ.get("GROK_SEATS_ROOT", "~/.grok-seats")))
GROK_SEAT_CACHES = tuple(CACHE_DIR / f"grok-billing-seat-{n}.json" for n in (1, 2, 3))
GROK_SEAT_HISTORIES = tuple(CACHE_DIR / f"grok-billing-history-seat-{n}.jsonl" for n in (1, 2, 3))
GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing"
# Lightweight enforcement probe (GET, no completion burn). Billing can show
# remaining SuperGrok credits while this path still returns spending-limit
# (g2 / movielin8866 2026-08-01: used=0/15000 but personal-team-blocked).
GROK_MODELS_URL = "https://api.x.ai/v1/models"
OPENROUTER_CREDITS_URL = "https://openrouter.ai/api/v1/credits"
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
GO_CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
GROK_TTL = 5 * 60  # seconds — billing is monthly, no need to hammer API
GROK_CHAT_GATE_TIMEOUT = 8.0
OPENROUTER_TTL = 5 * 60  # seconds — account billing data does not need rapid polling
OPENROUTER_TIMEOUT = 8.0
# The Hammerspoon collector watchdog is 8s for the whole process. Keep this
# optional provider well inside that window, including both seats and both
# endpoints per seat, so one slow billing call cannot starve later providers.
OPENROUTER_TOTAL_DEADLINE = 3.5
OPENROUTER_SEAT_DEADLINE = 1.5
# The Hammerspoon collector watchdog kills the whole process at 8s. Establish
# one shared deadline at build_snapshot() start so OpenRouter (which runs
# after host/claude/codex/grok/grok_seats) can never grant itself a fresh
# relative budget that ignores how much of the 8s earlier providers already
# spent. 0.5s margin covers OpenRouter's own post-fetch JSON/trend/cache work.
COLLECTOR_WATCHDOG_BUDGET_SECONDS = 7.5
OPENROUTER_MIN_REQUEST_BUDGET = 0.1
# x.ai's /v1/billing endpoint returns credits only, never a USD figure — the
# subscription price has to be hand-maintained here (Rain-confirmed 2026-07-12).
# Bump this when the plan tier or price changes; nothing else will catch it.
GROK_PLAN_NAME = "SuperGrok"
GROK_PLAN_PRICE_USD_MO = 30.0
# SuperGrok included monthly credit pool (hand-maintained; API used to return
# this as monthlyLimit until ~2026-08-10 when it started returning 0).
# Used only as soft fallback when API omits limit so MenuBar can show %.
GROK_DEFAULT_MONTHLY_LIMIT = 15000.0
GO_TTL_OK = 5 * 60
GO_TTL_CAPPED = 15 * 60  # when already at limit, probe less often
CLAUDE_FRESH_TTL = 90  # recent sanitized status/cache freshness window
CLAUDE_TTL = 6 * 60 * 60  # last-known-good quota when statusLine omits rate_limits
# Official OpenCode Go caps (https://opencode.ai/docs/go/#usage-limits)
GO_CAP_5H_USD = 12.0
GO_CAP_WEEK_USD = 30.0
GO_CAP_MONTH_USD = 60.0
AGY_CACHE = CACHE_DIR / "antigravity.json"
AGY_TTL = 90  # live LS probe interval while agy is up
AGY_STALE_TTL = 6 * 60 * 60  # keep last-known-good when CLI briefly exits
AGY_RPC = "/exa.language_server_pb.LanguageServerService/GetUserStatus"
AGY_MAX_PORTS = 8  # raised: up to 4 accounts × 2 ports each (LS + web)
AGY_MAX_MODELS = 12
AGY_MAX_RESPONSE_BYTES = 256 * 1024
AGY_TOTAL_DEADLINE = 6.0  # slightly more headroom for multi-seat probing
AGY_MAX_SEATS = 4
# Maps JETSKI_APP_DATA_DIR values to human-readable seat numbers.
# "antigravity-cli" is the default (original agy); agy-account-N are wrappers.
AGY_SEAT_DATA_DIRS: dict[str, int] = {
    "antigravity-cli": 0,  # original default agy
    "agy-account-1": 1,
    "agy-account-2": 2,
    "agy-account-3": 3,
    "agy-account-4": 4,
}
AGY_SEAT_CACHES = tuple(CACHE_DIR / f"antigravity-seat-{n}.json" for n in range(AGY_MAX_SEATS + 1))
# Process names / path fragments that legitimately host the Antigravity LS.
AGY_COMM_NAMES = frozenset({"agy", "agy-node", "Antigravity", "antigravity"})
AGY_PATH_MARKERS = (
    "/Antigravity/",
    "/antigravity/",
    "/bin/agy",
    "agy-node",
)
OPENROUTER_M5_ENV = Path(os.path.expanduser("~/.credentials/m5_openrouter.env"))
OPENROUTER_GLOBAL_ENV = Path(os.path.expanduser("~/.hermes/credentials.d/openrouter"))
OPENROUTER_SEATS = (
    {"seat": "m5", "path": OPENROUTER_M5_ENV, "variable": "OPENROUTER_API_KEY_M5"},
    {"seat": "global", "path": OPENROUTER_GLOBAL_ENV, "variable": "OPENROUTER_API_KEY"},
)
KNOWN_CACHE_FILES = (
    OUT, GROK_CACHE, OPENROUTER_CACHE, GO_CACHE, AGY_CACHE, CLAUDE_CACHE,
    *GROK_SEAT_CACHES, *AGY_SEAT_CACHES,
)


def _now() -> float:
    return time.time()


def _safe_error(value: Any, fallback: str = "source_unavailable") -> str:
    """Return a short error label without paths, URLs, or response bodies."""
    if not value:
        return fallback
    text = str(value)
    if "HTTP " in text:
        match = re.search(r"HTTP\s+(\d{3})", text)
        return f"HTTP {match.group(1)}" if match else fallback
    if isinstance(value, urllib.error.URLError):
        return "network_unavailable"
    if isinstance(value, TimeoutError):
        return "source_timeout"
    return fallback


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(CACHE_DIR, 0o700)
    for path in KNOWN_CACHE_FILES:
        try:
            if path.parent == CACHE_DIR and path.is_file():
                os.chmod(path, 0o600)
        except OSError:
            continue
    try:
        if OPENROUTER_HISTORY.parent == CACHE_DIR and OPENROUTER_HISTORY.is_file():
            os.chmod(OPENROUTER_HISTORY, 0o600)
    except OSError:
        pass


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_cache_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically write one known cache file with owner-only permissions."""
    if path.parent != CACHE_DIR or path not in KNOWN_CACHE_FILES:
        raise ValueError("unsupported_cache_path")
    _ensure_cache_dir()
    temp_path = CACHE_DIR / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temp_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(_json_safe(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _pct(v: Any) -> int | None:
    if v is None:
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return max(0, min(100, int(round(n))))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _claude_rate_windows(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract 5h / 7d windows from several Claude Code statusLine shapes."""
    rl = data.get("rate_limits") if isinstance(data.get("rate_limits"), dict) else {}
    five = rl.get("five_hour") if isinstance(rl.get("five_hour"), dict) else {}
    seven = rl.get("seven_day") if isinstance(rl.get("seven_day"), dict) else {}
    # Newer payloads sometimes nest under utilization / limits.
    if not five and not seven:
        for key in ("utilization", "limits", "usage", "quota"):
            nested = data.get(key)
            if isinstance(nested, dict):
                if isinstance(nested.get("five_hour"), dict):
                    five = nested["five_hour"]
                if isinstance(nested.get("seven_day"), dict):
                    seven = nested["seven_day"]
                if isinstance(nested.get("rate_limits"), dict):
                    sub = nested["rate_limits"]
                    five = five or (sub.get("five_hour") if isinstance(sub.get("five_hour"), dict) else {})
                    seven = seven or (sub.get("seven_day") if isinstance(sub.get("seven_day"), dict) else {})
    return five, seven


def _claude_from_cache(max_age: float = CLAUDE_TTL) -> dict[str, Any] | None:
    if not CLAUDE_CACHE.is_file():
        return None
    try:
        cached = json.loads(CLAUDE_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(cached, dict) or not cached.get("ok"):
        return None
    age = _now() - float(cached.get("_fetched_at_ts") or 0)
    if age > max_age:
        return None
    if cached.get("five_hour_pct") is None and cached.get("seven_day_pct") is None:
        return None
    cached = dict(cached)
    cached["stale"] = age > CLAUDE_FRESH_TTL
    cached["source"] = cached.get("source") or "claude-cache"
    # Never re-surface accidental credential fields if an old cache had them.
    for key in ("access_token", "refresh_token", "email", "email_address", "full_name"):
        cached.pop(key, None)
    return cached


def claude_usage() -> dict[str, Any]:
    data = None
    source = None
    for path in (CLAUDE_STATUS, CLAUDE_LEGACY, CLAUDE_TT):
        data = _read_json(path)
        if data:
            source = "claude-status"
            break

    model = None
    updated_at = None
    five_pct = seven_pct = None
    five_reset = seven_reset = None

    if data:
        five, seven = _claude_rate_windows(data)
        now = _now()
        five_reset = five.get("resets_at")
        seven_reset = seven.get("resets_at")
        five_pct = _pct(five.get("used_percentage", five.get("used_percent", five.get("utilization"))))
        seven_pct = _pct(seven.get("used_percentage", seven.get("used_percent", seven.get("utilization"))))
        if isinstance(five_reset, (int, float)) and five_reset < now:
            five_pct = 0
        if isinstance(seven_reset, (int, float)) and seven_reset < now:
            seven_pct = 0
        if isinstance(data.get("model"), dict):
            model = data["model"].get("display_name") or data["model"].get("id")
        updated_at = data.get("_received_at") or data.get("updated_at")

        if five_pct is not None or seven_pct is not None:
            result = {
                "ok": True,
                "source": source,
                "five_hour_pct": five_pct,
                "seven_day_pct": seven_pct,
                "five_hour_resets_at": five_reset,
                "seven_day_resets_at": seven_reset,
                "model": model,
                "updated_at": updated_at,
                "stale": False,
                "_fetched_at": datetime.now(timezone.utc).isoformat(),
                "_fetched_at_ts": now,
            }
            try:
                _write_cache_json(CLAUDE_CACHE, result)
            except OSError:
                pass
            return result

    cached = _claude_from_cache()
    if cached:
        if model and not cached.get("model"):
            cached = dict(cached)
            cached["model"] = model
        return cached

    if data:
        return {
            "ok": False,
            "error": "rate_limits_missing",
            "source": source,
            "model": model,
            "updated_at": updated_at,
            "five_hour_pct": None,
            "seven_day_pct": None,
        }
    return {"ok": False, "error": "no status file", "source": None}


def codex_usage() -> dict[str, Any]:
    if not CODEX_SESSIONS.is_dir():
        return {"ok": False, "error": "no sessions dir"}

    paths: list[tuple[float, Path]] = []
    for p in CODEX_SESSIONS.rglob("*.jsonl"):
        try:
            paths.append((p.stat().st_mtime, p))
        except OSError:
            continue
    paths.sort(key=lambda x: x[0], reverse=True)

    for _, path in paths[:8]:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        # scan tail only
        text = raw[-400_000:].decode("utf-8", errors="replace")
        for line in reversed(text.splitlines()):
            if "rate_limits" not in line or "used_percent" not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            rl = _find_rate_limits(obj)
            if not rl:
                continue
            primary = rl.get("primary") if isinstance(rl.get("primary"), dict) else {}
            secondary = rl.get("secondary") if isinstance(rl.get("secondary"), dict) else {}

            # Codex reports windows generically as primary/secondary; which one is
            # the 5h vs 7d/weekly bucket is decided by window_minutes, not position.
            # (Seen in practice: primary alone holding window_minutes=10080/7d with
            # secondary=null — a naive primary->5h mapping mislabels that as 5h.)
            five: dict[str, Any] = {}
            seven: dict[str, Any] = {}
            for window in (primary, secondary):
                if not window:
                    continue
                minutes = window.get("window_minutes")
                if isinstance(minutes, (int, float)):
                    if minutes <= 720:
                        five = window
                    else:
                        seven = window
                elif not five:
                    five = window
                else:
                    seven = window

            return {
                "ok": True,
                "source": "codex-session",
                "five_hour_pct": _pct(five.get("used_percent")),
                "seven_day_pct": _pct(seven.get("used_percent")),
                "five_hour_resets_at": five.get("resets_at"),
                "seven_day_resets_at": seven.get("resets_at"),
                "plan_type": rl.get("plan_type"),
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
    return {"ok": False, "error": "no rate_limits in recent sessions"}


def _find_rate_limits(obj: Any, depth: int = 0) -> dict[str, Any] | None:
    if depth > 10:
        return None
    if isinstance(obj, dict):
        if "primary" in obj and isinstance(obj.get("primary"), dict) and "used_percent" in obj["primary"]:
            return obj
        if "rate_limits" in obj:
            return _find_rate_limits(obj["rate_limits"], depth + 1)
        for v in obj.values():
            found = _find_rate_limits(v, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj[:20]:
            found = _find_rate_limits(v, depth + 1)
            if found:
                return found
    return None


def _grok_week_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """ISO week Monday 00:00 UTC → next Monday (SuperGrok-style rolling week display)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    weekday = now.weekday()  # Mon=0
    start = (now - timedelta(days=weekday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(days=7)
    return start, end


def _append_grok_billing_history(used: float | None, monthly_limit: float | None) -> None:
    """Append redacted billing point so weekly credit burn can be estimated."""
    if used is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ts_unix": _now(),
            "used": float(used),
            "monthly_limit": float(monthly_limit) if monthly_limit is not None else None,
        }
        with GROK_HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        # keep last ~400 points (~2 weeks at 5-min poll worst case still fine)
        lines = GROK_HISTORY.read_text(encoding="utf-8").splitlines()
        if len(lines) > 500:
            GROK_HISTORY.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _append_grok_billing_history_to(used: float | None, monthly_limit: float | None, path: Path) -> None:
    """Append redacted billing point to custom history file."""
    if used is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ts_unix": _now(),
            "used": float(used),
            "monthly_limit": float(monthly_limit) if monthly_limit is not None else None,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 500:
            path.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _last_nonzero_monthly_limit(history_path: Path | None = None) -> float | None:
    """Scan billing history for the most recent non-zero monthly_limit."""
    path = history_path if history_path is not None else GROK_HISTORY
    if path is None or not path.exists():
        return None
    last: float | None = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            lim = row.get("monthly_limit")
            if lim is None:
                continue
            lim_f = float(lim)
            if lim_f > 0:
                last = lim_f
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return last
    return last


def _resolve_grok_monthly_pool(
    api_limit: float | None,
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve display monthly credit pool when API omits/zeros monthlyLimit.

    Priority: API (>0) → last non-zero history → SuperGrok plan default.
    Soft fallbacks set limit_missing=True so UI can badge 「軟估」.
    """
    api_raw = float(api_limit) if api_limit is not None else None
    if api_raw is not None and api_raw > 0:
        return {
            "monthly_limit": api_raw,
            "monthly_limit_api": api_raw,
            "limit_missing": False,
            "limit_source": "api",
        }
    hist = _last_nonzero_monthly_limit(history_path)
    if hist is not None and hist > 0:
        return {
            "monthly_limit": float(hist),
            "monthly_limit_api": api_raw,
            "limit_missing": True,
            "limit_source": "history_last_nonzero",
        }
    return {
        "monthly_limit": float(GROK_DEFAULT_MONTHLY_LIMIT),
        "monthly_limit_api": api_raw,
        "limit_missing": True,
        "limit_source": "plan_default",
    }


def _grok_used_pct(used: float | None, monthly_limit: float | None) -> int | None:
    if used is not None and monthly_limit and monthly_limit > 0:
        return max(0, min(100, int(round(100.0 * float(used) / float(monthly_limit)))))
    return None


def _grok_weekly_from_history(
    current_used: float | None,
    monthly_limit: float | None,
    period_start: str | None = None,
    period_end: str | None = None,
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Estimate SuperGrok weekly credit use from local billing snapshots.

    CLI /v1/billing only returns *monthly* credits. We persist each fetch and
    compute week-to-date burn vs a pro-rata weekly share of the monthly pool.
    """
    empty = {
        "weekly_used_pct": None,
        "weekly_used": None,
        "weekly_limit": None,
        "weekly_reset_at": None,
        "weekly_breakdown": {},
        "weekly_available": False,
        "weekly_source": None,
        "weekly_note": None,
    }
    if current_used is None:
        return empty

    week_start, week_end = _grok_week_bounds_utc()
    # Pro-rata weekly limit from monthly pool (soft cap for the bar).
    month_days = 30.0
    try:
        if period_start and period_end:
            ps = datetime.fromisoformat(str(period_start).replace("Z", "+00:00"))
            pe = datetime.fromisoformat(str(period_end).replace("Z", "+00:00"))
            month_days = max(1.0, (pe - ps).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        pass
    weekly_limit = None
    if monthly_limit and monthly_limit > 0:
        weekly_limit = float(monthly_limit) * 7.0 / month_days

    baseline_used = None
    baseline_ts = None
    actual_history_path = history_path if history_path is not None else GROK_HISTORY
    if actual_history_path.exists():
        try:
            for line in actual_history_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                ts_raw = row.get("ts") or ""
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                except ValueError:
                    continue
                used_val = row.get("used")
                if used_val is None:
                    continue
                used_f = float(used_val)
                # only trust snapshots at/before week start as true baseline
                if ts <= week_start:
                    baseline_used = used_f
                    baseline_ts = ts.isoformat()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    weekly_used = None
    weekly_source = None
    weekly_note = None

    if baseline_used is not None:
        weekly_used = max(0.0, float(current_used) - float(baseline_used))
        weekly_source = "billing_snapshot_delta"
        weekly_note = f"本週自 {str(baseline_ts)[:10]} 快照起算 credits 增量"
    else:
        # No pre-week snapshot yet: linear burn estimate since billing period start.
        try:
            if period_start:
                ps = datetime.fromisoformat(str(period_start).replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_into = max(1.0, (now - ps).total_seconds() / 86400.0)
                # If billing period started this week, all MTD credits are this week.
                # Soft weekly_limit is still month×7/days — do NOT treat early-month
                # front-load as hard 100% cap (UI de-emphasizes linear estimates).
                if ps >= week_start:
                    weekly_used = max(0.0, float(current_used))
                    weekly_source = "linear_period_estimate"
                    weekly_note = (
                        "計費週自本週開始；本週用量=本月已用（軟上限=月額×7/月天，非硬鎖）"
                    )
                else:
                    days_before_week = max(0.0, (week_start - ps).total_seconds() / 86400.0)
                    baseline_est = float(current_used) * (days_before_week / days_into)
                    weekly_used = max(0.0, float(current_used) - baseline_est)
                    weekly_source = "linear_period_estimate"
                    weekly_note = "CLI 無官方週額度；以月 credits 線性估本週用量（週上限=月額×7/月天數）"
            else:
                weekly_used = 0.0
                weekly_source = "billing_snapshot_pending"
                weekly_note = "週額度估算中（需 billing 快照）"
        except (TypeError, ValueError):
            weekly_used = 0.0
            weekly_source = "billing_snapshot_pending"
            weekly_note = "週額度估算中"

    used_pct = None
    if weekly_used is not None and weekly_limit and weekly_limit > 0:
        # Cap display at 100; raw weekly_used may exceed soft pro-rata limit.
        used_pct = max(0, min(100, int(round(100.0 * weekly_used / weekly_limit))))

    return {
        "weekly_used_pct": used_pct,
        "weekly_used": weekly_used,
        "weekly_limit": weekly_limit,
        "weekly_reset_at": week_end.isoformat(),
        "weekly_breakdown": {},
        "weekly_available": weekly_limit is not None,
        "weekly_source": weekly_source,
        "weekly_note": weekly_note,
        "weekly_window_start": week_start.isoformat(),
    }


def _grok_weekly_usage(
    cfg: dict[str, Any],
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Extract consumer weekly-pool fields without persisting account details.

    Prefer official fields when present; otherwise estimate from local snapshots.
    Pass history_path for multi-seat isolation — never share one seat's baseline
    with another (wrong baselines inflate/deflate weekly bars).
    """
    weekly = next(
        (
            cfg.get(key)
            for key in ("weeklyUsage", "weekly_usage", "weeklyLimit", "weekly_limit")
            if isinstance(cfg.get(key), dict)
        ),
        {},
    )
    used_pct = None
    for value in (
        weekly.get("usedPercent"), weekly.get("used_pct"), weekly.get("percentageUsed"),
        cfg.get("weeklyUsagePercent"), cfg.get("weekly_used_pct"),
    ):
        used_pct = _pct(value)
        if used_pct is not None:
            break
    used = _money_val(weekly.get("used"))
    limit = _money_val(weekly.get("limit") or weekly.get("allowance"))
    if used_pct is None and used is not None and limit and limit > 0:
        used_pct = _pct(100 * used / limit)

    breakdown_raw = weekly.get("breakdown") or weekly.get("products") or cfg.get("weeklyUsageBreakdown")
    breakdown: dict[str, int] = {}
    if isinstance(breakdown_raw, dict):
        for product, value in breakdown_raw.items():
            pct_value = _pct(value.get("usedPercent") if isinstance(value, dict) else value)
            if pct_value is not None and str(product).lower() in {"api", "build", "chat", "imagine", "voice"}:
                breakdown[str(product).lower()] = pct_value

    reset_at = next(
        (
            value for value in (
                weekly.get("resetsAt"), weekly.get("resetAt"), weekly.get("reset_at"),
                cfg.get("weeklyResetAt"), cfg.get("weekly_reset_at"),
            ) if isinstance(value, str) and value
        ),
        None,
    )
    if used_pct is not None or reset_at is not None or bool(breakdown) or used is not None:
        return {
            "weekly_used_pct": used_pct,
            "weekly_used": used,
            "weekly_limit": limit,
            "weekly_reset_at": reset_at,
            "weekly_breakdown": breakdown,
            "weekly_available": used_pct is not None or reset_at is not None or bool(breakdown) or used is not None,
            "weekly_source": "api",
            "weekly_note": None,
        }

    # CLI billing currently only exposes monthly pool — estimate week from snapshots.
    # history_path must be seat-specific when called from multi-seat collectors.
    return _grok_weekly_from_history(
        current_used=_money_val(cfg.get("used")),
        monthly_limit=_money_val(cfg.get("monthlyLimit")),
        period_start=cfg.get("billingPeriodStart"),
        period_end=cfg.get("billingPeriodEnd"),
        history_path=history_path,
    )


def grok_usage(force: bool = False) -> dict[str, Any]:
    # Prefer short-lived cache so MenuBar refresh doesn't hit network every 2s.
    # Require chat_gate so pre-probe caches are refreshed once.
    if not force and GROK_CACHE.exists():
        try:
            cached = json.loads(GROK_CACHE.read_text(encoding="utf-8"))
            if (
                _now() - float(cached.get("_fetched_at_ts", 0)) < GROK_TTL
                and "chat_gate" in cached
            ):
                return cached
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    auth = _read_json(GROK_AUTH)
    if not auth:
        return {"ok": False, "error": "no ~/.grok/auth.json — run grok login"}

    token = _auth_bearer_token(auth)
    if not token:
        return {"ok": False, "error": "no access token in auth.json"}

    req = urllib.request.Request(
        GROK_BILLING_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "nexstatus/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 — optional provider isolation
        return {"ok": False, "error": _safe_error(e)}

    cfg = body.get("config") if isinstance(body.get("config"), dict) else body
    used = _money_val(cfg.get("used"))
    api_limit = _money_val(cfg.get("monthlyLimit"))
    pool = _resolve_grok_monthly_pool(api_limit, history_path=GROK_HISTORY)
    limit = pool["monthly_limit"]
    pct = _grok_used_pct(used, limit)

    weekly_fields = _grok_weekly_usage(cfg)
    # Prefer official weekly block; otherwise estimate with *effective* monthly
    # pool (soft limit when API returns 0).
    if (
        not weekly_fields.get("weekly_available")
        or weekly_fields.get("weekly_source") != "api"
    ):
        weekly_fields = _grok_weekly_from_history(
            current_used=used,
            monthly_limit=limit,
            period_start=cfg.get("billingPeriodStart"),
            period_end=cfg.get("billingPeriodEnd"),
        )
        if pool["limit_missing"] and weekly_fields.get("weekly_available"):
            note = weekly_fields.get("weekly_note") or ""
            tag = "月上限軟估（API 未回）"
            weekly_fields["weekly_note"] = f"{note}；{tag}" if note else tag

    result = {
        "ok": True,
        "source": GROK_BILLING_URL,
        "plan": GROK_PLAN_NAME,
        "price": f"${GROK_PLAN_PRICE_USD_MO:g}/mo",
        "used": used,
        "monthly_limit": limit,
        "monthly_limit_api": pool["monthly_limit_api"],
        "limit_missing": pool["limit_missing"],
        "limit_source": pool["limit_source"],
        "used_pct": pct,
        "on_demand_cap": _money_val(cfg.get("onDemandCap")),
        "period_start": cfg.get("billingPeriodStart"),
        "period_end": cfg.get("billingPeriodEnd"),
        "unit": "credits",
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
        **weekly_fields,
    }
    _annotate_grok_enforcement(result, token)
    # History stores raw API limit so last-nonzero fallback stays honest.
    _append_grok_billing_history(used, api_limit)
    try:
        _write_cache_json(GROK_CACHE, result)
    except OSError:
        pass
    return result


def _seat_email(auth_path: Path) -> str:
    """Extract email from a grok-seat auth.json without exposing tokens."""
    data = _read_json(auth_path)
    if not data:
        return "(not logged in)"
    for v in data.values():
        if isinstance(v, dict) and v.get("email"):
            return str(v["email"])
    return "(no email)"


def _auth_bearer_token(auth: dict[str, Any] | None) -> str | None:
    if not auth:
        return None
    for entry in auth.values():
        if isinstance(entry, dict):
            key = entry.get("key")
            if isinstance(key, str) and key:
                return key
    return None


def _grok_chat_gate(token: str) -> dict[str, Any]:
    """Probe whether the chat enforcement path allows this session.

    SuperGrok ``/v1/billing`` only reports monthly included credits. The chat
    path (``api.x.ai``) can still return ``personal-team-blocked:spending-limit``
    after a hard overage month, even when billing ``used`` has reset to 0.
    Use GET ``/v1/models`` so we do not burn completion credits.
    """
    req = urllib.request.Request(
        GROK_MODELS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "nexstatus/1.0",
        },
    )
    try:
        with urllib.request.urlopen(
            req,
            context=ssl.create_default_context(),
            timeout=GROK_CHAT_GATE_TIMEOUT,
        ) as resp:
            # Drain body so the connection can close cleanly; ignore content.
            try:
                resp.read(4096)
            except Exception:  # noqa: BLE001
                pass
            return {
                "chat_ok": True,
                "chat_gate": "ok",
                "block_code": None,
                "block_message": None,
                "http_status": getattr(resp, "status", 200),
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:  # noqa: BLE001
            body = ""
        code: str | None = None
        msg: str | None = None
        try:
            parsed = json.loads(body) if body else {}
            if isinstance(parsed, dict):
                raw_code = parsed.get("code") or parsed.get("error_code")
                code = str(raw_code) if raw_code is not None else None
                err = parsed.get("error")
                if isinstance(err, str):
                    msg = err
                elif isinstance(err, dict):
                    msg = err.get("message") or err.get("error")
                    if msg is not None:
                        msg = str(msg)
                if not msg and parsed.get("message") is not None:
                    msg = str(parsed.get("message"))
        except json.JSONDecodeError:
            msg = body[:200] if body else None

        msg_l = (msg or "").lower()
        code_l = (code or "").lower()
        blocked = (
            e.code in (402, 403)
            or "spending-limit" in code_l
            or "blocked" in code_l
            or "usage balance exhausted" in msg_l
            or "run out of credits" in msg_l
            or "payment required" in msg_l
        )
        if blocked:
            return {
                "chat_ok": False,
                "chat_gate": "blocked",
                "block_code": code or f"http_{e.code}",
                "block_message": (msg or "chat path blocked")[:240],
                "http_status": e.code,
            }
        return {
            "chat_ok": None,
            "chat_gate": "unknown",
            "block_code": code or f"http_{e.code}",
            "block_message": (msg or f"HTTP {e.code}")[:240],
            "http_status": e.code,
        }
    except Exception as e:  # noqa: BLE001 — probe must never abort snapshot
        return {
            "chat_ok": None,
            "chat_gate": "unknown",
            "block_code": None,
            "block_message": _safe_error(e),
            "http_status": None,
        }


def _annotate_grok_enforcement(
    result: dict[str, Any],
    token: str | None,
) -> dict[str, Any]:
    """Attach chat-gate fields; flag billing-vs-enforcement mismatch (假有額)."""
    used = result.get("used")
    limit = result.get("monthly_limit")
    billing_remaining = True
    billing_exhausted = False
    if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
        billing_exhausted = float(used) >= float(limit)
        billing_remaining = float(used) < float(limit)

    if billing_exhausted:
        result["chat_ok"] = False
        result["chat_gate"] = "billing_exhausted"
        result["block_code"] = "monthly_limit"
        result["block_message"] = "月 credits 已用盡"
        result["http_status"] = None
        result["effective_available"] = False
        result["false_available"] = False
        result["status_label"] = "額度盡"
        return result

    if not token:
        result["chat_ok"] = None
        result["chat_gate"] = "unknown"
        result["block_code"] = None
        result["block_message"] = "no access token"
        result["http_status"] = None
        result["effective_available"] = None
        result["false_available"] = False
        result["status_label"] = "未確認"
        return result

    gate = _grok_chat_gate(token)
    result["chat_ok"] = gate.get("chat_ok")
    result["chat_gate"] = gate.get("chat_gate")
    result["block_code"] = gate.get("block_code")
    result["block_message"] = gate.get("block_message")
    result["http_status"] = gate.get("http_status")

    if gate.get("chat_gate") == "blocked":
        # Billing says room left, enforcement says no → 假有額 / 帳務鎖
        result["effective_available"] = False
        result["false_available"] = bool(billing_remaining)
        result["status_label"] = "帳務鎖" if billing_remaining else "額度盡"
    elif gate.get("chat_ok") is True:
        result["effective_available"] = True
        result["false_available"] = False
        result["status_label"] = "正常"
    else:
        result["effective_available"] = None
        result["false_available"] = False
        result["status_label"] = "未確認"
    return result


def _grok_seat_stale_fallback(
    cache_path: Path,
    seat_num: int,
    email: str,
    err: str,
) -> dict[str, Any] | None:
    """On transient billing failure, prefer last good seat cache over '離線'."""
    if not cache_path.is_file():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(cached, dict) or not cached.get("ok"):
        return None
    # Require a prior successful billing payload (used/limit), not a bare error shell.
    if cached.get("used") is None and cached.get("monthly_limit") is None:
        return None
    out = dict(cached)
    out["seat"] = seat_num
    out["email"] = email
    out["active"] = True
    out["stale"] = True
    out["stale_error"] = err
    out["status_label"] = (out.get("status_label") or "正常") + "·快取"
    return out


def _grok_seat_billing(seat_num: int, force: bool = False) -> dict[str, Any]:
    """Fetch billing for one grok-seat, with per-seat cache and history."""
    seat_dir = GROK_SEATS_ROOT / str(seat_num)
    auth_path = seat_dir / "auth.json"
    cache_path = CACHE_DIR / f"grok-billing-seat-{seat_num}.json"
    history_path = CACHE_DIR / f"grok-billing-history-seat-{seat_num}.jsonl"
    
    email = _seat_email(auth_path)
    
    if not auth_path.is_file():
        return {"ok": False, "seat": seat_num, "email": email, "error": "no auth.json", "active": False}
    
    if not force and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            # Require chat_gate so pre-probe caches are not treated as "正常".
            # Never reuse a failed shell (ok=false) as a warm cache hit.
            if (
                cached.get("ok") is True
                and _now() - float(cached.get("_fetched_at_ts", 0)) < GROK_TTL
                and "chat_gate" in cached
            ):
                cached["seat"] = seat_num
                cached["email"] = email
                cached["active"] = True
                return cached
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    
    auth = _read_json(auth_path)
    if not auth:
        return {"ok": False, "seat": seat_num, "email": email, "error": "invalid auth.json", "active": True}
    
    token = _auth_bearer_token(auth)
    if not token:
        return {"ok": False, "seat": seat_num, "email": email, "error": "no access token", "active": True}
    
    req = urllib.request.Request(
        GROK_BILLING_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "nexstatus/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = f"HTTP {e.code}"
        stale = _grok_seat_stale_fallback(cache_path, seat_num, email, err)
        if stale is not None:
            return stale
        return {"ok": False, "seat": seat_num, "email": email, "error": err, "active": True}
    except Exception as e:
        err = _safe_error(e)
        stale = _grok_seat_stale_fallback(cache_path, seat_num, email, err)
        if stale is not None:
            return stale
        return {"ok": False, "seat": seat_num, "email": email, "error": err, "active": True}
    
    cfg = body.get("config") if isinstance(body.get("config"), dict) else body
    used = _money_val(cfg.get("used"))
    api_limit = _money_val(cfg.get("monthlyLimit"))
    pool = _resolve_grok_monthly_pool(api_limit, history_path=history_path)
    limit = pool["monthly_limit"]
    pct_val = _grok_used_pct(used, limit)
    
    # Always pass this seat's history — default GROK_HISTORY is a different
    # account and will poison weekly deltas (G2 inflated / G3 floored to 0).
    weekly_fields = _grok_weekly_usage(cfg, history_path=history_path)
    if (
        not weekly_fields.get("weekly_available")
        or weekly_fields.get("weekly_source") != "api"
    ):
        weekly_fields = _grok_weekly_from_history(
            current_used=used,
            monthly_limit=limit,
            period_start=cfg.get("billingPeriodStart"),
            period_end=cfg.get("billingPeriodEnd"),
            history_path=history_path,
        )
        if pool["limit_missing"] and weekly_fields.get("weekly_available"):
            note = weekly_fields.get("weekly_note") or ""
            tag = "月上限軟估（API 未回）"
            weekly_fields["weekly_note"] = f"{note}；{tag}" if note else tag
    
    result = {
        "ok": True,
        "seat": seat_num,
        "email": email,
        "active": True,
        "source": GROK_BILLING_URL,
        "plan": GROK_PLAN_NAME,
        "price": f"${GROK_PLAN_PRICE_USD_MO:g}/mo",
        "used": used,
        "monthly_limit": limit,
        "monthly_limit_api": pool["monthly_limit_api"],
        "limit_missing": pool["limit_missing"],
        "limit_source": pool["limit_source"],
        "used_pct": pct_val,
        "on_demand_cap": _money_val(cfg.get("onDemandCap")),
        "period_start": cfg.get("billingPeriodStart"),
        "period_end": cfg.get("billingPeriodEnd"),
        "unit": "credits",
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
        **weekly_fields,
    }
    _annotate_grok_enforcement(result, token)
    
    # Persist raw API limit (0/null) so history_last_nonzero stays meaningful.
    _append_grok_billing_history_to(used, api_limit, history_path)
    try:
        _write_cache_json(cache_path, result)
    except OSError:
        pass
    return result


def grok_multi_seat_usage(force: bool = False) -> list[dict[str, Any]]:
    """Collect billing for all grok-seats (1-3)."""
    seats = []
    for n in (1, 2, 3):
        seats.append(_grok_seat_billing(n, force=force))
    return seats


def _money_val(v: Any) -> float | None:
    if isinstance(v, dict) and "val" in v:
        try:
            return float(v["val"])
        except (TypeError, ValueError):
            return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _read_env_key(path: Path, variable: str) -> str | None:
    """Read one dotenv-style credential without ever returning it to output."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        prefix = f"{variable}="
        if line.startswith(prefix):
            value = line[len(prefix):].strip().strip("'\"")
            return value or None
    # Some credential.d files contain only the key. Support that shape while
    # refusing to treat an unrelated multi-line document as a credential.
    if len(lines) == 1 and "=" not in lines[0] and lines[0].strip():
        return lines[0].strip().strip("'\"") or None
    return None


def _openrouter_key(seat: dict[str, Any]) -> str | None:
    """Resolve one OpenRouter key from its explicitly assigned local source."""
    variable = str(seat.get("variable") or "")
    path = seat.get("path")
    if not variable or not isinstance(path, Path):
        return None

    # The assigned file is the normal authority. An environment value is an
    # explicit override only when it has the shape of an OpenRouter key;
    # malformed launch-environment residue must never silently win.
    file_value = _read_env_key(path, variable)
    env_value = os.environ.get(variable)
    if _valid_openrouter_key(env_value):
        return env_value
    if _valid_openrouter_key(file_value):
        return file_value
    return None


def _valid_openrouter_key(value: Any) -> bool:
    if not isinstance(value, str) or not (20 <= len(value) <= 512):
        return False
    if not value.startswith("sk-or-") or not value.isascii():
        return False
    return not any(char.isspace() for char in value)


def _openrouter_key_source(seat: dict[str, Any], key: str | None) -> str | None:
    """Identify the redacted key source without exposing credential material."""
    if not _valid_openrouter_key(key):
        return None
    variable = str(seat.get("variable") or "")
    path = seat.get("path")
    if not variable or not isinstance(path, Path):
        return None
    if _valid_openrouter_key(os.environ.get(variable)) and os.environ.get(variable) == key:
        return "env"
    if _valid_openrouter_key(_read_env_key(path, variable)):
        return "file"
    return None


def _openrouter_empty_seat(
    seat_name: str,
    error: str,
    key_source: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "seat": seat_name,
        "key_source": key_source,
        "label": None,
        "account_credits": None,
        "account_usage": None,
        "account_remaining": None,
        "key_limit": None,
        "key_limit_remaining": None,
        "key_usage_monthly": None,
        "used_pct": None,
        "delta_today": None,
        "delta_7d": None,
        "daily_avg": None,
        "_fetched_at": None,
        "_fetched_at_ts": None,
        "error": error,
    }


def _openrouter_fetch_json(
    url: str,
    key: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "nexstatus/1.0",
        },
    )
    try:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("openrouter_deadline")
        timeout = OPENROUTER_TIMEOUT if deadline is None else _remaining(deadline, OPENROUTER_TIMEOUT)
        with urllib.request.urlopen(
            req,
            context=ssl.create_default_context(),
            timeout=timeout,
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001 — provider boundary is isolated below
        raise RuntimeError(_safe_error(exc)) from exc
    if not isinstance(body, dict):
        raise RuntimeError("invalid_response")
    return body


def _openrouter_history_rows(path: Path | None = None) -> list[dict[str, Any]]:
    actual_path = path if path is not None else OPENROUTER_HISTORY
    try:
        lines = actual_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _openrouter_usage_trends(
    seat: str,
    current_usage: float | None,
    history_path: Path | None = None,
    now_ts: float | None = None,
) -> dict[str, float | None]:
    """Calculate measured deltas only when history contains a real baseline.

    Today's baseline is the first prior sample in the current UTC day. The
    seven-day baseline must be at or before the seven-day cutoff; otherwise we
    deliberately return unknown instead of inventing a rate from current use.
    """
    empty: dict[str, float | None] = {
        "delta_today": None,
        "delta_7d": None,
        "daily_avg": None,
    }
    if current_usage is None:
        return empty
    now = float(_now() if now_ts is None else now_ts)
    rows: list[tuple[float, float]] = []
    for row in _openrouter_history_rows(history_path):
        if row.get("seat") != seat:
            continue
        try:
            ts = float(row.get("ts_unix"))
            usage = float(row.get("total_usage"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(ts) and math.isfinite(usage) and ts < now:
            rows.append((ts, usage))
    rows.sort(key=lambda item: item[0])

    today_start = datetime.fromtimestamp(now, timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp()
    today_rows = [item for item in rows if item[0] >= today_start]
    if today_rows:
        delta_today = float(current_usage) - today_rows[0][1]
        if delta_today >= 0:
            empty["delta_today"] = round(delta_today, 6)

    # A 7-day trend needs a measured sample near the 7-day boundary. A much
    # older sample is not a 7-day baseline and must remain unknown.
    window_start = now - 8 * 86400
    window_end = now - 6 * 86400
    baselines = [item for item in rows if window_start <= item[0] <= window_end]
    if baselines:
        delta = float(current_usage) - baselines[-1][1]
        if delta >= 0:
            empty["delta_7d"] = round(delta, 6)
            empty["daily_avg"] = round(delta / 7.0, 8)
    return empty


def _append_openrouter_history(
    seat: str,
    total_usage: float | None,
    usage_monthly: float | None,
    total_credits: float | None,
    ts: float | None = None,
    path: Path | None = None,
) -> None:
    """Append a redacted billing point and bound both record count and size."""
    if total_usage is None or total_credits is None:
        return
    actual_path = path if path is not None else OPENROUTER_HISTORY
    try:
        _ensure_cache_dir()
        timestamp = float(_now() if ts is None else ts)
        row = {
            "ts": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "ts_unix": timestamp,
            "seat": seat,
            "total_usage": float(total_usage),
            "usage_monthly": float(usage_monthly) if usage_monthly is not None else None,
            "total_credits": float(total_credits),
        }
        with actual_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        os.chmod(actual_path, 0o600)
        lines = actual_path.read_text(encoding="utf-8").splitlines()
        # 5-minute polling for two seats needs >4,000 rows for a 7-day
        # baseline. Keep a little headroom while still bounding local state.
        if len(lines) > 6000 or actual_path.stat().st_size > 1024 * 1024:
            kept: list[str] = []
            size = 0
            for line in reversed(lines):
                encoded_size = len((line + "\n").encode("utf-8"))
                if len(kept) >= 5000 or size + encoded_size > 900 * 1024:
                    break
                kept.append(line)
                size += encoded_size
            actual_path.write_text("\n".join(reversed(kept)) + "\n", encoding="utf-8")
            os.chmod(actual_path, 0o600)
    except OSError:
        pass


def openrouter_usage(
    force: bool = False,
    deadline: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Collect account and key billing for the configured OpenRouter seats."""
    if not force and OPENROUTER_CACHE.exists():
        cached = _read_json(OPENROUTER_CACHE)
        cache_fresh = True
        if not cached:
            cache_fresh = False
        else:
            for seat in OPENROUTER_SEATS:
                entry = cached.get(str(seat["seat"]))
                try:
                    fetched_ts = float(entry.get("_fetched_at_ts")) if isinstance(entry, dict) else 0.0
                except (TypeError, ValueError):
                    fetched_ts = 0.0
                if not isinstance(entry, dict) or _now() - fetched_ts >= OPENROUTER_TTL:
                    cache_fresh = False
                    break
        if cache_fresh:
            return cached  # type: ignore[return-value]

    result: dict[str, dict[str, Any]] = {}
    fetched_at_ts = _now()
    fetched_at = datetime.fromtimestamp(fetched_at_ts, timezone.utc).isoformat()
    total_deadline = time.monotonic() + OPENROUTER_TOTAL_DEADLINE
    if deadline is not None:
        total_deadline = min(total_deadline, deadline)
    for seat_cfg in OPENROUTER_SEATS:
        seat_name = str(seat_cfg.get("seat") or "unknown")
        now = time.monotonic()
        seat_deadline = min(total_deadline, now + OPENROUTER_SEAT_DEADLINE)
        key = _openrouter_key(seat_cfg)
        key_source = _openrouter_key_source(seat_cfg, key) or "unknown"
        if not key:
            result[seat_name] = _openrouter_empty_seat(seat_name, "missing_api_key", key_source=None)
            continue
        if seat_deadline - now <= OPENROUTER_MIN_REQUEST_BUDGET:
            result[seat_name] = _openrouter_empty_seat(
                seat_name,
                "deadline_exceeded",
                key_source=key_source,
            )
            continue
        try:
            try:
                credits_body = _openrouter_fetch_json(
                    OPENROUTER_CREDITS_URL,
                    key,
                    deadline=seat_deadline,
                )
                key_body = _openrouter_fetch_json(
                    OPENROUTER_KEY_URL,
                    key,
                    deadline=seat_deadline,
                )
            except RuntimeError as first_exc:
                fallback_key = None
                if str(first_exc) in {"HTTP 401", "HTTP 403"} and key_source == "env":
                    variable = str(seat_cfg.get("variable") or "")
                    path = seat_cfg.get("path")
                    if variable and isinstance(path, Path):
                        file_key = _read_env_key(path, variable)
                        if _valid_openrouter_key(file_key) and file_key != key:
                            fallback_key = file_key
                if fallback_key is None:
                    raise
                try:
                    credits_body = _openrouter_fetch_json(
                        OPENROUTER_CREDITS_URL,
                        fallback_key,
                        deadline=seat_deadline,
                    )
                    key_body = _openrouter_fetch_json(
                        OPENROUTER_KEY_URL,
                        fallback_key,
                        deadline=seat_deadline,
                    )
                except Exception:
                    raise first_exc
                key_source = "fallback"
            credits = credits_body.get("data")
            key_data = key_body.get("data")
            if not isinstance(credits, dict) or not isinstance(key_data, dict):
                raise RuntimeError("invalid_response")

            total_credits = _money_val(credits.get("total_credits"))
            total_usage = _money_val(credits.get("total_usage"))
            account_remaining = None
            if total_credits is not None and total_usage is not None:
                account_remaining = max(0.0, total_credits - total_usage)
            key_limit = _money_val(key_data.get("limit"))
            key_limit_remaining = _money_val(key_data.get("limit_remaining"))
            key_usage_monthly = _money_val(key_data.get("usage_monthly"))
            used_pct = None
            if total_credits is not None and total_credits > 0 and total_usage is not None:
                used_pct = _pct(100.0 * total_usage / total_credits)
            trends = _openrouter_usage_trends(
                seat_name,
                total_usage,
                now_ts=fetched_at_ts,
            )
            entry = {
                "ok": True,
                "seat": seat_name,
                "key_source": key_source,
                "label": key_data.get("label") if isinstance(key_data.get("label"), str) else None,
                "account_credits": total_credits,
                "account_usage": total_usage,
                "account_remaining": account_remaining,
                "key_limit": key_limit,
                "key_limit_remaining": key_limit_remaining,
                "key_usage_monthly": key_usage_monthly,
                "used_pct": used_pct,
                **trends,
                "_fetched_at": fetched_at,
                "_fetched_at_ts": fetched_at_ts,
            }
            result[seat_name] = entry
            _append_openrouter_history(
                seat_name,
                total_usage,
                key_usage_monthly,
                total_credits,
                ts=fetched_at_ts,
            )
        except RuntimeError as exc:
            result[seat_name] = _openrouter_empty_seat(seat_name, str(exc), key_source=key_source)
        except Exception as exc:  # noqa: BLE001 — one seat must not abort the other
            result[seat_name] = _openrouter_empty_seat(seat_name, _safe_error(exc), key_source=key_source)

    try:
        _write_cache_json(OPENROUTER_CACHE, result)
    except OSError:
        pass
    return result


def _opencode_key() -> str | None:
    for env in ("OPENCODE_ZEN_API_KEY", "OPENCODE_GO_API_KEY"):
        if os.environ.get(env):
            return os.environ[env]
    auth = _read_json(OPENCODE_AUTH)
    if auth and isinstance(auth.get("opencode"), dict):
        key = auth["opencode"].get("key")
        if isinstance(key, str) and key:
            return key
    # Optional dotenv-style files (never log contents)
    for path in (
        Path(os.path.expanduser("~/.config/nexstatus/env")),
        Path(os.path.expanduser("~/.config/opencode/.env")),
    ):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[7:]
                if line.startswith("OPENCODE_ZEN_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
        except OSError:
            continue
    return None


def _go_local_ledger() -> dict[str, Any]:
    """Local cost.db ledger for opencode-go-subscription (under-counts vs server)."""
    empty = {
        "req_5h": 0,
        "req_7d": 0,
        "req_30d": 0,
        "shadow_usd_5h": 0.0,
        "shadow_usd_7d": 0.0,
        "shadow_usd_30d": 0.0,
        "top_models_30d": [],
    }
    if not COST_DB.exists():
        return empty
    try:
        import sqlite3
        from datetime import timedelta

        con = sqlite3.connect(f"file:{COST_DB}?mode=ro", uri=True)
        now = datetime.now(timezone.utc)

        def window(hours: float) -> tuple[int, float]:
            since = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
            row = con.execute(
                """
                SELECT count(*), coalesce(sum(shadow_cost_usd), 0)
                FROM cost_events
                WHERE quota_source = 'opencode-go-subscription' AND ts >= ?
                """,
                (since,),
            ).fetchone()
            return int(row[0] or 0), float(row[1] or 0)

        r5, s5 = window(5)
        r7, s7 = window(24 * 7)
        r30, s30 = window(24 * 30)
        since30 = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
        tops = con.execute(
            """
            SELECT model, count(*)
            FROM cost_events
            WHERE quota_source = 'opencode-go-subscription' AND ts >= ?
            GROUP BY model ORDER BY count(*) DESC LIMIT 5
            """,
            (since30,),
        ).fetchall()
        con.close()
        return {
            "req_5h": r5,
            "req_7d": r7,
            "req_30d": r30,
            "shadow_usd_5h": round(s5, 4),
            "shadow_usd_7d": round(s7, 4),
            "shadow_usd_30d": round(s30, 4),
            "top_models_30d": [{"model": m, "count": c} for m, c in tops],
        }
    except Exception:  # noqa: BLE001
        empty["error"] = "ledger_unavailable"
        return empty


def _parse_go_reset_seconds(message: str) -> int | None:
    import re

    m = re.search(r"Resets in (\d+)\s*days?", message, re.I)
    if m:
        return int(m.group(1)) * 86400
    m = re.search(r"Resets in (\d+)\s*hours?", message, re.I)
    if m:
        return int(m.group(1)) * 3600
    m = re.search(r"Resets in (\d+)\s*minutes?", message, re.I)
    if m:
        return int(m.group(1)) * 60
    return None


def opencode_go_usage(force: bool = False) -> dict[str, Any]:
    """OpenCode Go ($10/mo) — $12/5h, $30/week, $60/month dollar caps.

    Live status via lightweight chat probe (cached). Local ledger is incomplete
    (missing cache tokens) so we never treat it as authoritative alone.
    """
    local = _go_local_ledger()
    caps = {
        "five_hour_usd": GO_CAP_5H_USD,
        "weekly_usd": GO_CAP_WEEK_USD,
        "monthly_usd": GO_CAP_MONTH_USD,
    }

    cached: dict[str, Any] | None = None
    if GO_CACHE.exists():
        try:
            cached = json.loads(GO_CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None

    if cached and not force:
        age = _now() - float(cached.get("_fetched_at_ts", 0))
        ttl = GO_TTL_CAPPED if cached.get("live_status") == "capped" else GO_TTL_OK
        if age < ttl:
            cached["local"] = local  # always refresh local numbers
            # recompute soft pct from local if not capped
            if cached.get("live_status") != "capped":
                cached["used_pct"] = _go_soft_pct(local)
                cached["approx"] = True
            return cached

    key = _opencode_key()
    if not key:
        return {
            "ok": False,
            "error": "no OPENCODE_ZEN_API_KEY / auth.json",
            "local": local,
            "caps": caps,
        }

    # Tiny probe — min model, 1 completion token
    payload = json.dumps(
        {
            "model": "minimax-m3",
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        GO_CHAT_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nexstatus/1.0",
        },
    )

    live_status = "unknown"
    limit_name = None
    message = None
    resets_in_sec = None
    used_pct: int | None = None
    http_code = None
    human_error = None

    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=20) as resp:
            http_code = resp.status
            _ = resp.read(200)
            live_status = "ok"
            used_pct = _go_soft_pct(local)
    except urllib.error.HTTPError as e:
        http_code = e.code
        body = b""
        try:
            body = e.read(800)
        except Exception:  # noqa: BLE001
            pass
        text = body.decode("utf-8", errors="replace")
        if e.code == 429 and "GoUsageLimitError" in text:
            live_status = "capped"
            used_pct = 100
            try:
                err = json.loads(text)
            except json.JSONDecodeError:
                err = {}
            error = (err.get("error") or {}) if isinstance(err, dict) else {}
            meta = (err.get("metadata") or {}) if isinstance(err, dict) else {}
            message = error.get("message") if isinstance(error, dict) else None
            limit_name = meta.get("limitName") if isinstance(meta, dict) else None
            if not limit_name and isinstance(message, str):
                low = message.lower()
                if "monthly" in low:
                    limit_name = "monthly"
                elif "weekly" in low or "week" in low:
                    limit_name = "weekly"
                elif "5 hour" in low or "five hour" in low:
                    limit_name = "five_hour"
            if isinstance(message, str):
                # Strip personal workspace links before caching/display
                import re as _re
                message = _re.sub(
                    r"https://opencode\.ai/workspace/[^\s]+",
                    "https://opencode.ai/workspace/…",
                    message,
                )
                resets_in_sec = _parse_go_reset_seconds(message)
            # Retry-After header (seconds) as fallback
            if resets_in_sec is None:
                ra = e.headers.get("Retry-After") if e.headers else None
                try:
                    if ra and int(ra) < 86400 * 40:
                        resets_in_sec = int(ra)
                except (TypeError, ValueError):
                    pass
        else:
            live_status = "error"
            try:
                err = json.loads(text)
            except json.JSONDecodeError:
                err = None
            nested_error = err.get("error") if isinstance(err, dict) else None
            if not isinstance(nested_error, dict):
                nested_error = {}
            error_type = err.get("type") if isinstance(err, dict) else None
            if not isinstance(error_type, str):
                error_type = nested_error.get("type")
            raw_message = err.get("message") if isinstance(err, dict) else None
            if not isinstance(raw_message, str):
                raw_message = nested_error.get("message")
            if not isinstance(raw_message, str) or not raw_message:
                raw_message = text.strip() if err is not None else None
            message = raw_message or f"HTTP {e.code}"
            if e.code == 401:
                if error_type == "CreditsError" or "insufficient balance" in message.lower():
                    human_error = "OpenCode Go 餘額不足，需儲值"
                else:
                    human_error = "OpenCode Go key 無效"
            else:
                human_error = f"OpenCode Go API 錯誤 HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        live_status = "error"
        message = _safe_error(e)
        human_error = "OpenCode Go 連線失敗（離線或逾時）"

    result = {
        "ok": live_status in ("ok", "capped"),
        "plan": "OpenCode Go",
        "price": "$10/mo",
        "live_status": live_status,
        "limit_name": limit_name,
        "used_pct": used_pct,
        "message": message,
        "error": human_error,
        "resets_in_sec": resets_in_sec,
        "http_code": http_code,
        "caps": caps,
        "local": local,
        "approx": live_status != "capped",
        "note": "官方額度以 $ 計（5h $12 / 週 $30 / 月 $60）。本機 ledger 常低估（缺 cache token）。"
        if live_status != "capped"
        else "官方回報額度已滿；可改用 free models 或 console 開 balance。",
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
    }
    try:
        _write_cache_json(GO_CACHE, result)
    except OSError:
        pass
    return result


def _go_soft_pct(local: dict[str, Any]) -> int:
    """Best-effort % from local shadow $ vs monthly cap (usually underestimates)."""
    s30 = float(local.get("shadow_usd_30d") or 0)
    s7 = float(local.get("shadow_usd_7d") or 0)
    s5 = float(local.get("shadow_usd_5h") or 0)
    # take max of window percentages so any tight window surfaces
    scores = [
        s5 / GO_CAP_5H_USD if GO_CAP_5H_USD else 0,
        s7 / GO_CAP_WEEK_USD if GO_CAP_WEEK_USD else 0,
        s30 / GO_CAP_MONTH_USD if GO_CAP_MONTH_USD else 0,
    ]
    return max(0, min(99, int(round(max(scores) * 100))))  # never claim 100 from soft


def host_metrics() -> dict[str, Any]:
    # _mem_info already folds CPU into pressure_pct and returns cpu_pct.
    info = _mem_info()
    try:
        info.update(_host_process_snapshot())
    except Exception:  # noqa: BLE001 — process sample must never abort host metrics
        info.setdefault("top_cpu", [])
        info.setdefault("top_mem", [])
        info.setdefault("top_families", [])
    return info


def _proc_short_name(raw: str) -> str:
    """Basename-only process label — no home paths or args.

    macOS paths often contain spaces (``Google Chrome.app/...``), so we cannot
    split on the first space. Prefer ``.app`` bundle names; otherwise strip
    flag-style argv (`` -x``) and take the path basename.
    """
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return "unknown"

    path_token = ""
    name = text
    if "/" in text or text.startswith("~"):
        app = re.search(r"/([^/]+)\.app/", text)
        if app:
            name = app.group(1)
            path_token = text
        else:
            # Drop common flag argv: " /path/bin --flag" or " /path/bin -c code"
            cut = re.split(r"\s+-", text, maxsplit=1)[0].strip()
            path_token = cut
            name = Path(cut).name or cut
    for suffix in (
        " Helper (Renderer)",
        " Helper (GPU)",
        " Helper (Plugin)",
        " Helper",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].rstrip() or name
    # Collapse noisy Python framework path leftovers.
    if name in {"Python", "python3", "python"} and path_token:
        parent = Path(path_token.split(None, 1)[0]).parent.name if path_token else ""
        # Prefer Xcode / project folder clues from the path.
        m = re.search(r"/([^/]+)/(?:bin|MacOS)/Python", path_token.replace("\\", "/"))
        if m and m.group(1) not in {".", "bin", "MacOS", "Versions"}:
            name = f"Python({m.group(1)})"
        elif parent and parent not in {".", "bin", "MacOS", "Versions"}:
            name = f"Python({parent})"
    return name[:48]


def _proc_family(name: str) -> str:
    low = name.lower()
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("本機模型", ("llama", "ollama", "mlx", "mlc", "vllm", "gpt-oss", "qwen")),
        ("AI CLI / 訂閱", ("claude", "codex", "chatgpt", "agy", "antigravity", "opencode", "grok", "hermes", "nexvoice", "nexpilot", "nexstatus", "fable")),
        ("瀏覽器", ("chrome", "chromium", "firefox", "safari", "webkit", "arc", "brave", "edge")),
        ("顯示 / UI", ("windowserver", "dock", "finder", "screencapture", "coregraphics")),
        ("容器 / VM", ("orbstack", "docker", "vpnkit", "qemu", "virtualization", "utm")),
        ("模擬器", ("simmetal", "simrender", "simulator", "coresimulator")),
        ("開發工具", ("node", "bun", "python", "swift", "xcode", "cmux", "cursor", "code", "electron", "java", "ruby", "go", "rustc", "cargo")),
        ("系統", ("kernel_task", "mds", "syspolicyd", "trustd", "coreaudiod", "assistantd", "siri", "cloudd", "bird", "photolibrary", "spotlight", "launchd")),
    ]
    for label, keys in rules:
        if any(k in low for k in keys):
            return label
    return "其他"


def _host_process_snapshot(limit_cpu: int = 8, limit_mem: int = 8, limit_families: int = 6) -> dict[str, Any]:
    """Cheap live top-process sample for the Mac detail sheet."""
    try:
        out = subprocess.check_output(
            ["/bin/ps", "-axo", "pid=,pcpu=,pmem=,rss=,command="],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.5,
        )
    except (OSError, subprocess.SubprocessError):
        return {"top_cpu": [], "top_mem": [], "top_families": []}

    rows: list[dict[str, Any]] = []
    self_pid = os.getpid()
    skip_names = frozenset({"ps", "top", "memory_pressure", "NexStatusMenuBar"})
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            cpu = float(parts[1])
            mem = float(parts[2])
            rss_kb = int(parts[3])
        except ValueError:
            continue
        if pid == self_pid:
            continue
        name = _proc_short_name(parts[4])
        if name in skip_names:
            continue
        rows.append(
            {
                "pid": pid,
                "name": name,
                "family": _proc_family(name),
                "cpu_pct": round(cpu, 1),
                "mem_pct": round(mem, 1),
                "rss_mb": round(rss_kb / 1024.0, 1),
            }
        )

    def _pack(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        packed: list[dict[str, Any]] = []
        for item in items:
            packed.append(
                {
                    "pid": item["pid"],
                    "name": item["name"],
                    "family": item["family"],
                    "cpu_pct": item["cpu_pct"],
                    "mem_pct": item["mem_pct"],
                    "rss_mb": item["rss_mb"],
                }
            )
        return packed

    top_cpu = _pack(sorted(rows, key=lambda r: r["cpu_pct"], reverse=True)[:limit_cpu])
    top_mem = _pack(sorted(rows, key=lambda r: r["rss_mb"], reverse=True)[:limit_mem])

    fam_cpu: dict[str, float] = {}
    fam_rss: dict[str, float] = {}
    for row in rows:
        fam = str(row["family"])
        fam_cpu[fam] = fam_cpu.get(fam, 0.0) + float(row["cpu_pct"])
        fam_rss[fam] = fam_rss.get(fam, 0.0) + float(row["rss_mb"])
    families = sorted(
        (
            {
                "name": name,
                "cpu_pct": round(cpu, 1),
                "rss_gb": round(fam_rss.get(name, 0.0) / 1024.0, 2),
            }
            for name, cpu in fam_cpu.items()
        ),
        key=lambda item: (item["rss_gb"], item["cpu_pct"]),
        reverse=True,
    )[:limit_families]

    top_mem_name = top_mem[0]["name"] if top_mem else None
    top_cpu_name = top_cpu[0]["name"] if top_cpu else None
    return {
        "top_cpu": top_cpu,
        "top_mem": top_mem,
        "top_families": families,
        "top_mem_name": top_mem_name,
        "top_cpu_name": top_cpu_name,
    }


def _cpu_pct() -> int:
    try:
        out = subprocess.check_output(
            ["/usr/bin/top", "-l", "1", "-n", "0", "-s", "0"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        if "CPU usage" in line:
            # CPU usage: 12.34% user, 5.67% sys, 81.99% idle
            parts = line.replace("%", " ").replace(",", " ").split()
            nums = []
            for p in parts:
                try:
                    nums.append(float(p))
                except ValueError:
                    continue
            if len(nums) >= 2:
                return max(0, min(100, int(round(nums[0] + nums[1]))))
    return 0


def _mem_info() -> dict[str, Any]:
    free_pct = 50.0
    try:
        out = subprocess.check_output(
            ["/usr/bin/memory_pressure"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        for line in out.splitlines():
            if "System-wide memory free percentage" in line:
                # ...: 46%
                tail = line.rsplit(":", 1)[-1].strip().rstrip("%")
                free_pct = float(tail)
                break
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    used_pct = max(0, min(100, int(round(100 - free_pct))))
    total = 0
    try:
        out = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "hw.memsize"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        total = int(out.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        total = 0
    total_gb = total / (1024**3) if total else 128.0
    used_gb = total_gb * used_pct / 100.0

    swap_mb = 0.0
    swap_total_mb = 0.0
    try:
        out = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        # total = 2048.00M  used = 123.40M  free = 1924.60M  (encrypted)
        parsed = re.search(
            r"total\s*=\s*([\d.]+)M.*?used\s*=\s*([\d.]+)M",
            out,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if parsed:
            swap_total_mb = float(parsed.group(1))
            swap_mb = float(parsed.group(2))
        elif "used" in out:
            after = out.split("used", 1)[1]
            token = after.replace("=", " ").split()[0]
            swap_mb = float(token.rstrip("M"))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        swap_mb = 0.0
        swap_total_mb = 0.0
    # Bar uses absolute pressure vs 16GB (AI-Mac soft ceiling), NOT used/total of
    # the encrypted swap file. After a thrash, macOS often keeps a large swap
    # file (total≈used) so used/total≈90% looks "full" even when free% recovered.
    swap_pct = int(min(100, round(100.0 * swap_mb / 16384.0))) if swap_mb > 0 else 0
    swap_pct = max(0, min(100, swap_pct))

    pressure = 0
    try:
        out = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        pressure = int(out.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        pressure = 0

    if pressure >= 4:
        p_label = "critical 🔴"
        level_score = 92
    elif pressure >= 2:
        p_label = "warning 🟡"
        level_score = 62
    else:
        p_label = "normal 🟢"
        level_score = 12

    cpu = _cpu_pct()
    # Single host-load index for MenuBar (hardware pressure, not AI quota weather).
    # Swap was under-weighted: 32–56GB compressed swap is common on AI Macs and
    # should move H more than the old flat +8 for any swap ≥2GB.
    pressure_pct = int(round(0.45 * used_pct + 0.25 * cpu + 0.30 * level_score))
    if swap_mb >= 32768:
        pressure_pct = min(100, pressure_pct + 22)
    elif swap_mb >= 16384:
        pressure_pct = min(100, pressure_pct + 16)
    elif swap_mb >= 8192:
        pressure_pct = min(100, pressure_pct + 12)
    elif swap_mb >= 2048:
        pressure_pct = min(100, pressure_pct + 8)
    elif swap_mb >= 512:
        pressure_pct = min(100, pressure_pct + 4)
    pressure_pct = max(0, min(100, pressure_pct))

    return {
        "cpu_pct": cpu,
        "mem_pct": used_pct,
        "mem_used_gb": round(used_gb, 1),
        "mem_total_gb": round(total_gb, 0),
        "swap_mb": round(swap_mb, 1),
        "swap_total_mb": round(swap_total_mb, 1),
        "swap_pct": swap_pct,
        "pressure": p_label,
        "pressure_level": pressure,
        "pressure_pct": pressure_pct,
    }


def _remaining(deadline: float, maximum: float) -> float:
    return max(0.05, min(maximum, deadline - time.monotonic()))


def _agy_process_allowed(comm: str, args: str = "") -> bool:
    """Accept only same-product Antigravity / agy process names or path markers."""
    name = Path(comm).name
    if name in AGY_COMM_NAMES:
        return True
    hay = f"{comm} {args}"
    return any(marker in hay for marker in AGY_PATH_MARKERS)


def _pgrep_pids(args: list[str], deadline: float) -> list[str]:
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_remaining(deadline, 1.0),
        ).split()[: AGY_MAX_PORTS * 3]
    except (OSError, subprocess.SubprocessError):
        return []


def _verified_agy_pids(deadline: float) -> list[str]:
    """Return a bounded list of same-user Antigravity / agy processes.

    Accepts CLI ``agy``, ``agy-node``, and the desktop app binary path so the
    local language server can be found more reliably than ``pgrep -x agy`` alone.
    """
    candidates: list[str] = []
    for cmd in (
        ["/usr/bin/pgrep", "-x", "agy"],
        ["/usr/bin/pgrep", "-x", "agy-node"],
        ["/usr/bin/pgrep", "-x", "Antigravity"],
        # Path-based fallback (still re-verified via ps uid + path markers).
        ["/usr/bin/pgrep", "-f", "Antigravity|agy-node|/bin/agy"],
    ):
        if time.monotonic() >= deadline:
            break
        for pid in _pgrep_pids(cmd, deadline):
            if pid not in candidates:
                candidates.append(pid)

    verified: list[str] = []
    for pid in candidates:
        if time.monotonic() >= deadline:
            break
        if len(verified) >= AGY_MAX_PORTS:
            break
        try:
            output = subprocess.check_output(
                ["/bin/ps", "-p", pid, "-o", "uid=", "-o", "comm=", "-o", "args="],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_remaining(deadline, 0.6),
            ).strip()
            # uid is first token; comm may contain spaces rarely — use ps fields carefully.
            parts = output.split(None, 2)
            if len(parts) < 2:
                continue
            uid_text, comm = parts[0], parts[1]
            args = parts[2] if len(parts) > 2 else ""
            if int(uid_text) != os.getuid():
                continue
            if not _agy_process_allowed(comm, args):
                continue
            verified.append(pid)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return verified


def _find_agy_listen_ports(deadline: float) -> list[int]:
    """Find bounded loopback listeners owned by a verified local agy process."""
    ports: list[int] = []
    for pid in _verified_agy_pids(deadline):
        if time.monotonic() >= deadline:
            break
        try:
            output = subprocess.check_output(
                [
                    "/usr/sbin/lsof",
                    "-nP",
                    "-a",
                    "-p",
                    pid,
                    "-iTCP",
                    "-sTCP:LISTEN",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_remaining(deadline, 0.8),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in output.splitlines():
            # Accept 127.0.0.1 and [::1] — Antigravity sometimes binds IPv6 loopback.
            host_port = None
            if "127.0.0.1:" in line and "LISTEN" in line:
                try:
                    host_port = int(line.split("127.0.0.1:", 1)[1].split()[0].split("->", 1)[0])
                except (ValueError, IndexError):
                    host_port = None
            elif "[::1]:" in line and "LISTEN" in line:
                try:
                    host_port = int(line.split("[::1]:", 1)[1].split()[0].split("->", 1)[0])
                except (ValueError, IndexError):
                    host_port = None
            if host_port is None:
                continue
            if 1024 <= host_port <= 65535 and host_port not in ports:
                ports.append(host_port)
                if len(ports) >= AGY_MAX_PORTS:
                    return ports
    return ports


def _agy_from_cache(max_age: float = AGY_STALE_TTL) -> dict[str, Any] | None:
    """Return last-known-good Antigravity snapshot within max_age, or None."""
    if not AGY_CACHE.exists():
        return None
    try:
        cached = json.loads(AGY_CACHE.read_text(encoding="utf-8"))
        if not isinstance(cached, dict) or cached.get("ok") is not True:
            return None
        age = _now() - float(cached.get("_fetched_at_ts", 0))
        if age < 0 or age > max_age:
            return None
        out = dict(cached)
        out["stale"] = age > AGY_TTL
        out["source"] = out.get("source") or "agy-cache"
        if out["stale"]:
            out["source"] = "agy-cache-stale"
        return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non_standard_json:{value}")


def _probe_agy_user_status(port: int, deadline: float) -> dict[str, Any] | None:
    """Read a bounded status response from a verified local Antigravity endpoint."""
    url = f"http://127.0.0.1:{port}{AGY_RPC}"
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "User-Agent": "nexstatus/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_remaining(deadline, 1.0)) as resp:
            chunks: list[bytes] = []
            total = 0
            while total <= AGY_MAX_RESPONSE_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError("agy_deadline")
                chunk = resp.read(min(8192, AGY_MAX_RESPONSE_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > AGY_MAX_RESPONSE_BYTES:
                return None
            body = json.loads(
                b"".join(chunks).decode("utf-8"),
                parse_constant=_reject_json_constant,
            )
            if isinstance(body, dict) and (
                "userStatus" in body or "planStatus" in body
            ):
                return body
    except Exception:  # noqa: BLE001
        return None
    return None


def antigravity_usage(force: bool = False) -> dict[str, Any]:
    """Antigravity CLI subscription quota via local language server GetUserStatus.

    Requires a running `agy` / Antigravity language-server session on loopback.
    Remote cloudcode-pa quota APIs are often PERMISSION_DENIED for CLI accounts;
    local probe is the supported path (same approach as CodexBar).

    When the process briefly exits (common), keep last-known-good values for
    AGY_STALE_TTL so the MenuBar does not flap to A—%%.
    """
    if not force:
        fresh = _agy_from_cache(max_age=AGY_TTL)
        if fresh is not None:
            return fresh

    deadline = time.monotonic() + AGY_TOTAL_DEADLINE
    ports = _find_agy_listen_ports(deadline)
    if not ports:
        stale = _agy_from_cache(max_age=AGY_STALE_TTL)
        if stale is not None:
            stale = dict(stale)
            stale["stale"] = True
            stale["source"] = "agy-cache-stale"
            stale["error"] = "agy_not_running_using_cache"
            return stale
        return {
            "ok": False,
            "error": "agy 未執行 — 開 Antigravity CLI 後會顯示用量",
            "hint": "local language server (GetUserStatus) only while agy is running",
        }

    body = None
    for port in ports:
        if time.monotonic() >= deadline:
            break
        body = _probe_agy_user_status(port, deadline)
        if body:
            break

    if not body:
        stale = _agy_from_cache(max_age=AGY_STALE_TTL)
        if stale is not None:
            stale = dict(stale)
            stale["stale"] = True
            stale["source"] = "agy-cache-stale"
            stale["error"] = "agy_status_unavailable_using_cache"
            return stale
        return {
            "ok": False,
            "error": "agy_status_unavailable",
        }

    us = body.get("userStatus") if isinstance(body.get("userStatus"), dict) else body
    plan_status = us.get("planStatus") if isinstance(us.get("planStatus"), dict) else {}
    plan_info = plan_status.get("planInfo") if isinstance(plan_status.get("planInfo"), dict) else {}
    plan_name = str(plan_info.get("planName") or us.get("userTier") or "—")[:80]

    models: list[dict[str, Any]] = []
    used_pcts: list[int] = []
    resets: list[str] = []
    cmcd = us.get("cascadeModelConfigData") if isinstance(us.get("cascadeModelConfigData"), dict) else {}
    configs = cmcd.get("clientModelConfigs") if isinstance(cmcd.get("clientModelConfigs"), list) else []
    truncated_models = len(configs) > AGY_MAX_MODELS
    for cfg in configs[:AGY_MAX_MODELS]:
        if not isinstance(cfg, dict):
            continue
        qi = cfg.get("quotaInfo") if isinstance(cfg.get("quotaInfo"), dict) else {}
        rem = qi.get("remainingFraction")
        used_pct = None
        if isinstance(rem, (int, float)) and math.isfinite(float(rem)):
            rem = max(0.0, min(1.0, float(rem)))
            used_pct = max(0, min(100, int(round((1.0 - rem) * 100))))
            used_pcts.append(used_pct)
        else:
            rem = None
        reset = qi.get("resetTime")
        if isinstance(reset, str) and reset:
            resets.append(reset)
        models.append(
            {
                "label": str(cfg.get("label") or cfg.get("modelOrAlias") or "model")[:80],
                "remaining_fraction": rem,
                "used_pct": used_pct,
                "reset_time": reset,
            }
        )

    # Primary chip: hottest model window (how full the tightest bucket is)
    session_used_pct = max(used_pcts) if used_pcts else 0
    # Credits (monthly pools when present)
    prompt_monthly = plan_info.get("monthlyPromptCredits")
    flow_monthly = plan_info.get("monthlyFlowCredits")
    prompt_avail = plan_status.get("availablePromptCredits")
    flow_avail = plan_status.get("availableFlowCredits")

    def finite_optional(value: Any) -> float | None:
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        return float(value)

    result = {
        "ok": True,
        "source": "agy-local",
        "plan": plan_name,
        "used_pct": session_used_pct,  # menubar A##%
        "session_used_pct": session_used_pct,
        "models": models,
        "models_truncated": truncated_models,
        "prompt_credits_available": finite_optional(prompt_avail),
        "prompt_credits_monthly": finite_optional(prompt_monthly),
        "flow_credits_available": finite_optional(flow_avail),
        "flow_credits_monthly": finite_optional(flow_monthly),
        "next_reset": min(resets) if resets else None,
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
    }
    try:
        _write_cache_json(AGY_CACHE, result)
    except OSError:
        pass
    return result


# ── AGY multi-seat (per-account) probing ─────────────────────────────────


def _agy_pid_to_seat(pid: str, deadline: float) -> int:
    """Read JETSKI_APP_DATA_DIR from a running agy process to identify the seat.

    Returns the seat number (0 = original, 1-4 = agy-account-N) or -1 if
    the env var is not readable or not in the known mapping.
    """
    try:
        env_output = subprocess.check_output(
            ["/bin/ps", "-p", pid, "-wwE"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_remaining(deadline, 0.6),
        )
        # Parse JETSKI_APP_DATA_DIR=<value> from the env dump
        for token in env_output.split():
            if token.startswith("JETSKI_APP_DATA_DIR="):
                data_dir = token.split("=", 1)[1].strip()
                return AGY_SEAT_DATA_DIRS.get(data_dir, -1)
        # No JETSKI_APP_DATA_DIR found → default agy (seat 0)
        return AGY_SEAT_DATA_DIRS.get("antigravity-cli", 0)
    except (OSError, subprocess.SubprocessError):
        return -1


def _find_agy_seat_ports(deadline: float) -> dict[int, list[int]]:
    """Map seat numbers to their listen ports.

    Returns {seat_num: [port, ...]} for all discovered agy processes.
    """
    seat_ports: dict[int, list[int]] = {}
    pid_seats: dict[str, int] = {}

    for pid in _verified_agy_pids(deadline):
        if time.monotonic() >= deadline:
            break
        seat = _agy_pid_to_seat(pid, deadline)
        if seat < 0:
            continue
        pid_seats[pid] = seat

    for pid, seat in pid_seats.items():
        if time.monotonic() >= deadline:
            break
        try:
            output = subprocess.check_output(
                [
                    "/usr/sbin/lsof",
                    "-nP",
                    "-a",
                    "-p",
                    pid,
                    "-iTCP",
                    "-sTCP:LISTEN",
                ],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=_remaining(deadline, 0.8),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        for line in output.splitlines():
            host_port = None
            if "127.0.0.1:" in line and "LISTEN" in line:
                try:
                    host_port = int(line.split("127.0.0.1:", 1)[1].split()[0].split("->", 1)[0])
                except (ValueError, IndexError):
                    host_port = None
            elif "[::1]:" in line and "LISTEN" in line:
                try:
                    host_port = int(line.split("[::1]:", 1)[1].split()[0].split("->", 1)[0])
                except (ValueError, IndexError):
                    host_port = None
            if host_port is None:
                continue
            if 1024 <= host_port <= 65535:
                seat_ports.setdefault(seat, [])
                if host_port not in seat_ports[seat]:
                    seat_ports[seat].append(host_port)
    return seat_ports


def _agy_seat_from_cache(seat_num: int, max_age: float = AGY_STALE_TTL) -> dict[str, Any] | None:
    """Return last-known-good per-seat Antigravity snapshot, or None."""
    if seat_num < 0 or seat_num >= len(AGY_SEAT_CACHES):
        return None
    cache_path = AGY_SEAT_CACHES[seat_num]
    if not cache_path.exists():
        return None
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cached, dict) or cached.get("ok") is not True:
            return None
        age = _now() - float(cached.get("_fetched_at_ts", 0))
        if age < 0 or age > max_age:
            return None
        out = dict(cached)
        out["stale"] = age > AGY_TTL
        if out["stale"]:
            out["source"] = "agy-seat-cache-stale"
        return out
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _agy_seat_label(seat_num: int) -> str:
    """Human-readable seat label: agy (default), agy1-agy4 (accounts)."""
    if seat_num == 0:
        return "agy"
    return f"agy{seat_num}"


def _agy_seat_probe(seat_num: int, ports: list[int], deadline: float, force: bool = False) -> dict[str, Any]:
    """Probe one agy seat's local language server and return a status dict.

    Follows the same pattern as _grok_seat_billing: per-seat cache, stale
    fallback, and email extraction from the live probe.
    """
    label = _agy_seat_label(seat_num)
    cache_path = AGY_SEAT_CACHES[seat_num] if 0 <= seat_num < len(AGY_SEAT_CACHES) else None

    # Check per-seat cache first (unless forced)
    if not force and cache_path is not None:
        cached = _agy_seat_from_cache(seat_num, max_age=AGY_TTL)
        if cached is not None:
            cached["seat"] = seat_num
            cached["label"] = label
            return cached

    # Live probe
    body = None
    for port in ports:
        if time.monotonic() >= deadline:
            break
        body = _probe_agy_user_status(port, deadline)
        if body:
            break

    if not body:
        stale = _agy_seat_from_cache(seat_num, max_age=AGY_STALE_TTL)
        if stale is not None:
            stale["seat"] = seat_num
            stale["label"] = label
            stale["stale"] = True
            stale["source"] = "agy-seat-cache-stale"
            return stale
        return {"ok": False, "seat": seat_num, "label": label, "error": "agy_seat_probe_failed", "active": True}

    # Parse the response (same logic as antigravity_usage)
    us = body.get("userStatus") if isinstance(body.get("userStatus"), dict) else body
    plan_status = us.get("planStatus") if isinstance(us.get("planStatus"), dict) else {}
    plan_info = plan_status.get("planInfo") if isinstance(plan_status.get("planInfo"), dict) else {}
    plan_name = str(plan_info.get("planName") or us.get("userTier") or "—")[:80]
    email = str(us.get("email") or "")[:120] or None

    models: list[dict[str, Any]] = []
    used_pcts: list[int] = []
    resets: list[str] = []
    cmcd = us.get("cascadeModelConfigData") if isinstance(us.get("cascadeModelConfigData"), dict) else {}
    configs = cmcd.get("clientModelConfigs") if isinstance(cmcd.get("clientModelConfigs"), list) else []
    for cfg in configs[:AGY_MAX_MODELS]:
        if not isinstance(cfg, dict):
            continue
        qi = cfg.get("quotaInfo") if isinstance(cfg.get("quotaInfo"), dict) else {}
        rem = qi.get("remainingFraction")
        used_pct = None
        if isinstance(rem, (int, float)) and math.isfinite(float(rem)):
            rem = max(0.0, min(1.0, float(rem)))
            used_pct = max(0, min(100, int(round((1.0 - rem) * 100))))
            used_pcts.append(used_pct)
        else:
            rem = None
        reset = qi.get("resetTime")
        if isinstance(reset, str) and reset:
            resets.append(reset)
        models.append(
            {
                "label": str(cfg.get("label") or cfg.get("modelOrAlias") or "model")[:80],
                "remaining_fraction": rem,
                "used_pct": used_pct,
                "reset_time": reset,
            }
        )

    session_used_pct = max(used_pcts) if used_pcts else 0
    prompt_monthly = plan_info.get("monthlyPromptCredits")
    flow_monthly = plan_info.get("monthlyFlowCredits")
    prompt_avail = plan_status.get("availablePromptCredits")
    flow_avail = plan_status.get("availableFlowCredits")

    def finite_optional(value: Any) -> float | None:
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            return None
        return float(value)

    result: dict[str, Any] = {
        "ok": True,
        "seat": seat_num,
        "label": label,
        "email": email,
        "active": True,
        "source": "agy-seat-local",
        "plan": plan_name,
        "used_pct": session_used_pct,
        "session_used_pct": session_used_pct,
        "models": models,
        "prompt_credits_available": finite_optional(prompt_avail),
        "prompt_credits_monthly": finite_optional(prompt_monthly),
        "flow_credits_available": finite_optional(flow_avail),
        "flow_credits_monthly": finite_optional(flow_monthly),
        "next_reset": min(resets) if resets else None,
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
    }
    if cache_path is not None:
        try:
            _write_cache_json(cache_path, result)
        except OSError:
            pass
    return result


def agy_multi_seat_usage(force: bool = False) -> list[dict[str, Any]]:
    """Collect status for all running agy seats (like grok_multi_seat_usage).

    Discovers running agy processes, identifies which account each belongs to
    via JETSKI_APP_DATA_DIR, probes each seat independently, and returns a
    list of per-seat status dicts.
    """
    deadline = time.monotonic() + AGY_TOTAL_DEADLINE
    seat_ports = _find_agy_seat_ports(deadline)

    seats: list[dict[str, Any]] = []
    seen: set[int] = set()
    for seat_num in sorted(seat_ports.keys()):
        if seat_num in seen:
            continue
        seen.add(seat_num)
        ports = seat_ports[seat_num]
        result = _agy_seat_probe(seat_num, ports, deadline, force=force)
        seats.append(result)

    # Also include stale cache entries for seats that are not currently running
    # but were recently active (mirrors grok-seat stale fallback behavior).
    for seat_num in range(AGY_MAX_SEATS + 1):
        if seat_num in seen:
            continue
        stale = _agy_seat_from_cache(seat_num, max_age=AGY_STALE_TTL)
        if stale is not None:
            stale["seat"] = seat_num
            stale["label"] = _agy_seat_label(seat_num)
            stale["stale"] = True
            stale["source"] = "agy-seat-cache-stale"
            stale["active"] = False
            seats.append(stale)

    return seats


def _safe_collect(label: str, function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Isolate optional collectors so one source cannot abort the snapshot."""
    try:
        result = function(*args, **kwargs)
        return result if isinstance(result, dict) else {"ok": False, "error": f"{label}_invalid"}
    except Exception:  # noqa: BLE001 — provider boundary must degrade safely
        return {"ok": False, "error": f"{label}_unavailable"}


def _menu_quota_pct(provider: dict[str, Any] | None) -> Any:
    """Prefer 5h quota for menu chips; fall back to 7d when 5h is unreported."""
    if not isinstance(provider, dict) or not provider.get("ok"):
        return None
    five = provider.get("five_hour_pct")
    if five is not None:
        return five
    return provider.get("seven_day_pct")


def build_snapshot(force_remote: bool = False) -> dict[str, Any]:
    collector_deadline = time.monotonic() + COLLECTOR_WATCHDOG_BUDGET_SECONDS
    host = _safe_collect("host", host_metrics)
    claude = _safe_collect("claude", claude_usage)
    codex = _safe_collect("codex", codex_usage)
    grok = _safe_collect("grok", grok_usage, force=force_remote)
    try:
        grok_seats = grok_multi_seat_usage(force=force_remote)
    except Exception:  # noqa: BLE001
        grok_seats = []
    openrouter = _safe_collect(
        "openrouter",
        openrouter_usage,
        force=force_remote,
        deadline=collector_deadline,
    )
    go = _safe_collect("opencode_go", opencode_go_usage, force=force_remote)
    agy = _safe_collect("antigravity", antigravity_usage, force=force_remote)
    try:
        agy_seats = agy_multi_seat_usage(force=force_remote)
    except Exception:  # noqa: BLE001
        agy_seats = []
    tokentracker = _safe_collect("tokentracker", tokentracker_usage)
    rag = _safe_collect("rag", rag_status)
    try:
        ledger = collect_ledger_summary(COST_DB)
        if not isinstance(ledger, dict):
            ledger = {"ok": False, "status": "error", "quality": {"warnings": ["ledger_invalid"]}}
    except Exception:  # noqa: BLE001 — ledger must never abort the snapshot
        ledger = {"ok": False, "status": "error", "quality": {"warnings": ["ledger_unavailable"]}}

    # Keep last live ledger only on transient read failures (busy/error), never when
    # the DB is simply missing — users without a ledger must see a clean empty state.
    if (
        not ledger.get("ok")
        and ledger.get("status") in {"busy", "error", "incompatible"}
        and OUT.is_file()
    ):
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            prev_ledger = previous.get("ledger") if isinstance(previous, dict) else None
            if isinstance(prev_ledger, dict) and prev_ledger.get("ok") is True:
                carried = dict(prev_ledger)
                quality = dict(carried.get("quality") or {})
                warnings = list(quality.get("warnings") or [])
                warnings.append("ledger_stale_carry")
                warnings.append(f"ledger_poll_{ledger.get('status')}")
                quality["warnings"] = list(dict.fromkeys(warnings))
                quality["stale"] = True
                if quality.get("level") == "ok":
                    quality["level"] = "warning"
                carried["quality"] = quality
                carried["carried_forward"] = True
                ledger = carried
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # Compact title pieces for MenuBar / logs.
    # Prefer short 5h window; fall back to 7d when a provider only reports weekly
    # (Codex currently often emits primary=7d with secondary=null).
    cl = _menu_quota_pct(claude)
    cx = _menu_quota_pct(codex)
    go_pct = go.get("used_pct") if go.get("ok") else None
    gk = grok.get("used_pct") if grok.get("ok") else None
    ag = agy.get("used_pct") if agy.get("ok") else None
    mem = host.get("mem_pct")
    host_load = host.get("pressure_pct")
    if host_load is None and isinstance(mem, (int, float)):
        cpu = host.get("cpu_pct") or 0
        host_load = int(round(0.55 * float(mem) + 0.45 * float(cpu)))

    def chip(letter: str, v: Any, bang_at: int | None = None) -> str:
        if v is None:
            return f"{letter}—%"
        mark = "!" if bang_at is not None and float(v) >= bang_at else ""
        return f"{letter}{mark}{int(v)}%"

    # C/G = AI quota (5h preferred, 7d fallback); H = computer pressure index
    title = " ".join(
        [
            chip("C", cl),
            chip("G", cx),
            chip("H", host_load, bang_at=80),
        ]
    )
    title_full = " ".join(
        [
            chip("C", cl),
            chip("G", cx),
            chip("Go", go_pct),
            chip("K", gk),
            chip("A", ag),
            chip("H", host_load, bang_at=80),
            chip("M", mem),
        ]
    )

    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": 2,
        "ok": True,
        "title": title,
        "title_full": title_full,
        "generated_at": generated_at,
        "polled_at": generated_at,
        "polled_at_ts": _now(),
        "host": host,
        "claude": claude,
        "codex": codex,
        "opencode_go": go,
        "grok": grok,
        "grok_seats": grok_seats,
        "openrouter": openrouter,
        "antigravity": agy,
        "agy_seats": agy_seats,
        "tokentracker": tokentracker,
        "rag": rag,
        "ledger": ledger,
    }


def main(argv: list[str]) -> int:
    force = "--force-grok" in argv or "--force-remote" in argv or "--force" in argv
    snap = build_snapshot(force_remote=force)
    _write_cache_json(OUT, snap)
    if "--print" in argv:
        print(json.dumps(snap, ensure_ascii=False, indent=2))
    else:
        print(snap.get("title", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
