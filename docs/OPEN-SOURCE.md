# Open-sourcing NexStatus

## Suggested GitHub setup

1. Create a **public** repo named `NexStatus` (or `nexstatus`).
2. Do **not** force-push secrets. Run a quick scan:

```bash
rg -n 'sk-|api[_-]?key|Bearer |eyJ' --glob '!**/.git/**' .
```

3. Push:

```bash
cd /path/to/NexStatus
git init
git add .
git commit -m "Initial release: NexStatus MenuBar for AI usage + host metrics"
git branch -M main
git remote add origin git@github.com:awe7893625/NexStatus.git
git push -u origin main
```

Public repo (live): **https://github.com/awe7893625/NexStatus**  
GitHub Pages (live): **https://awe7893625.github.io/NexStatus/**

Topics: `macos`, `menubar`, `hammerspoon`, `claude`, `codex`, `grok`, `opencode`, `status`.

## What stays private on the author’s machine

Rain’s personal paths (`~/Developer/M5Load`, Hammerspoon NexVoice, cost.db ledgers) are **not** required for NexStatus. The open repo is self-contained under `NexStatus/`.

Legacy experiments may remain in `~/Developer/M5Load` but are not part of the OSS tree.
