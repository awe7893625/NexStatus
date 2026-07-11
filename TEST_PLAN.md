# NexStatus Cost Ledger v1 Test Plan

## Scope

This plan covers the first production increment: a read-only canonical-ledger summary, collector integration, cache/privacy hardening, and the Hammerspoon dashboard refresh. Tests use synthetic fixtures only; no fixture may copy real local account, billing, task, session, or machine data.

## Automated tests

### Ledger query contract

- Valid minimal `cost_events` database returns contract version 1.
- Missing database returns `status=missing` without a private path.
- Missing required table returns `status=incompatible`.
- Busy/locked database returns `status=busy` and does not break other collectors.
- Missing optional amortization view preserves cash/shadow totals and reports allocation as unknown.
- Taipei month boundaries include/exclude UTC events correctly.
- Unknown quota sources remain in the unknown bucket.
- Null machine remains unknown and is not attributed to the current Mac.
- Event and token totals are conserved across class, machine, and source groupings.
- Cash, fixed commitment, allocation, and shadow value remain separate.
- The SQLite database remains byte-for-byte unchanged after every test.

### Snapshot and privacy contract

- Ledger failure never removes existing Claude, Codex, Grok, OpenCode Go, Antigravity, or host sections.
- Snapshot has a schema version and generation time.
- Unknown values serialize as null/unknown, never measured zero.
- Recursive denylist rejects token, key, cookie, authorization, bearer, auth payload, raw SQL, private absolute session paths, and unrelated port inventories.
- Cache directory mode is `0700`; generated JSON files are `0600` even when a permissive umask is active.
- Atomic replacement preserves the required file mode.
- Remote error text is normalized before persistence.

### Installer

- Repository paths containing whitespace and quotes are encoded as valid Lua strings.
- Existing unrelated `init.lua` content survives installation.
- Re-running install is idempotent.
- Rollback removes only the NexStatus block and symlink.

## UI fixtures

Render at least these synthetic snapshots:

1. Normal ledger with M4 and M5 rows.
2. Missing ledger.
3. Stale ledger with unknown quota and missing machine.
4. Fixed commitment not verified.
5. Old snapshot without a ledger section.

For each fixture verify:

- Four summary metrics, machine evidence, priority sources, and data-quality banner.
- Unknown displays as `—` or `待補證`, never `$0` or green.
- No tofu/missing Chinese glyphs.
- Minimum supporting text size 11px.
- No root overflow at 380×820.
- Reduced motion and reduced transparency fallbacks.
- Single-source refresh does not blank or rebuild unrelated content.

## Commands

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile nexstatus/*.py tests/*.py
git diff --check
python3 nexstatus/collector.py --print
```

Hammerspoon/Lua verification must record the command, fixture, observed result, and screenshot path. If no Lua parser or UI runtime is available, mark that check blocked rather than passed.

## Release gate

Release fails if any invariant is violated, any real private data enters fixtures, a secret-like value enters a snapshot, the canonical DB changes during a read test, old snapshots crash the panel, or the security audit has an unresolved MEDIUM-or-higher finding.
