"""Local integrations for NexStatus: TokenTracker and RAG status.

Provides read-only status metrics for local TokenTracker queue log and RAG HTTP server.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_QUEUE_FILE_SIZE = 64 * 1024 * 1024  # 64 MiB
MAX_LINE_BYTES = 64 * 1024  # 64 KiB
MAX_HTTP_RESPONSE_BYTES = 64 * 1024  # 64 KiB
HTTP_TIMEOUT_SECONDS = 1.5

ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
REQUIRED_FIELDS = (
    "source",
    "model",
    "hour_start",
    "total_tokens",
    "conversation_count",
)
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), _NoRedirectHandler()
)


def _get_tz() -> ZoneInfo:
    try:
        return ZoneInfo("Asia/Taipei")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def tokentracker_usage(
    queue_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    tz = _get_tz()
    if now is None:
        now_dt = datetime.now(timezone.utc).astimezone(tz)
    else:
        if now.tzinfo is None:
            now_dt = now.replace(tzinfo=tz)
        else:
            now_dt = now.astimezone(tz)

    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    r7d_cutoff = now_dt - timedelta(days=7)
    r30d_cutoff = now_dt - timedelta(days=30)
    future_limit = now_dt + timedelta(hours=1)

    if queue_path is None:
        env_path = os.environ.get("NEXSTATUS_TOKENTRACKER_QUEUE")
        if env_path:
            queue_path = Path(env_path)
        else:
            queue_path = Path.home() / ".tokentracker" / "tracker" / "queue.jsonl"

    res: dict[str, Any] = {
        "source": "tokentracker-local",
        "service": "TokenTracker",
        "status": "missing",
        "ok": False,
        "error": "tokentracker_missing",
        "warnings": [],
        "malformed_rows": 0,
        "today": {"tokens": 0, "conversations": 0},
        "rolling_7d": {"tokens": 0, "conversations": 0},
        "rolling_30d": {"tokens": 0, "conversations": 0},
        "sources_30d": [],
        "last_bucket_at": None,
        "is_live": False,
        "is_stale": True,
    }

    if not queue_path.exists() or not queue_path.is_file():
        return res

    try:
        file_size = queue_path.stat().st_size
    except Exception:
        res["status"] = "unavailable"
        res["error"] = "tokentracker_unavailable"
        return res

    if file_size > MAX_QUEUE_FILE_SIZE:
        res["status"] = "incompatible"
        res["error"] = "tokentracker_oversized"
        return res

    try:
        with open(queue_path, "rb") as f:
            content = f.read(MAX_QUEUE_FILE_SIZE + 1)
        if len(content) > MAX_QUEUE_FILE_SIZE:
            res["status"] = "incompatible"
            res["error"] = "tokentracker_oversized"
            return res
        lines_bytes = content.splitlines()
    except Exception:
        res["status"] = "unavailable"
        res["error"] = "tokentracker_unavailable"
        return res

    valid_buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    malformed_count = 0

    for raw_line in lines_bytes:
        if len(raw_line) > MAX_LINE_BYTES:
            malformed_count += 1
            continue

        try:
            line_str = raw_line.decode("utf-8")
            data = json.loads(line_str)
        except Exception:
            malformed_count += 1
            continue

        if not isinstance(data, dict):
            malformed_count += 1
            continue

        # Must strictly have required fields
        if not all(k in data for k in REQUIRED_FIELDS):
            malformed_count += 1
            continue

        source = data["source"]
        model = data["model"]
        hour_start = data["hour_start"]
        total_tokens = data["total_tokens"]
        conversation_count = data["conversation_count"]

        if (
            not isinstance(source, str)
            or not isinstance(model, str)
            or not isinstance(hour_start, str)
        ):
            malformed_count += 1
            continue

        if not SOURCE_RE.match(source):
            malformed_count += 1
            continue

        if len(model) == 0 or len(model) > 128:
            malformed_count += 1
            continue

        if len(hour_start) > 40:
            malformed_count += 1
            continue

        if type(total_tokens) is not int or type(conversation_count) is not int:
            malformed_count += 1
            continue

        if (
            total_tokens < 0
            or total_tokens > 10**15
            or conversation_count < 0
            or conversation_count > 10**9
        ):
            malformed_count += 1
            continue

        try:
            hs = hour_start.replace("Z", "+00:00") if hour_start.endswith("Z") else hour_start
            dt_bucket = datetime.fromisoformat(hs)
            if dt_bucket.tzinfo is None:
                malformed_count += 1
                continue
            dt_bucket = dt_bucket.astimezone(tz)
        except Exception:
            malformed_count += 1
            continue

        if dt_bucket > future_limit:
            continue

        key = (source, model, hour_start)
        valid_buckets[key] = {
            "source": source,
            "model": model,
            "hour_start": hour_start,
            "dt": dt_bucket,
            "tokens": total_tokens,
            "conversations": conversation_count,
        }

    if malformed_count > 0:
        res["malformed_rows"] = malformed_count
        res["warnings"].append("tokentracker_malformed_rows")

    if not valid_buckets:
        res["status"] = "incompatible"
        res["error"] = "tokentracker_malformed"
        return res

    res["ok"] = True
    res["error"] = None

    last_dt: datetime | None = None

    sources_30d_map: dict[str, dict[str, int]] = {}

    for bucket in valid_buckets.values():
        dt = bucket["dt"]
        tokens = bucket["tokens"]
        convs = bucket["conversations"]
        src = bucket["source"]

        if last_dt is None or dt > last_dt:
            last_dt = dt

        if dt >= today_start:
            res["today"]["tokens"] += tokens
            res["today"]["conversations"] += convs

        if dt >= r7d_cutoff:
            res["rolling_7d"]["tokens"] += tokens
            res["rolling_7d"]["conversations"] += convs

        if dt >= r30d_cutoff:
            res["rolling_30d"]["tokens"] += tokens
            res["rolling_30d"]["conversations"] += convs

            if src not in sources_30d_map:
                sources_30d_map[src] = {"tokens": 0, "conversations": 0}
            sources_30d_map[src]["tokens"] += tokens
            sources_30d_map[src]["conversations"] += convs

    if last_dt is not None:
        last_dt_utc = last_dt.astimezone(timezone.utc)
        res["last_bucket_at"] = last_dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        age_seconds = (now_dt - last_dt).total_seconds()
        if age_seconds <= 24 * 3600:
            res["is_live"] = True
            res["is_stale"] = False
            res["status"] = "live"
        else:
            res["is_live"] = False
            res["is_stale"] = True
            res["status"] = "stale"

    sorted_sources = sorted(
        sources_30d_map.items(),
        key=lambda item: (-item[1]["tokens"], -item[1]["conversations"], item[0]),
    )[:12]

    res["sources_30d"] = [
        {"id": k, "tokens": v["tokens"], "conversations": v["conversations"]}
        for k, v in sorted_sources
    ]

    return res


def _validate_and_parse_url(base_url: str | None) -> tuple[str | None, str | None]:
    if base_url is None:
        base_url = os.environ.get("NEXSTATUS_RAG_BASE_URL", "http://127.0.0.1:8220")

    try:
        parsed = urllib.parse.urlparse(base_url)
        port = parsed.port
    except Exception:
        return None, "rag_invalid_url"

    if parsed.scheme != "http":
        return None, "rag_invalid_url"

    if parsed.username is not None or parsed.password is not None:
        return None, "rag_invalid_url"

    if parsed.query or parsed.fragment:
        return None, "rag_invalid_url"

    hostname = parsed.hostname
    if not hostname:
        return None, "rag_invalid_url"

    hostname_clean = hostname.strip("[]")
    if hostname_clean not in ALLOWED_LOOPBACK_HOSTS:
        return None, "rag_invalid_url"

    path = parsed.path
    if path not in ("", "/"):
        return None, "rag_invalid_url"

    host_for_url = "[::1]" if hostname_clean == "::1" else hostname
    port_part = f":{port}" if port is not None else ""
    clean_base = f"http://{host_for_url}{port_part}"
    return clean_base, None


def rag_status(base_url: str | None = None) -> dict[str, Any]:
    res: dict[str, Any] = {
        "source": "loopback-http",
        "service": "Hybride PageIndex RAG",
        "status": "offline",
        "ok": False,
        "error": None,
        "latency_ms": None,
        "inventory_status": "unavailable",
        "documents": {
            "total": 0,
            "completed": 0,
            "queued": 0,
            "processing": 0,
            "failed": 0,
        },
    }

    clean_base, err_code = _validate_and_parse_url(base_url)
    if err_code:
        res["status"] = "invalid_config"
        res["error"] = "rag_invalid_url"
        return res

    health_url = f"{clean_base}/api/health"

    req = urllib.request.Request(
        health_url,
        headers={"Accept": "application/json", "User-Agent": "NexStatus/1.0"},
        method="GET",
    )

    t0 = time.monotonic()
    try:
        with _NO_REDIRECT_OPENER.open(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            latency = (time.monotonic() - t0) * 1000
            content = resp.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(content) > MAX_HTTP_RESPONSE_BYTES:
                res["status"] = "offline"
                res["error"] = "rag_invalid_response"
                return res
            data = json.loads(content.decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        res["status"] = "offline"
        res["error"] = "rag_unavailable"
        return res
    except Exception:
        res["status"] = "offline"
        res["error"] = "rag_invalid_response"
        return res

    if not isinstance(data, dict) or data.get("status") != "ok":
        res["status"] = "offline"
        res["error"] = "rag_invalid_response"
        return res

    res["status"] = "online"
    res["ok"] = True
    res["latency_ms"] = round(latency, 2)

    docs_url = f"{clean_base}/api/documents?latest_only=true"
    docs_req = urllib.request.Request(
        docs_url,
        headers={"Accept": "application/json", "User-Agent": "NexStatus/1.0"},
        method="GET",
    )

    try:
        with _NO_REDIRECT_OPENER.open(docs_req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            content = resp.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if len(content) <= MAX_HTTP_RESPONSE_BYTES:
                docs_data = json.loads(content.decode("utf-8"))
                if isinstance(docs_data, list):
                    counts = {
                        "total": len(docs_data),
                        "completed": 0,
                        "queued": 0,
                        "processing": 0,
                        "failed": 0,
                    }
                    for item in docs_data:
                        st = None
                        if isinstance(item, str):
                            st = item
                        elif isinstance(item, dict) and "status" in item:
                            st = str(item["status"])
                        if st in counts:
                            counts[st] += 1
                    res["documents"] = counts
                    res["inventory_status"] = "live"
                else:
                    res["inventory_status"] = "unavailable"
            else:
                res["inventory_status"] = "unavailable"
    except Exception:
        res["inventory_status"] = "unavailable"

    return res
