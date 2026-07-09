# Contributing to NexStatus

Thanks for helping make NexStatus better.

## Dev setup

```bash
git clone https://github.com/awe7893625/NexStatus.git
cd NexStatus
./scripts/install.sh
```

Requires:

- macOS
- [Hammerspoon](https://www.hammerspoon.org/)
- Python 3.10+ (`/usr/bin/python3` is fine)

## Layout

| Path | Role |
|------|------|
| `nexstatus/collector.py` | Gathers Claude / Codex / OpenCode Go / Grok / host metrics → JSON |
| `hammerspoon/nexstatus.lua` | MenuBar title + glass popover UI |
| `scripts/install.sh` | Symlink + Hammerspoon init hook |

## Principles

1. **No secrets on disk in the snapshot.** Tokens stay in-memory for API calls only.
2. **Never invent usage numbers.** Prefer official files/APIs; label estimates as approx.
3. **Keep the MenuBar short.** Details belong in the glass panel.
4. **macOS Tahoe-safe drawing.** Prefer Hammerspoon `hs.menubar` for titles (native `NSStatusItem` text is unreliable on Tahoe).

## Useful commands

```bash
# Snapshot only
python3 nexstatus/collector.py --print

# Force remote refresh (Grok billing + OpenCode Go probe)
python3 nexstatus/collector.py --print --force

# Reload UI after lua edits
hs -c 'hs.reload()'
```

## Pull requests

- Small, focused diffs
- Update README if user-facing behavior changes
- Do not commit API keys, `auth.json`, or personal paths outside `~/…` examples

## License

By contributing, you agree your contributions are licensed under the MIT License.
