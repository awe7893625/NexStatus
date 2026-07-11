# NexStatus Project Contract

## Scope and stack

- Local-only macOS MenuBar utility.
- Runtime: Python 3 standard library collector plus Hammerspoon Lua/WebView.
- Public repository: never commit real account data, auth material, task descriptions, machine-private paths, billing records, or snapshots from Rain's machines.

## Commands

```bash
python3 -m py_compile nexstatus/*.py tests/*.py
python3 -m unittest discover -s tests -v
python3 nexstatus/collector.py --print
git diff --check
```

If Lua tooling is unavailable, validate through Hammerspoon in an isolated fixture configuration and record that evidence. Do not claim a Lua smoke passed from visual inspection alone.

## Data contract

- `~/.claude/state/cost.db` is the only canonical ledger/query SSOT.
- `task-resource-ledger.jsonl` is an append-only ingest/evidence/DR source, never a UI or financial-total query source.
- NexStatus opens SQLite with `mode=ro`; no migration, DDL, trigger, index, insert, update, or delete belongs in the runtime collector.
- Cash, fixed commitment, managerial allocation, shadow value, and quota pressure are separate measures. Never add shadow value to cash/effective cost.
- Unknown, missing, stale, unverified, and measured zero are distinct states. Never coerce unknown data to zero or a green status.
- Cross-machine records distinguish origin/dispatch host from compute host when the schema supports them. One inference must not be counted once on M4 and again on M5.

## Protected paths and privacy

- Never read or print secret values from Grok, OpenCode, Claude, Codex, or other auth files.
- Cache and snapshot directories must be owner-only (`0700`); files must be owner-only (`0600`).
- Snapshot/cache data must not contain bearer tokens, cookies, authorization headers, full account identifiers, private absolute session paths, raw SQL, raw exception text, or a list of unrelated local ports.
- External API URLs remain fixed HTTPS destinations with normal certificate validation. No user-controlled URL fetching.
- WebView snapshot strings must be escaped before HTML insertion; bridge actions remain allowlisted and must not become arbitrary Lua or shell dispatch.
- The installer modifies `~/.hammerspoon/init.lua`; changes require escaping tests and an explicit rollback path.

## Git and delivery

- Work one task per branch. Do not work directly on `main`.
- Preserve unrelated user changes. Use ordinary commits and `git revert` for rollback; no destructive reset, history rewrite, force-push, publish, or release without Rain approval.
- Before a commit or release: run unit tests, syntax checks, `git diff --check`, secret scan, fixture snapshot denylist, and the scoped security gate.
- Do not push, publish GitHub Pages, sign/notarize, email, or install into the live Hammerspoon config unless the task explicitly authorizes that external effect.
