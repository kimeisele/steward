# Release a New Version
trigger: release, version, bump, pypi, publish, tag
---
To release a new version of steward-agent:

1. Bump version in TWO places:
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `steward/__init__.py` → `__version__ = "X.Y.Z"`
2. Commit: `git commit -m "chore: bump to vX.Y.Z"`
3. Push: `git push origin main`
4. Wait for CI to pass: `gh run list --repo kimeisele/steward --limit 1`
5. Tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
6. Tag push triggers publish.yml → tests → build → PyPI upload (Trusted Publishers)
7. Verify: `pip index versions steward-agent`

The version must match in both files. Tag must start with `v`.
