# Rollback Plan

## Scope

Safe rollback for ledger / panel / installer changes without touching user secrets or rewriting git history on a public branch.

## Commit boundaries

Prefer small reversible commits:

1. Ledger query core + unit tests
2. Collector integration + cache/privacy hardening
3. Installer escaping/permission hardening + tests
4. Hammerspoon UI changes
5. Docs and acceptance notes

## Rollback order

1. Revert UI first — provider cards must still open.
2. Revert collector integration next — Claude/Codex/Grok/host must still snapshot.
3. Revert ledger core last — it is read-only and must not leave DB migrations behind.
4. Revert installer changes independently if install regresses.

Use `git revert <commit>`. Avoid force-push on shared public branches unless maintainers explicitly agree.

## Runtime rollback

- Panel tolerates snapshots with no `ledger` section.
- Collector tolerates a missing ledger module and keeps other providers alive.
- If the new panel fails, hide the ledger presentation without writing to the ledger database.
- Installer rollback removes only the delimited NexStatus load block and its symlink.

## Data safety

- No schema migration or write path against the user’s ledger DB.
- Cache/snapshot files under the NexStatus cache directory are disposable derived data.
