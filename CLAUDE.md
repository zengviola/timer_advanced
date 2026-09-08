# timer_advanced

A single-file app (`index.html`) deployed via GitHub Pages from `origin/master`. The user tests changes by viewing the **deployed site**, not the local file — uncommitted or unpushed local edits are invisible to them and will cause confusing mismatches between what Claude changed and what the user sees.

## Workflow rules

- **Always commit and push after making changes**, without asking for confirmation first. This is standing authorization for this repo specifically.
- Before starting work each session, make sure local `master` is up to date with `origin/master` (`git fetch` + fast-forward) — this repo has previously drifted far behind (39 commits) because local edits were made without first syncing, causing work to be built on a stale base.
