# timer_advanced

A single-file app (`index.html`) deployed via GitHub Pages from `origin/master`. The user tests changes by viewing the **deployed site**, not the local file — uncommitted or unpushed local edits are invisible to them and will cause confusing mismatches between what Claude changed and what the user sees.

## Workflow rules

- **Always commit and push after making changes**, without asking for confirmation first. This is standing authorization for this repo specifically.
- Before starting work each session, make sure local `master` is up to date with `origin/master` (`git fetch` + fast-forward) — this repo has previously drifted far behind (39 commits) because local edits were made without first syncing, causing work to be built on a stale base.
- `index.html` shows a version tag next to the title (`<span class="app-version">v70</span>`) so the user can tell whether their browser has picked up the latest deploy vs. an old cached/open tab. Every commit that changes `index.html` must bump this number by 1 — set it to `git rev-list --count HEAD` + 1 (i.e. what the new commit's count will be) right before committing.
