# MyFantasyFootball — repo rules

## Git concurrency (IMPORTANT)

Multiple Claude sessions and Task Scheduler automations (9am consensus-ADP pull,
betting-lines scan) commit to this checkout concurrently. Assume another
session's uncommitted work may be sitting on disk at any moment.

- **Work in your worktree.** Desktop-app sessions get an isolated worktree under
  `.claude/worktrees/` automatically — do repo edits there and merge back
  through the app. Only edit this main checkout when the user explicitly points
  you at paths here, and then follow the staging rules below.
- **Never stage broadly** in the main checkout: no `git add -A`, `git add .`,
  `git add -u`, `git add --all`, no `git commit -a`/`-am`. (`.claude/settings.json`
  denies these.) Stage the exact files you changed, nothing else.
- **Before committing**, run `git status --short`. If files you did not edit
  this session are modified, leave them unstaged and tell the user — they
  belong to another session.
- **`?v=` cache-bust bumps in index.html collide across sessions.** Read the
  current value from disk immediately before bumping; never assume the value
  you saw earlier is still current.
