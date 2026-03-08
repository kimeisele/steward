# Commit and Push
trigger: commit, push, git, save changes
---
When committing and pushing changes:

1. Run tests first: `python -m pytest tests/ -x -q --timeout=30`
2. Run lint: `ruff format --check steward/ tests/ && ruff check steward/ tests/ --select=E9,F63,F7,F82`
3. Stage specific files (never `git add -A`): `git add <files>`
4. Write a clear commit message with Co-Authored-By trailer
5. Push: `git push origin main`
6. Watch CI: `gh run list --repo kimeisele/steward --limit 1`

Never commit .env files, credentials, or __pycache__/.
Never use --no-verify or --force.
