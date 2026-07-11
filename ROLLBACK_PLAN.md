# NexStatus Cost Ledger v1 Rollback Plan

## Baseline

- Branch: `feat/nexstatus-cost-ledger-v3`
- Preserved pre-delivery checkpoint: `2cffe04`
- Project contract checkpoint: `467dd85`
- No push, release, live Hammerspoon install, signing, notarization, or GitHub Pages deployment is authorized by this plan.

## Commit boundaries

Keep implementation in reversible commits:

1. Ledger query core and its unit tests.
2. Collector integration and cache/privacy hardening.
3. Installer escaping/permission hardening and tests.
4. Hammerspoon information architecture and visual changes.
5. Acceptance/security-only test adjustments.

Do not squash these boundaries before acceptance.

## Rollback order

1. Revert the UI commit first. Existing snapshots and provider cards must remain usable.
2. Revert collector integration next. The existing provider collectors must continue to produce the legacy snapshot.
3. Revert ledger core last. It is read-only and must not leave migrations or database state behind.
4. Revert installer changes independently if live-install behavior regresses.

Use ordinary `git revert <commit>`. Do not use destructive reset, force-push, history rewriting, or broad checkout commands.

## Runtime rollback

- The panel must tolerate snapshots with no `ledger` section.
- The collector must tolerate a missing ledger module/feature flag and keep existing providers alive.
- Keep the old snapshot path and prefs schema during the first increment.
- If a new panel fails, disable the ledger/summary presentation without modifying `cost.db`.
- If an install test touched an isolated Hammerspoon config, remove only the delimited NexStatus load block and its symlink.

## Data safety

The first increment performs no schema migration and no write to `cost.db`. A rollback therefore never edits, restores, or replaces the canonical ledger. Cache/snapshot files are disposable derived data; delete them only after confirming they are under the isolated NexStatus cache directory.

## Rollback evidence

For each rollback drill record:

- commit reverted;
- command and exit status;
- collector smoke result;
- legacy snapshot compatibility result;
- Git status;
- any remaining files or manual action.
