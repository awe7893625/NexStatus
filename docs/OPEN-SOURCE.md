# Open-sourcing NexStatus

NexStatus is a **local, client-side** macOS MenuBar app. Contributors and users run it on their own machines and connect their own Claude / Codex / OpenCode / Grok accounts. Nothing is uploaded by NexStatus.

## Suggested GitHub setup

1. Create a public repo (or use the existing one).
2. Scan before every push:

```bash
rg -n 'sk-|api[_-]?key|Bearer |eyJ|/Users/[a-zA-Z]' --glob '!**/.git/**' .
python3 -m unittest discover -s tests -v
```

3. Push only product sources (`nexstatus/`, `hammerspoon/`, `scripts/`, `docs/`, tests, README). Never push local cache, auth files, or internal work packets.

## What users connect themselves

| Source | Typical local input (examples) |
|--------|--------------------------------|
| Claude | `~/.claude/usage-status.json` |
| Codex | `~/.codex/sessions/**/*.jsonl` |
| Grok | `~/.grok/auth.json` (token used in-memory only) |
| OpenCode Go | `~/.local/share/opencode/auth.json` |
| Optional ledger | `NEXSTATUS_COST_DB` or `~/.claude/state/cost.db` |

None of these files belong in git. Each user supplies their own.

## What must stay out of the public tree

- API keys, OAuth tokens, cookies, `auth.json`
- Live `status.json` / billing dumps from a real machine
- Internal orchestration folders (e.g. `.workflow/`)
- Absolute home-directory paths to private projects

See [SECURITY.md](SECURITY.md) for runtime guarantees.
