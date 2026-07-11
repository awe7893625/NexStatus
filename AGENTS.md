# NexStatus Project Contract

## Scope and stack

- Local-only macOS MenuBar utility.
- Runtime: Python 3 standard library collector plus Hammerspoon Lua/WebView.
- Public repository: never commit real account data, auth material, private paths, billing dumps, or personal usage snapshots.

## Commands

```bash
python3 -m py_compile nexstatus/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 nexstatus/collector.py --print
git diff --check
```

If Lua tooling is unavailable, validate through Hammerspoon with synthetic fixtures only. Do not claim a Lua smoke passed from visual inspection alone.

## Data contract

- Optional ledger source defaults to `~/.claude/state/cost.db` (override with `NEXSTATUS_COST_DB`).
- NexStatus opens SQLite with `mode=ro`; no migration, DDL, insert, update, or delete belongs in the runtime collector.
- Cash, fixed commitment, allocation, shadow value, and quota pressure are separate measures. Never add shadow value to cash.
- Unknown, missing, stale, unverified, and measured zero are distinct states. Never coerce unknown data to zero or a green status.
- Multi-machine ledgers group by the `machine` field; unlabelled rows stay `unknown`.

## Protected paths and privacy

- Never read or print secret values from Grok, OpenCode, Claude, Codex, or other auth files.
- Cache and snapshot directories must be owner-only (`0700`); files must be owner-only (`0600`).
- Snapshots must not contain bearer tokens, cookies, authorization headers, full account identifiers, private absolute session paths, raw SQL, raw exception text, or unrelated local port inventories.
- External API URLs remain fixed HTTPS destinations with normal certificate validation.
- WebView strings must be escaped before HTML insertion; bridge actions remain allowlisted.

## Git and delivery

- Work on a feature branch; prefer ordinary commits and `git revert` for rollback.
- Before a commit or release: run unit tests, syntax checks, `git diff --check`, and a secret scan.
- Do not commit `.env`, `auth.json`, cache dumps, or personal machine paths.
