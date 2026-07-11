# Security

## Public surface

NexStatus is an **open-source, client-side** macOS utility. It does **not** run a cloud backend.

## Data handled at runtime

| Data | Where it lives | In git? | In snapshot JSON? |
|------|----------------|---------|-------------------|
| Claude usage | local Claude status source | No | Yes (redacted usage, reset and model metadata) |
| Codex rate limits | local Codex session source | No | Yes (redacted quota, reset and plan metadata) |
| OpenCode Go key | env / `~/.local/share/opencode/auth.json` | No | **No** |
| Grok OIDC token | `~/.grok/auth.json` | No | **No** |
| Host CPU / MEM | system APIs | No | Yes (metrics only) |
| Token ledger | `~/.claude/state/cost.db` (read-only) | No | Yes (today/3/7/30-day platform, local-compute and project aggregates) |

## Guarantees

1. **No secrets committed** — `.gitignore` excludes `.env`, `auth.json`, keys.
2. **No secrets in snapshot** — `~/.cache/nexstatus/status.json` stores redacted operational metadata and aggregates, never bearer tokens or raw private source paths.
3. **Tokens only in memory** for remote probes (Grok billing, OpenCode Go light probe).
4. **Personal OpenCode workspace URLs** in error messages are redacted before cache/display.
5. **Optional ledger path** (`NEXSTATUS_COST_DB`) is local-only and never uploaded by NexStatus. Project labels are truncated, HTML-escaped at render time, and remain only in the owner-only local snapshot.
6. **API key attribution is anonymized** — raw `api_key_id` values are used only in memory for equality grouping. The snapshot contains sequential labels such as `Key 01`; it contains neither raw IDs, key material, nor key-derived digests.
7. **Owner-only cache** — the cache directory is forced to `0700`; known JSON files are atomically written and forced to `0600`.
8. **Bounded optional probes** — local Antigravity discovery is restricted to same-user exact-process listeners, with deadlines, response/model caps and last-known-good fallback.

## Reporting a vulnerability

Please open a **private** security advisory on GitHub, or email the maintainer via the GitHub profile. Do not file public issues with live tokens or dumps.
