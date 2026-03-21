"""Tests for PR Gate — federation PR review pipeline."""

import time
from unittest.mock import patch

from steward.federation import (
    OP_PR_REVIEW_REQUEST,
    OP_PR_REVIEW_VERDICT,
    FederationBridge,
)
from steward.pr_gate import CORE_FILES, _is_core_file, diagnose_pr
from steward.reaper import HeartbeatReaper

# ── Diagnostic Pipeline ──────────────────────────────────────────


class TestDiagnosePR:
    """diagnose_pr() runs blast radius, author, and CI checks."""

    def test_blast_radius_counts_files(self):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=["a.py", "b.py", "c.py"],
        )
        assert result["blast_radius"] == 3

    def test_core_files_detected(self):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=["city/services.py", "tests/test_foo.py"],
        )
        assert result["has_core_files"] is True
        assert "city/services.py" in result["core_files_touched"]

    def test_no_core_files(self):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=["tests/test_foo.py", "docs/README.md"],
        )
        assert result["has_core_files"] is False
        assert result["core_files_touched"] == []

    def test_author_is_known_peer(self):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="agent-city",
            files=[],
            reaper=reaper,
        )
        assert result["author_is_peer"] is True
        assert result["author_trust"] > 0.0

    def test_author_unknown(self):
        reaper = HeartbeatReaper()
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="random-bot",
            files=[],
            reaper=reaper,
        )
        assert result["author_is_peer"] is False
        assert result["author_trust"] == 0.0

    def test_no_reaper_defaults_to_unknown_author(self):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="anyone",
            files=[],
            reaper=None,
        )
        assert result["author_is_peer"] is False

    @patch("steward.pr_gate._check_ci_status", return_value="failure")
    def test_ci_failing(self, mock_ci):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=[],
        )
        assert result["ci_failing"] is True
        assert result["ci_status"] == "failure"

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_ci_passing(self, mock_ci):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=[],
        )
        assert result["ci_failing"] is False
        assert result["ci_status"] == "success"

    @patch("steward.pr_gate._check_ci_status", return_value="unknown")
    def test_ci_unknown_not_failing(self, mock_ci):
        result = diagnose_pr(
            repo="kimeisele/agent-city",
            pr_number=42,
            author="",
            files=[],
        )
        assert result["ci_failing"] is False


class TestCoreFileDetection:
    """_is_core_file matches exact and suffix patterns."""

    def test_exact_match(self):
        assert _is_core_file("city/services.py") is True

    def test_suffix_match(self):
        assert _is_core_file("src/city/immune.py") is True

    def test_non_core_file(self):
        assert _is_core_file("tests/test_foo.py") is False

    def test_claude_md_is_core(self):
        assert _is_core_file("CLAUDE.md") is True

    def test_all_core_files_detected(self):
        for f in CORE_FILES:
            assert _is_core_file(f) is True


# ── NADI Handler ──────────────────────────────────────────────


class TestPRReviewRequestHandler:
    """FederationBridge._handle_pr_review_request dispatches correctly."""

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_handler_registered_in_dispatch(self, mock_ci):
        bridge = FederationBridge()
        assert OP_PR_REVIEW_REQUEST in bridge._op_dispatch

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_handler_rejects_missing_repo(self, mock_ci):
        bridge = FederationBridge()
        assert not bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {"pr_number": 42},
        )

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_handler_rejects_missing_pr_number(self, mock_ci):
        bridge = FederationBridge()
        assert not bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {"repo": "kimeisele/agent-city"},
        )

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_handler_emits_verdict(self, mock_ci):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        bridge = FederationBridge(reaper=reaper)

        result = bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "agent-city",
                "files": ["tests/test_new.py"],
                "source_agent": "agent-city",
            },
        )
        assert result is True

        # Verdict emitted to outbound queue
        assert len(bridge._outbound) == 1
        event = bridge._outbound[0]
        assert event.operation == OP_PR_REVIEW_VERDICT
        assert event.payload["pr_number"] == 42
        assert event.payload["verdict"] == "approve"
        assert event.payload["repo"] == "kimeisele/agent-city"

    @patch("steward.pr_gate._check_ci_status", return_value="failure")
    def test_ci_failure_causes_request_changes(self, mock_ci):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        bridge = FederationBridge(reaper=reaper)

        bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "agent-city",
                "files": ["tests/test_new.py"],
                "source_agent": "agent-city",
            },
        )

        event = bridge._outbound[0]
        assert event.payload["verdict"] == "request_changes"
        assert "CI is failing" in event.payload["reason"]

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_unknown_author_causes_request_changes(self, mock_ci):
        reaper = HeartbeatReaper()
        bridge = FederationBridge(reaper=reaper)

        bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "random-bot",
                "files": ["tests/test_new.py"],
                "source_agent": "agent-city",
            },
        )

        event = bridge._outbound[0]
        assert event.payload["verdict"] == "request_changes"
        assert "not in federation" in event.payload["reason"]

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_core_files_flagged_in_diagnostics(self, mock_ci):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        bridge = FederationBridge(reaper=reaper)

        bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "agent-city",
                "files": ["city/services.py", "tests/test_new.py"],
                "source_agent": "agent-city",
            },
        )

        event = bridge._outbound[0]
        # Still approve but flag for council
        assert event.payload["verdict"] == "approve"
        assert "council vote required" in event.payload["reason"]
        assert event.payload["diagnostics"]["has_core_files"] is True

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_high_blast_radius_causes_request_changes(self, mock_ci):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        bridge = FederationBridge(reaper=reaper)

        # 25 files changed — high blast radius
        files = [f"file_{i}.py" for i in range(25)]
        bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "agent-city",
                "files": files,
                "source_agent": "agent-city",
            },
        )

        event = bridge._outbound[0]
        assert event.payload["verdict"] == "request_changes"
        assert "blast radius" in event.payload["reason"]


# ── KirtanLoop Integration ────────────────────────────────────


class TestPRReviewKirtan:
    """KirtanLoop tracks PR review lifecycle."""

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_kirtan_call_opened_and_closed(self, mock_ci, tmp_path):
        from steward.kirtan import KirtanLoop
        from steward.services import SVC_KIRTAN
        from vibe_core.di import ServiceRegistry

        kirtan = KirtanLoop(ledger_path=str(tmp_path / "kirtan_ledger.json"))
        ServiceRegistry.register(SVC_KIRTAN, kirtan)

        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())
        bridge = FederationBridge(reaper=reaper)

        bridge.ingest(
            OP_PR_REVIEW_REQUEST,
            {
                "repo": "kimeisele/agent-city",
                "pr_number": 42,
                "author": "agent-city",
                "files": [],
                "source_agent": "agent-city",
            },
        )

        # KirtanLoop should have no open calls — verdict was sent and closed
        assert len(kirtan.open_calls()) == 0


# ── Transport Integration ─────────────────────────────────────


class TestPRReviewViaTransport:
    """PR review request arrives via transport.process_inbound()."""

    @patch("steward.pr_gate._check_ci_status", return_value="success")
    def test_pr_review_via_transport(self, mock_ci):
        reaper = HeartbeatReaper()
        reaper.record_heartbeat("agent-city", timestamp=time.time())

        transport = _FakeTransport(
            messages=[
                {
                    "operation": OP_PR_REVIEW_REQUEST,
                    "payload": {
                        "repo": "kimeisele/agent-city",
                        "pr_number": 99,
                        "author": "agent-city",
                        "files": ["hooks/new_hook.py"],
                        "source_agent": "agent-city",
                    },
                },
            ]
        )

        bridge = FederationBridge(reaper=reaper)
        count = bridge.process_inbound(transport)
        assert count == 1
        assert len(bridge._outbound) == 1
        assert bridge._outbound[0].operation == OP_PR_REVIEW_VERDICT
        assert bridge._outbound[0].payload["verdict"] == "approve"


class _FakeTransport:
    """Minimal FederationTransport for testing."""

    def __init__(self, messages=None):
        self._outbox = messages or []
        self._inbox = []

    def read_outbox(self):
        return self._outbox

    def append_to_inbox(self, messages):
        self._inbox.extend(messages)
        return len(messages)
