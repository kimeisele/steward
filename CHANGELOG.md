# Changelog

All notable changes to steward-agent will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.17.0] - 2026-03-15

### Added
- PreciseSilentExceptRemedy — steward-owned Shuddhi remedy that classifies exception types before transforming (46 tests)
- ThinkTool — neuro-symbolic reasoning bridge: LLM calls `think(hypothesis, action)` and gets structured feedback from Antahkarana (13 tests)
- `py.typed` marker (PEP 561) for type checker support
- Security scanning (bandit) in CI pipeline
- DevContainer configuration for GitHub Codespaces
- Makefile with standard targets (install, test, lint, format, security, check, clean)

### Changed
- CI lint rules now enforce full ruff config (was only checking crash-level errors)
- Single source of truth for version — pyproject.toml reads from `steward.__version__`
- Steward-owned remedies loaded into Shuddhi engine via `add_remedy_path()`

### Fixed
- 46 unused imports removed across 77 files (F401 was suppressed in ruff config)
- ThinkTool Gandha pattern detection was dead code (always None)
- `_build_system_prompt()` had 4 vestigial parameters
- `_get_cetana()` was always returning None (dead code path)
- `_atomic_write()` had a double-close bug
- Test fixture duplication: 39 duplicate Fake classes consolidated into `tests/fakes.py` (-376 lines)

### Removed
- F401 (unused import) suppression in ruff config — dead code is now visible

## [0.16.0] - 2026-03

### Added
- Federation relay for cross-repo coordination via GitHub API
- Diamond service activation
- WCFA services: L0 intent, Ouroboros, SikSasTakam
- CLAUDE.md auto-regeneration from live context (MOKSHA hook)
- Targeted heartbeat delivery to known federation peers

### Changed
- Briefing system refactored to pure formatter (zero hardcoded content)
- Context bridge as single source of truth for CLAUDE.md content
