"""Tests for steward/gaps.py — GapTracker."""

from __future__ import annotations

import time

import pytest

from steward.gaps import Gap, GapTracker


class TestGapTracker:
    """Test GapTracker."""

    def setup_method(self):
        self.tracker = GapTracker()

    def test_record_gap(self):
        self.tracker.record("tool", "Cannot search the web")
        assert len(self.tracker) == 1

    def test_deduplication(self):
        self.tracker.record("tool", "Cannot search the web")
        self.tracker.record("tool", "Cannot search the web")
        assert len(self.tracker) == 1

    def test_different_gaps(self):
        self.tracker.record("tool", "Cannot search the web")
        self.tracker.record("skill", "No deploy skill")
        assert len(self.tracker) == 2

    def test_record_tool_failure(self):
        self.tracker.record_tool_failure("web_search", "API key not set")
        assert len(self.tracker) == 1
        gap = self.tracker.active_gaps()[0]
        assert gap.category == "tool"
        assert "web_search" in gap.description

    def test_tool_failure_filters_noise(self):
        """User errors (file not found, permission) should not be recorded."""
        self.tracker.record_tool_failure("read_file", "File not found: /tmp/x")
        assert len(self.tracker) == 0

    def test_record_missing_skill(self):
        self.tracker.record_missing_skill("deploy to kubernetes")
        assert len(self.tracker) == 1
        gap = self.tracker.active_gaps()[0]
        assert gap.category == "skill"

    def test_record_provider_gap(self):
        self.tracker.record_provider_gap("streaming", "No provider supports streaming")
        assert len(self.tracker) == 1

    def test_resolve_gap(self):
        self.tracker.record("tool", "Cannot search the web")
        assert len(self.tracker) == 1
        resolved = self.tracker.resolve("Cannot search the web", "Installed tavily-python")
        assert resolved
        assert len(self.tracker) == 0  # active_gaps excludes resolved

    def test_resolve_nonexistent(self):
        assert not self.tracker.resolve("nonexistent gap")

    def test_format_for_prompt(self):
        self.tracker.record("tool", "Cannot search the web")
        self.tracker.record("skill", "No deploy skill")
        text = self.tracker.format_for_prompt()
        assert "## Known Capability Gaps" in text
        assert "search the web" in text
        assert "deploy skill" in text

    def test_format_empty(self):
        assert self.tracker.format_for_prompt() == ""

    def test_stats(self):
        self.tracker.record("tool", "Gap A")
        self.tracker.record("skill", "Gap B")
        self.tracker.resolve("Gap A", "Fixed")
        stats = self.tracker.stats
        assert stats["total_tracked"] == 2
        assert stats["active"] == 1
        assert stats["resolved"] == 1
        assert stats["by_category"]["skill"] == 1

    def test_serialization(self):
        self.tracker.record("tool", "Gap A")
        self.tracker.record("skill", "Gap B")
        data = self.tracker.to_dict()
        assert len(data) == 2

        # Restore
        new_tracker = GapTracker()
        new_tracker.load_from_dict(data)
        assert len(new_tracker) == 2

    def test_max_gaps_fifo(self):
        for i in range(25):
            self.tracker.record("tool", f"Gap {i}")
        assert len(self.tracker._gaps) <= 20

    def test_expired_gaps_pruned(self):
        gap = Gap(
            category="tool",
            description="Old gap",
            context="",
            timestamp=time.time() - (80 * 3600),  # 80 hours ago (> 72h expiry)
        )
        self.tracker._gaps.append(gap)
        active = self.tracker.active_gaps()
        assert len(active) == 0
