"""
GitHub CLI wrapper with rate limiting and graceful degradation.

Provides GhClient — a rate-limited wrapper around the `gh` CLI tool.
Auto-detects when `gh` is unavailable and falls back to offline mode
(all subsequent calls return None instantly, zero subprocess overhead).

Extracted from agent-city's gh_rate.py + pr_lifecycle.py patterns.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger("STEWARD.SENSE.GH")

# Rate limit constants (from agent-city)
_MAX_PER_MINUTE = 30
_BACKOFF_SECONDS = (30, 60, 120)  # exponential backoff tiers
_RATE_LIMIT_CODES = ("403", "rate limit", "secondary rate")


@dataclass
class GhClient:
    """Rate-limited gh CLI wrapper.

    Singleton via get_gh_client(). Handles:
    - Sliding window rate limiting (30 calls/min)
    - Exponential backoff on 403/429
    - Auto-offline on FileNotFoundError (gh not installed)
    - Graceful degradation: always returns None on failure
    """

    max_per_minute: int = _MAX_PER_MINUTE
    _call_times: deque[float] = field(default_factory=deque)
    _backoff_until: float = 0.0
    _backoff_step: int = 0
    _offline: bool = False
    _total_calls: int = 0
    _throttled_calls: int = 0

    def call(self, args: list[str], timeout: int = 15) -> str | None:
        """Run gh CLI command. Returns stdout or None on failure/throttle."""
        if self._offline:
            return None

        now = time.monotonic()

        # Check backoff
        if now < self._backoff_until:
            self._throttled_calls += 1
            return None

        # Sliding window rate limit
        while self._call_times and self._call_times[0] < now - 60:
            self._call_times.popleft()
        if len(self._call_times) >= self.max_per_minute:
            self._throttled_calls += 1
            logger.debug("Rate limited: %d calls in last 60s", len(self._call_times))
            return None

        # Execute
        self._total_calls += 1
        self._call_times.append(now)

        try:
            result = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            logger.info("gh CLI not found — switching to offline mode")
            self._offline = True
            return None
        except subprocess.TimeoutExpired:
            logger.warning("gh %s timed out after %ds", " ".join(args[:3]), timeout)
            return None

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if any(code in stderr.lower() for code in _RATE_LIMIT_CODES):
                self._trigger_backoff()
                return None
            logger.debug("gh %s failed (rc=%d): %s", " ".join(args[:3]), result.returncode, stderr[:200])
            return None

        # Success — reset backoff
        self._backoff_step = 0
        return result.stdout.strip()

    def call_json(self, args: list[str], timeout: int = 15) -> dict | list | None:
        """call() + JSON parse. Returns None on parse failure."""
        raw = self.call(args, timeout=timeout)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse JSON from gh %s", " ".join(args[:3]))
            return None

    @property
    def is_available(self) -> bool:
        """gh CLI is installed and not in backoff."""
        return not self._offline

    def stats(self) -> dict:
        """Diagnostics for observability."""
        return {
            "total_calls": self._total_calls,
            "throttled_calls": self._throttled_calls,
            "offline": self._offline,
            "backoff_step": self._backoff_step,
            "is_available": self.is_available,
        }

    def _trigger_backoff(self) -> None:
        """Exponential backoff: 30s → 60s → 120s."""
        step = min(self._backoff_step, len(_BACKOFF_SECONDS) - 1)
        wait = _BACKOFF_SECONDS[step]
        self._backoff_until = time.monotonic() + wait
        self._backoff_step += 1
        self._throttled_calls += 1
        logger.warning("GitHub rate limit hit — backing off %ds (step %d)", wait, self._backoff_step)


# Singleton
_client: GhClient | None = None


def get_gh_client() -> GhClient:
    """Get the shared GhClient singleton."""
    global _client
    if _client is None:
        _client = GhClient()
    return _client


def _reset_gh_client() -> None:
    """Reset singleton (for test isolation only)."""
    global _client
    _client = None
