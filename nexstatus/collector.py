#!/usr/bin/env python3
"""NexStatus collector — Claude / Codex / OpenCode Go / Grok / host metrics.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from nexstatus.ledger import collect_ledger_summary
except ModuleNotFoundError:  # direct ``python nexstatus/collector.py`` execution
    from ledger import collect_ledger_summary

CACHE_DIR = Path(os.environ.get("NEXSTATUS_CACHE", os.path.expanduser("~/.cache/nexstatus")))
OUT = CACHE_DIR / "status.json"
GROK_CACHE = CACHE_DIR / "grok-billing.json"
GO_CACHE = CACHE_DIR / "opencode-go.json"
CLAUDE_CACHE = CACHE_DIR / "claude-usage.json"
CLAUDE_STATUS = Path(os.path.expanduser("~/.claude/usage-status.json"))
CLAUDE_LEGACY = Path(os.path.expanduser("~/.claude/usag-status.json"))
CLAUDE_TT = Path(os.path.expanduser("~/.claude/tt-status.json"))
CODEX_SESSIONS = Path(os.path.expanduser("~/.codex/sessions"))
GROK_AUTH = Path(os.path.expanduser("~/.grok/auth.json"))
OPENCODE_AUTH = Path(os.path.expanduser("~/.local/share/opencode/auth.json"))
COST_DB = Path(os.environ.get("NEXSTATUS_COST_DB", os.path.expanduser("~/.claude/state/cost.db")))
GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing"
GO_CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
GROK_TTL = 5 * 60  # seconds — billing is monthly, no need to hammer API
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
AGY_MAX_PORTS = 4
AGY_MAX_MODELS = 12
AGY_MAX_RESPONSE_BYTES = 256 * 1024
AGY_TOTAL_DEADLINE = 4.0
# Process names / path fragments that legitimately host the Antigravity LS.
AGY_COMM_NAMES = frozenset({"agy", "agy-node", "Antigravity", "antigravity"})
AGY_PATH_MARKERS = (
    "/Antigravity/",
    "/antigravity/",
    "/bin/agy",
    "agy-node",
)
KNOWN_CACHE_FILES = (OUT, GROK_CACHE, GO_CACHE, AGY_CACHE, CLAUDE_CACHE)


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
            return {
                "ok": True,
                "source": "codex-session",
                "five_hour_pct": _pct(primary.get("used_percent")),
                "seven_day_pct": _pct(secondary.get("used_percent")),
                "five_hour_resets_at": primary.get("resets_at"),
                "seven_day_resets_at": secondary.get("resets_at"),
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


def _grok_weekly_usage(cfg: dict[str, Any]) -> dict[str, Any]:
    """Extract consumer weekly-pool fields without persisting account details."""
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
    return {
        "weekly_used_pct": used_pct,
        "weekly_used": used,
        "weekly_limit": limit,
        "weekly_reset_at": reset_at,
        "weekly_breakdown": breakdown,
        "weekly_available": used_pct is not None or reset_at is not None or bool(breakdown),
    }


def grok_usage(force: bool = False) -> dict[str, Any]:
    # Prefer short-lived cache so MenuBar refresh doesn't hit network every 2s
    if not force and GROK_CACHE.exists():
        try:
            cached = json.loads(GROK_CACHE.read_text(encoding="utf-8"))
            if _now() - float(cached.get("_fetched_at_ts", 0)) < GROK_TTL:
                return cached
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    auth = _read_json(GROK_AUTH)
    if not auth:
        return {"ok": False, "error": "no ~/.grok/auth.json — run grok login"}

    token = None
    for entry in auth.values():
        if isinstance(entry, dict) and entry.get("key"):
            token = entry["key"]
            break
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
    limit = _money_val(cfg.get("monthlyLimit"))
    pct = None
    if used is not None and limit and limit > 0:
        pct = max(0, min(100, int(round(100.0 * used / limit))))

    result = {
        "ok": True,
        "source": GROK_BILLING_URL,
        "used": used,
        "monthly_limit": limit,
        "used_pct": pct,
        "on_demand_cap": _money_val(cfg.get("onDemandCap")),
        "period_start": cfg.get("billingPeriodStart"),
        "period_end": cfg.get("billingPeriodEnd"),
        "unit": "credits",
        "_fetched_at": datetime.now(timezone.utc).isoformat(),
        "_fetched_at_ts": _now(),
        **_grok_weekly_usage(cfg),
    }
    try:
        _write_cache_json(GROK_CACHE, result)
    except OSError:
        pass
    return result


def _money_val(v: Any) -> float | None:
    if isinstance(v, dict) and "val" in v:
        try:
            return float(v["val"])
        except (TypeError, ValueError):
            return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


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
            message = f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        live_status = "error"
        message = _safe_error(e)

    result = {
        "ok": live_status in ("ok", "capped"),
        "plan": "OpenCode Go",
        "price": "$10/mo",
        "live_status": live_status,
        "limit_name": limit_name,
        "used_pct": used_pct,
        "message": message,
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
    return _mem_info()


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
    try:
        out = subprocess.check_output(
            ["/usr/sbin/sysctl", "-n", "vm.swapusage"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        # ... used = 123.4M ...
        for part in out.replace("=", " ").split():
            if part.endswith("M") and part[:-1].replace(".", "", 1).isdigit():
                # take the "used" one — crude: largest M value after "used"
                pass
        if "used" in out:
            after = out.split("used", 1)[1]
            token = after.replace("=", " ").split()[0]
            swap_mb = float(token.rstrip("M"))
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        swap_mb = 0.0

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
    pressure_pct = int(round(0.45 * used_pct + 0.25 * cpu + 0.30 * level_score))
    if swap_mb >= 2048:
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


def _safe_collect(label: str, function: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Isolate optional collectors so one source cannot abort the snapshot."""
    try:
        result = function(*args, **kwargs)
        return result if isinstance(result, dict) else {"ok": False, "error": f"{label}_invalid"}
    except Exception:  # noqa: BLE001 — provider boundary must degrade safely
        return {"ok": False, "error": f"{label}_unavailable"}


def build_snapshot(force_remote: bool = False) -> dict[str, Any]:
    host = _safe_collect("host", host_metrics)
    claude = _safe_collect("claude", claude_usage)
    codex = _safe_collect("codex", codex_usage)
    grok = _safe_collect("grok", grok_usage, force=force_remote)
    go = _safe_collect("opencode_go", opencode_go_usage, force=force_remote)
    agy = _safe_collect("antigravity", antigravity_usage, force=force_remote)
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

    # Compact title pieces for MenuBar / logs
    cl = claude.get("five_hour_pct") if claude.get("ok") else None
    cx = codex.get("five_hour_pct") if codex.get("ok") else None
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

    # C/G = AI 5h quota; H = computer pressure index (not AI weather score)
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
        "antigravity": agy,
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
