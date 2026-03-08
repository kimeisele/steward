# Fix CI Failure
trigger: ci, failing, pipeline, github actions, workflow, lint, test failure
---
When CI fails:

1. Check which job failed: `gh run list --repo kimeisele/steward --limit 3`
2. Get failure logs: `gh run view <RUN_ID> --repo kimeisele/steward --log-failed | tail -50`
3. Common failures:
   - **Lint**: `ruff format steward/ tests/` then `ruff check --fix steward/ tests/`
   - **Tests**: `python -m pytest tests/ -x -v --timeout=30` to reproduce locally
   - **Import error**: Check `steward-protocol[providers]` is in CI install step
   - **Missing dependency**: Add to `pyproject.toml` optional-dependencies
4. Fix, commit, push. Watch CI again.

CI runs: Tests (3.11 + 3.12) + Lint. All three must pass.
Branch protection requires all 3 checks (admin can bypass).
