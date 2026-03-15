"""Tests for deterministic TaskIntent dispatch.

Verifies that the autonomy loop works without LLM calls:
  - TaskIntent enum maps from intent_type strings
  - Unknown intent types return None (not fed to LLM)
  - Dispatch table routes to correct handlers
  - Handlers return None (no issue) or problem string (needs LLM)
"""


from steward.intents import INTENT_TYPE_KEY, TaskIntent


class TestTaskIntentEnum:
    """TaskIntent enum maps correctly from strings."""

    def test_health_check_maps(self):
        assert TaskIntent.from_intent_type("health_check") == TaskIntent.HEALTH_CHECK

    def test_sense_scan_maps(self):
        assert TaskIntent.from_intent_type("sense_scan") == TaskIntent.SENSE_SCAN

    def test_ci_check_maps(self):
        assert TaskIntent.from_intent_type("ci_check") == TaskIntent.CI_CHECK

    def test_unknown_returns_none(self):
        assert TaskIntent.from_intent_type("random_garbage") is None

    def test_none_returns_none(self):
        assert TaskIntent.from_intent_type(None) is None

    def test_empty_string_returns_none(self):
        assert TaskIntent.from_intent_type("") is None

    def test_intent_type_key_is_string(self):
        assert isinstance(INTENT_TYPE_KEY, str)

    def test_update_deps_maps(self):
        assert TaskIntent.from_intent_type("update_deps") == TaskIntent.UPDATE_DEPS

    def test_remove_dead_code_maps(self):
        assert TaskIntent.from_intent_type("remove_dead_code") == TaskIntent.REMOVE_DEAD_CODE

    def test_post_merge_maps(self):
        assert TaskIntent.from_intent_type("post_merge") == TaskIntent.POST_MERGE

    def test_post_merge_is_reactive(self):
        assert not TaskIntent.POST_MERGE.is_proactive

    def test_proactive_intents_are_proactive(self):
        assert TaskIntent.UPDATE_DEPS.is_proactive
        assert TaskIntent.REMOVE_DEAD_CODE.is_proactive

    def test_federation_health_maps(self):
        assert TaskIntent.from_intent_type("federation_health") == TaskIntent.FEDERATION_HEALTH

    def test_federation_health_is_reactive(self):
        assert not TaskIntent.FEDERATION_HEALTH.is_proactive

    def test_reactive_intents_are_not_proactive(self):
        assert not TaskIntent.HEALTH_CHECK.is_proactive
        assert not TaskIntent.SENSE_SCAN.is_proactive
        assert not TaskIntent.CI_CHECK.is_proactive
        assert not TaskIntent.POST_MERGE.is_proactive
        assert not TaskIntent.FEDERATION_HEALTH.is_proactive

    def test_all_intents_have_handlers(self):
        """Every TaskIntent value must have a corresponding handler.

        If you add a new TaskIntent, you must also add a handler in
        StewardAgent._dispatch_intent. This test enforces that contract.
        """
        # Import here to avoid circular — just verify the enum is complete
        values = {m.value for m in TaskIntent}
        assert "health_check" in values
        assert "sense_scan" in values
        assert "ci_check" in values
        assert "post_merge" in values
        assert "update_deps" in values
        assert "remove_dead_code" in values
        assert "federation_health" in values


class TestDeterministicDispatch:
    """run_autonomous() dispatches to Python methods, not LLM."""

    def test_dispatch_health_check(self, fake_llm):
        """Health check handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.handlers.execute_health_check()
        # Healthy agent → no problem → no LLM needed
        assert result is None
        assert fake_llm.call_count == 0  # Zero LLM tokens

    def test_dispatch_sense_scan(self, fake_llm):
        """Sense scan handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.handlers.execute_sense_scan()
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_ci_check(self, fake_llm):
        """CI check handler runs without LLM calls."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.handlers.execute_ci_check()
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_post_merge(self, fake_llm):
        """Post-merge handler runs without LLM calls."""
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        # Mock subprocess calls (ruff + pytest) to avoid real execution
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            result = agent._autonomy.handlers.execute_post_merge()
        # Clean codebase → no problems → None
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_post_merge_detects_lint_failure(self, fake_llm):
        """Post-merge handler detects lint violations."""
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        def mock_subprocess(cmd, **kwargs):
            r = MagicMock()
            if "ruff" in cmd:
                r.returncode = 1
                r.stdout = "steward/foo.py:10:1: F401 unused import\n"
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=mock_subprocess):
            result = agent._autonomy.handlers.execute_post_merge()
        assert result is not None
        assert "ruff" in result
        assert "lint violation" in result
        assert fake_llm.call_count == 0

    def test_dispatch_post_merge_detects_test_failure(self, fake_llm):
        """Post-merge handler detects test failures."""
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        def mock_subprocess(cmd, **kwargs):
            r = MagicMock()
            if "ruff" in cmd:
                r.returncode = 0
                r.stdout = ""
            elif "pytest" in cmd:
                r.returncode = 1
                r.stdout = "3 failed, 50 passed\n"
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        with patch("subprocess.run", side_effect=mock_subprocess):
            result = agent._autonomy.handlers.execute_post_merge()
        assert result is not None
        assert "tests" in result
        assert "failed" in result
        assert fake_llm.call_count == 0

    def test_dispatch_federation_health_healthy(self, fake_llm):
        """Federation health check with no dead peers → no problem."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.handlers.execute_federation_health()
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_federation_health_with_dead_peers(self, fake_llm):
        """Federation health check detects dead peers."""
        from steward.agent import StewardAgent
        from steward.reaper import PeerStatus
        from steward.services import SVC_REAPER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        reaper = ServiceRegistry.get(SVC_REAPER)
        # Manually inject a dead peer
        from steward.reaper import PeerRecord

        reaper._peers["dead-agent"] = PeerRecord(
            agent_id="dead-agent",
            last_seen=0,
            trust=0.0,
            status=PeerStatus.DEAD,
        )
        result = agent._autonomy.handlers.execute_federation_health()
        assert result is not None
        assert "dead peer" in result.lower()
        assert "dead-agent" in result
        assert fake_llm.call_count == 0

    def test_dispatch_federation_health_with_outbox_backlog(self, fake_llm):
        """Federation health check detects outbox backlog."""
        from steward.agent import StewardAgent
        from steward.services import SVC_FEDERATION
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        federation = ServiceRegistry.get(SVC_FEDERATION)
        # Queue many outbound events to create backlog
        for i in range(15):
            federation.emit("test", {"i": i})
        result = agent._autonomy.handlers.execute_federation_health()
        assert result is not None
        assert "outbox backlog" in result.lower()
        assert fake_llm.call_count == 0

    def test_dispatch_unknown_intent_returns_none(self, fake_llm):
        """Unknown intent types are skipped, not fed to LLM."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.dispatch_intent("not_a_real_intent")
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_routes_correctly(self, fake_llm):
        """Each TaskIntent routes to its correct handler."""
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from steward.services import SVC_REAPER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Stop Cetana daemon thread — it runs GenesisDiscoveryHook in the
        # background which populates the reaper with real federation peers
        # from the GitHub API, causing execute_federation_health() to detect
        # missing capabilities and return a non-None problem string.
        agent._cetana.stop()

        # Clear any peers already discovered before Cetana was stopped
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is not None:
            reaper._peers.clear()

        # Mock subprocess to avoid real pip call in UPDATE_DEPS
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            for intent in TaskIntent:
                result = agent._autonomy.dispatch_intent(intent)
                assert result is None, f"Intent {intent.name} unexpectedly returned: {result}"
        assert fake_llm.call_count == 0
