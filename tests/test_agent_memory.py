"""Tests for agent_memory — persistence of synaptic weights, chitta, gaps, sessions."""

from __future__ import annotations

from unittest.mock import MagicMock

from steward.agent_memory import (
    load_chitta,
    load_gaps,
    load_synaptic,
    record_session_ledger,
    record_session_stats,
    save_chitta,
    save_gaps,
    save_synaptic,
)


def _make_memory(data: dict | None = None) -> MagicMock:
    """Create a fake MemoryProtocol that returns data on recall."""
    mem = MagicMock()
    mem.recall.return_value = data
    return mem


def _make_synaptic() -> MagicMock:
    """Create a fake HebbianSynaptic with a _weights dict."""
    syn = MagicMock()
    syn._weights = {}
    syn.weights = property(lambda self: self._weights)
    return syn


# ── Synaptic Persistence ──────────────────────────────────────────────


class TestSynapticPersistence:
    def test_load_restores_weights(self):
        mem = _make_memory({"w1": 0.8, "w2": 0.3})
        syn = _make_synaptic()
        load_synaptic(mem, syn)
        assert syn._weights == {"w1": 0.8, "w2": 0.3}

    def test_load_no_data_is_noop(self):
        mem = _make_memory(None)
        syn = _make_synaptic()
        load_synaptic(mem, syn)
        assert syn._weights == {}

    def test_save_persists_weights(self):
        mem = _make_memory()
        syn = _make_synaptic()
        syn._weights = {"a": 0.5, "b": 0.9}
        save_synaptic(mem, syn)
        mem.remember.assert_called_once()
        call_args = mem.remember.call_args
        assert "synaptic" in call_args[1].get("tags", [])


# ── Chitta Persistence ──────────────────────────────────────────────────


class TestChittaPersistence:
    def test_load_calls_buddhi(self):
        mem = _make_memory({"reads": 3, "patterns": ["x"]})
        buddhi = MagicMock()
        load_chitta(mem, buddhi)
        buddhi.load_chitta_summary.assert_called_once_with({"reads": 3, "patterns": ["x"]})

    def test_load_no_data_skips(self):
        mem = _make_memory(None)
        buddhi = MagicMock()
        load_chitta(mem, buddhi)
        buddhi.load_chitta_summary.assert_not_called()

    def test_save_persists(self):
        mem = _make_memory()
        buddhi = MagicMock()
        buddhi.chitta_summary.return_value = {"state": "active"}
        save_chitta(mem, buddhi)
        mem.remember.assert_called_once()


# ── Gap Persistence ──────────────────────────────────────────────────


class TestGapPersistence:
    def test_load_restores_gaps(self):
        mem = _make_memory([{"tool": "bash", "count": 3}])
        gaps = MagicMock()
        load_gaps(mem, gaps)
        gaps.load_from_dict.assert_called_once_with([{"tool": "bash", "count": 3}])

    def test_load_no_data_skips(self):
        mem = _make_memory(None)
        gaps = MagicMock()
        load_gaps(mem, gaps)
        gaps.load_from_dict.assert_not_called()

    def test_save_persists(self):
        mem = _make_memory()
        gaps = MagicMock()
        gaps.to_dict.return_value = [{"tool": "bash"}]
        save_gaps(mem, gaps)
        mem.remember.assert_called_once()


# ── Session Stats ──────────────────────────────────────────────────────


class TestSessionStats:
    def test_records_cumulative_stats(self):
        mem = _make_memory(None)
        usage = MagicMock()
        usage.input_tokens = 1000
        usage.output_tokens = 500
        usage.tool_calls = 5
        usage.buddhi_errors = 1
        usage.buddhi_reflections = 2
        usage.buddhi_action = "edit_file"
        usage.rounds = 3
        record_session_stats(mem, usage)
        mem.remember.assert_called_once()


# ── Session Ledger ──────────────────────────────────────────────────────


class TestSessionLedger:
    def test_records_session(self):
        ledger = MagicMock()
        buddhi = MagicMock()
        buddhi.chitta_files_read = ["a.py", "b.py"]
        buddhi.chitta_files_written = ["c.py"]
        usage = MagicMock()
        usage.buddhi_errors = 0
        usage.buddhi_reflections = 0
        usage.buddhi_action = "edit_file"
        usage.buddhi_phase = None
        usage.output_tokens = 100
        usage.input_tokens = 200
        usage.tool_calls = 3
        usage.rounds = 2
        record_session_ledger(ledger, buddhi, "fix bug", usage)
        ledger.record.assert_called_once()
        record = ledger.record.call_args[0][0]
        assert record.task == "fix bug"
        assert record.outcome == "success"

    def test_error_outcome(self):
        ledger = MagicMock()
        buddhi = MagicMock()
        buddhi.chitta_files_read = []
        buddhi.chitta_files_written = []
        usage = MagicMock()
        usage.buddhi_errors = 3
        usage.buddhi_reflections = 0
        usage.buddhi_action = None
        usage.buddhi_phase = None
        usage.output_tokens = 50
        usage.input_tokens = 100
        usage.tool_calls = 1
        usage.rounds = 1
        record_session_ledger(ledger, buddhi, "broken task", usage)
        record = ledger.record.call_args[0][0]
        assert record.outcome == "error"
