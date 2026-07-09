# Security

## Public surface

NexStatus is an **open-source, client-side** macOS utility. It does **not** run a cloud backend.

## Data handled at runtime

| Data | Where it lives | In git? | In snapshot JSON? |
|------|----------------|---------|-------------------|
| Claude usage % | `~/.claude/usage-status.json` | No | Yes (percent only) |
| Codex rate limits | `~/.codex/sessions/**/*.jsonl` | No | Yes (percent only) |
| OpenCode Go key | env / `~/.local/share/opencode/auth.json` | No | **No** |
| Grok OIDC token | `~/.grok/auth.json` | No | **No** |
| Host CPU / MEM | system APIs | No | Yes (metrics only) |

## Guarantees

1. **No secrets committed** — `.gitignore` excludes `.env`, `auth.json`, keys.
2. **No secrets in snapshot** — `~/.cache/nexstatus/status.json` stores usage percentages and host metrics only.
3. **Tokens only in memory** for remote probes (Grok billing, OpenCode Go light probe).
4. **Personal OpenCode workspace URLs** in error messages are redacted before cache/display.
5. **Optional ledger path** (`NEXSTATUS_COST_DB`) is local-only and never uploaded by NexStatus.

## Reporting a vulnerability

Please open a **private** security advisory on GitHub, or email the maintainer via the GitHub profile. Do not file public issues with live tokens or dumps.
