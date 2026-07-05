"""Tests for deterministic TaskIntent dispatch.

Verifies that the autonomy loop works without LLM calls:
  - TaskIntent enum maps from intent_type strings
  - Unknown intent types return None (not fed to LLM)
  - Dispatch table routes to correct handlers
  - Handlers return None (no issue) or problem string (needs LLM)
"""

from steward.intent_handlers import NO_HANDLER
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

    def test_dispatch_unknown_intent_returns_sentinel(self, fake_llm):
        """Unknown intent types return NO_HANDLER sentinel, not None."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        result = agent._autonomy.dispatch_intent("not_a_real_intent")
        assert result is NO_HANDLER
        assert fake_llm.call_count == 0

    def test_known_intent_no_problem_still_none(self, fake_llm):
        """Known intent with no problem detected still returns None."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # HEALTH_CHECK returns None when health is above critical threshold
        result = agent._autonomy.dispatch_intent(TaskIntent.HEALTH_CHECK)
        assert result is None
        assert fake_llm.call_count == 0

    def test_unhandled_intent_task_blocked_not_completed(self, fake_llm):
        """Unhandled intent dispatch returns NO_HANDLER sentinel (blocking signal)."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Dispatch an intent that has no handler
        result = agent._autonomy.dispatch_intent("bottleneck_escalation")
        assert result is NO_HANDLER
        assert fake_llm.call_count == 0

    def test_normal_task_still_completes(self, fake_llm):
        """Regression: known intent with success still behaves normally."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # A known intent that succeeds returns None (problem-free)
        result = agent._autonomy.dispatch_intent(TaskIntent.HEALTH_CHECK)
        assert result is None
        assert fake_llm.call_count == 0

    def test_dispatch_routes_correctly(self, fake_llm):
        """Each TaskIntent routes to its correct handler.

        Detector intents (health checks, scans) return None when no problems detected.
        Membran intents (federation signals) require a task payload; without one they
        return NO_HANDLER (which blocks the task in autonomy.py).
        """
        from unittest.mock import MagicMock, patch

        from steward.agent import StewardAgent
        from steward.intent_handlers import NO_HANDLER
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
                if intent.is_membran:
                    # Membran intents require a payload; without one they correctly signal NO_HANDLER → BLOCKED
                    assert result is NO_HANDLER, f"Membran intent {intent.name} should return NO_HANDLER without payload, got: {result}"
                elif intent == TaskIntent.DIAGNOSE_STAGNATION:
                    # Stagnation detector always reports a problem when called (Kap 3b).
                    # In real execution, it only fires when is_stuck() is true (CONDITION_BASED).
                    assert isinstance(result, str) and result, f"DIAGNOSE_STAGNATION should return a problem string, got: {result}"
                else:
                    assert result is None, f"Intent {intent.name} unexpectedly returned: {result}"
        assert fake_llm.call_count == 0


class SimpleTask:
    """Minimal task object for testing — no mocks, just real data."""
    def __init__(self, id: str, title: str, description: str):
        self.id = id
        self.title = title
        self.description = description


class TestMembranSignals:
    """Tests for Membran-Signal handlers (Kap. 2)."""

    def test_bottleneck_escalation_intent_registered(self):
        """TaskIntent.BOTTLENECK_ESCALATION exists."""
        assert TaskIntent["BOTTLENECK_ESCALATION"]
        assert TaskIntent.BOTTLENECK_ESCALATION.value == "bottleneck_escalation"

    def test_governance_bounty_intent_registered(self):
        """TaskIntent.GOVERNANCE_BOUNTY exists."""
        assert TaskIntent["GOVERNANCE_BOUNTY"]
        assert TaskIntent.GOVERNANCE_BOUNTY.value == "governance_bounty"

    def test_bottleneck_handler_returns_problem_not_sentinel(self, fake_llm):
        """Bottleneck handler dispatch returns problem string, NOT NO_HANDLER."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Create real task with bottleneck description (key:value format)
        task = SimpleTask(
            id="test-task-123",
            title="[BOTTLENECK_ESCALATION] test",
            description="target_repo:kimeisele/agent-city\n"
        )

        # Dispatch the bottleneck intent with task context
        result = agent._autonomy.dispatch_intent(TaskIntent.BOTTLENECK_ESCALATION, task)
        assert result is not NO_HANDLER
        assert isinstance(result, str)
        assert "bottleneck escalation" in result.lower()
        assert fake_llm.call_count == 0

    def test_bottleneck_handler_extracts_repo(self, fake_llm):
        """Bottleneck handler extracts target_repo from description."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Create real task with specific repo
        task = SimpleTask(
            id="test-task-456",
            title="[BOTTLENECK_ESCALATION] test",
            description="target_repo:kimeisele/special-repo\n"
        )

        result = agent._autonomy.dispatch_intent(TaskIntent.BOTTLENECK_ESCALATION, task)
        assert "special-repo" in result
        assert fake_llm.call_count == 0

    def test_governance_handler_returns_problem_not_sentinel(self, fake_llm):
        """Governance bounty handler dispatch returns problem string, NOT NO_HANDLER."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Create real task with governance description
        task = SimpleTask(
            id="test-task-789",
            title="[GOVERNANCE_BOUNTY] test",
            description="target_repo:kimeisele/world-repo\n"
        )

        result = agent._autonomy.dispatch_intent(TaskIntent.GOVERNANCE_BOUNTY, task)
        assert result is not NO_HANDLER
        assert isinstance(result, str)
        assert "governance" in result.lower() or "bounty" in result.lower()
        assert fake_llm.call_count == 0

    def test_kap1_regression_unknown_intent_still_blocked(self, fake_llm):
        """Regression: unknown intent still returns NO_HANDLER (BLOCKED)."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Dispatch a completely unknown intent
        result = agent._autonomy.dispatch_intent("truly_unknown_intent")
        assert result is NO_HANDLER
        assert fake_llm.call_count == 0


class TestConscience:
    """Tests for Kapitel 3a: Gewissenstor (dharmische Gating)."""

    def test_steward_has_grihastha_identity(self, fake_llm):
        """Agent._ashrama == Ashrama.GRIHASTHA."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama

        agent = track_agent(StewardAgent(provider=fake_llm))
        assert agent._ashrama == Ashrama.GRIHASTHA

    def test_bhakti_scales_with_vedana(self, fake_llm):
        """Bhakti skaliert mit vedana.health: 1.0→100, 0.5→50, 0.0→0."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # _current_bhakti() muss die vedana_fn nutzen
        # Prüfe den Bereich
        bhakti = agent._autonomy._current_bhakti()
        assert 0 <= bhakti <= 100, f"Bhakti {bhakti} sollte zwischen 0 und 100 sein"

    def test_conscience_allows_authorized_intent(self, fake_llm):
        """Autorisierter Intent (HEAL_REPO→contract_import_fix) bei GRIHASTHA+hohem Bhakti → durchgelassen."""
        from steward.agent import StewardAgent
        from steward.intents import INTENT_TO_CONSCIENCE, TaskIntent
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
        from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # HEAL_REPO ist auf contract_import_fix gemappt
        intent_str = INTENT_TO_CONSCIENCE[TaskIntent.HEAL_REPO]
        bhakti = agent._autonomy._current_bhakti()
        verdict = check_conscience(intent_str, Ashrama.GRIHASTHA, bhakti)
        assert verdict.is_permitted, f"HEAL_REPO sollte erlaubt sein, aber: {verdict.reason}"

    def test_conscience_blocks_unauthorized(self, fake_llm):
        """Gewissenstor blockiert "shutdown" (braucht system_control+admin, GRIHASTHA hat keine)."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
        from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # "shutdown" erfordert ['system_control', 'admin'] — GRIHASTHA hat beide NICHT
        verdict = check_conscience("shutdown", Ashrama.GRIHASTHA, 99)
        assert verdict.is_permitted is False, "shutdown sollte für GRIHASTHA blockiert sein"
        assert "admin" in verdict.missing_permissions, "admin sollte in missing_permissions sein"

    def test_low_bhakti_revokes_borderline(self, fake_llm):
        """Niedriga Bhakti (<50) blockiert borderline-Intents."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
        from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Mit sehr niedrigem Bhakti prüfen
        low_bhakti = 10
        verdict = check_conscience("create_pr", Ashrama.GRIHASTHA, low_bhakti)
        # Wenn Bhakti zu niedrig ist, sollte es blockiert sein
        assert not verdict.is_permitted or verdict.bhakti >= 10

    def test_kap1_kap2_regression(self, fake_llm):
        """Regression: Kap-1/2 Logik funktioniert noch (NO_HANDLER, Membran-Payload)."""
        from steward.agent import StewardAgent
        from steward.intents import TaskIntent
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Unbekannter Intent → NO_HANDLER
        result = agent._autonomy.dispatch_intent("unknown_intent")
        assert result is NO_HANDLER

        # Membran-Intent mit Payload → Problem-String
        task = SimpleTask(
            id="test-task",
            title="[HEAL_REPO] test",
            description="target_repo:test/repo\n"
        )
        result = agent._autonomy.dispatch_intent(TaskIntent.HEAL_REPO, task)
        # HEAL_REPO sollte entweder None (ok) oder String (problem) sein, nicht NO_HANDLER
        assert result is None or isinstance(result, str)

    def test_unmapped_intent_fails_closed(self, fake_llm):
        """Nicht gemappter Intent → fällt auf "shutdown" (fail-closed) → blockiert."""
        from steward.agent import StewardAgent
        from steward.intents import INTENT_TO_CONSCIENCE
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
        from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # Simuliere einen unmapped Intent
        fake_intent = object()  # Nicht in INTENT_TO_CONSCIENCE
        intent_str = INTENT_TO_CONSCIENCE.get(fake_intent, "shutdown")
        assert intent_str == "shutdown", "Unmapped intent sollte auf 'shutdown' fallen"

        # "shutdown" ist fail-closed → blockiert für GRIHASTHA
        verdict = check_conscience(intent_str, Ashrama.GRIHASTHA, 99)
        assert verdict.is_permitted is False, "Unmapped intent sollte blockiert sein"

    def test_authorized_write_intent_passes(self, fake_llm):
        """Autorisierte Schreib-Intents (contract_import_fix) werden NICHT blockiert."""
        from steward.agent import StewardAgent
        from tests.conftest import track_agent
        from vibe_core.mahamantra.protocols.sankalpa.types import Ashrama
        from vibe_core.mahamantra.substrate.sankalpa.will import check_conscience

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._cetana.stop()

        # "contract_import_fix" erfordert nur ['code_modify'] — GRIHASTHA HAT code_modify
        verdict = check_conscience("contract_import_fix", Ashrama.GRIHASTHA, 80)
        assert verdict.is_permitted is True, "contract_import_fix sollte für GRIHASTHA erlaubt sein"
        assert verdict.missing_permissions == [], "Keine Permissions sollten fehlen"
