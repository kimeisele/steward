# Development Workflow — Steward

## Why this exists
The Steward lives in its own repo: a heartbeat mechanism periodically commits
`.steward/` state and rebases against `main`. Working on features directly inside
the runtime clone therefore causes HEAD/refs to move under you, and agent-reported
commits/pushes may be silently lost. This document is the hard-won rule set.

## Rules
1. **Never do feature work in the runtime clone** (`/Users/ss/projects/steward`).
   Use a separate real `git clone` (own `.git`, true quarantine — not a worktree,
   which shares `.git`).
2. **Verify the baseline before writing code**, per `ci.yml`:
   `pip install steward-protocol[providers]` → `pip install -e ".[providers,search,api,dev]"`
   → `pytest`. Know which tests are already red on `main` before you start.
3. **Always double-verify state changes independently.** After `git commit`, run
   `git log --oneline -1`. After `git push`, run `git ls-remote origin | grep <branch>`.
   Never trust an agent's success message for commit/push.
4. **Deliver via Pull Request**, never direct-push to `main`.
