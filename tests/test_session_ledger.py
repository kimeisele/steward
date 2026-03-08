"""Tests for SessionLedger — cross-session learning."""

import json
import tempfile
from pathlib import Path

from steward.session_ledger import SessionLedger, SessionRecord


class TestSessionRecord:
    """Test SessionRecord dataclass."""

    def test_to_dict_roundtrip(self):
        record = SessionRecord(
            task="Fix the bug",
            outcome="success",
            summary="debug: 3 rounds, 5 tools",
            tokens=1500,
            tool_calls=5,
            rounds=3,
            files_read=["/a.py", "/b.py"],
            files_written=["/a.py"],
            buddhi_action="debug",
            buddhi_phase="VERIFY",
        )
        d = record.to_dict()
        restored = SessionRecord.from_dict(d)
        assert restored.task == record.task
        assert restored.outcome == record.outcome
        assert restored.tokens == record.tokens
        assert restored.files_read == record.files_read
        assert restored.files_written == record.files_written

    def test_from_dict_missing_fields(self):
        """Missing fields get defaults."""
        record = SessionRecord.from_dict({"task": "test", "outcome": "success"})
        assert record.task == "test"
        assert record.tokens == 0
        assert record.files_read == []
        assert record.buddhi_action == ""

    def test_from_dict_empty(self):
        record = SessionRecord.from_dict({})
        assert record.task == ""
        assert record.outcome == ""


class TestSessionLedger:
    """Test SessionLedger persistence and context generation."""

    def test_record_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(SessionRecord(task="Fix bug", outcome="success", summary="done"))
            assert len(ledger.sessions) == 1
            assert ledger.sessions[0].task == "Fix bug"

    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger1 = SessionLedger(cwd=tmpdir)
            ledger1.record(SessionRecord(task="Task 1", outcome="success", summary="ok"))
            ledger1.record(SessionRecord(task="Task 2", outcome="error", summary="failed"))

            # New instance loads from disk
            ledger2 = SessionLedger(cwd=tmpdir)
            assert len(ledger2.sessions) == 2
            assert ledger2.sessions[0].task == "Task 1"
            assert ledger2.sessions[1].task == "Task 2"

    def test_prompt_context_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            assert ledger.prompt_context() == ""

    def test_prompt_context_with_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(
                    task="Fix authentication",
                    outcome="success",
                    summary="done",
                    tokens=2000,
                    rounds=4,
                    files_written=["/src/auth.py"],
                    timestamp="2026-03-08T10:00:00Z",
                )
            )
            ctx = ledger.prompt_context()
            assert "Previous sessions" in ctx
            assert "Fix authentication" in ctx
            assert "success" in ctx
            assert "2000 tokens" in ctx
            assert "auth.py" in ctx

    def test_prompt_context_limits_to_5(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            for i in range(10):
                ledger.record(
                    SessionRecord(
                        task=f"Task {i}",
                        outcome="success",
                        summary=f"done {i}",
                    )
                )
            ctx = ledger.prompt_context()
            # Should only show last 5
            assert "Task 5" in ctx
            assert "Task 9" in ctx
            assert "Task 0" not in ctx

    def test_max_sessions_trimmed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            for i in range(60):
                ledger.record(SessionRecord(task=f"Task {i}", outcome="success", summary=f"done {i}"))
            # Should keep last 50
            assert len(ledger.sessions) == 50
            assert ledger.sessions[0].task == "Task 10"
            assert ledger.sessions[-1].task == "Task 59"

    def test_task_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            long_task = "x" * 300
            ledger.record(SessionRecord(task=long_task, outcome="success", summary="done"))
            assert len(ledger.sessions[0].task) <= 203  # 200 + "..."

    def test_file_list_truncation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(
                    task="test",
                    outcome="success",
                    summary="done",
                    files_read=[f"/file{i}.py" for i in range(30)],
                )
            )
            assert len(ledger.sessions[0].files_read) <= 20

    def test_stats_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            assert ledger.stats["total_sessions"] == 0

    def test_stats_aggregation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(
                    task="t1",
                    outcome="success",
                    summary="ok",
                    tokens=1000,
                    tool_calls=5,
                )
            )
            ledger.record(
                SessionRecord(
                    task="t2",
                    outcome="error",
                    summary="fail",
                    tokens=2000,
                    tool_calls=3,
                )
            )
            stats = ledger.stats
            assert stats["total_sessions"] == 2
            assert stats["success_rate"] == 0.5
            assert stats["total_tokens"] == 3000
            assert stats["total_tool_calls"] == 8
            assert stats["avg_tokens_per_session"] == 1500

    def test_timestamp_auto_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(SessionRecord(task="test", outcome="success", summary="done"))
            assert ledger.sessions[0].timestamp != ""
            assert "2026" in ledger.sessions[0].timestamp

    def test_corrupted_file_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".steward"
            state_dir.mkdir()
            (state_dir / "sessions.json").write_text("not valid json{{{")

            ledger = SessionLedger(cwd=tmpdir)
            assert len(ledger.sessions) == 0  # Graceful fallback

    def test_version_mismatch_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / ".steward"
            state_dir.mkdir()
            (state_dir / "sessions.json").write_text(json.dumps({"version": 999, "sessions": []}))

            ledger = SessionLedger(cwd=tmpdir)
            assert len(ledger.sessions) == 0  # Version mismatch = start fresh


class TestSkillCandidates:
    """Test find_skill_candidates — post-task learning pattern extraction."""

    def test_no_candidates_too_few_sessions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(task="Fix bug", outcome="success", summary="ok", tool_calls=3, buddhi_action="debug")
            )
            assert ledger.find_skill_candidates() == []

    def test_no_candidates_all_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            for i in range(5):
                ledger.record(
                    SessionRecord(
                        task=f"Task {i}", outcome="error", summary="fail", tool_calls=3, buddhi_action="debug"
                    )
                )
            assert ledger.find_skill_candidates() == []

    def test_candidate_from_repeated_action(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(
                    task="Fix failing tests in auth module",
                    outcome="success",
                    summary="ok",
                    tool_calls=5,
                    rounds=3,
                    buddhi_action="debug",
                    files_read=["auth.py"],
                    files_written=["auth.py"],
                )
            )
            ledger.record(
                SessionRecord(
                    task="Debug failing tests in login",
                    outcome="success",
                    summary="ok",
                    tool_calls=4,
                    rounds=2,
                    buddhi_action="debug",
                    files_read=["auth.py"],
                    files_written=["auth.py"],
                )
            )
            candidates = ledger.find_skill_candidates()
            assert len(candidates) == 1
            assert candidates[0]["action"] == "debug"
            assert candidates[0]["frequency"] == 2
            assert "auth.py" in candidates[0]["common_files"]

    def test_no_candidate_if_single_action(self):
        """Need 2+ sessions with same action to create candidate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            ledger.record(
                SessionRecord(task="Fix auth", outcome="success", summary="ok", tool_calls=3, buddhi_action="debug")
            )
            ledger.record(
                SessionRecord(
                    task="Add feature", outcome="success", summary="ok", tool_calls=3, buddhi_action="implement"
                )
            )
            assert ledger.find_skill_candidates() == []

    def test_candidate_has_sample_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            for i in range(3):
                ledger.record(
                    SessionRecord(
                        task=f"Deploy version {i}",
                        outcome="success",
                        summary="ok",
                        tool_calls=3,
                        rounds=2,
                        buddhi_action="deploy",
                    )
                )
            candidates = ledger.find_skill_candidates()
            assert len(candidates) == 1
            assert len(candidates[0]["sample_tasks"]) == 3
            assert candidates[0]["avg_rounds"] == 2
            assert candidates[0]["avg_tools"] == 3

    def test_low_tool_calls_filtered(self):
        """Sessions with fewer than 2 tool calls are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = SessionLedger(cwd=tmpdir)
            for _ in range(3):
                ledger.record(
                    SessionRecord(
                        task="Simple query", outcome="success", summary="ok", tool_calls=1, buddhi_action="query"
                    )
                )
            assert ledger.find_skill_candidates() == []
