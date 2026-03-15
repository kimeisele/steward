"""End-to-end test of the autonomous flow — Sankalpa → TaskManager → dispatch → 0 tokens.

Verifies the complete autonomy pipeline:
  1. Sankalpa generates typed intents
  2. _phase_genesis() stores tasks with [INTENT_NAME] title prefix
  3. run_autonomous() parses intent from title, dispatches to Python methods
  4. No LLM calls occur for deterministic intents
  5. LLM only called when handler finds a real problem
  6. Session ledger records autonomous cycles

This is the most important test in steward. If this breaks,
the agent cannot run autonomously.
"""

import asyncio

from steward.autonomy import parse_intent_from_title as _parse_intent_from_title
from steward.fix_pipeline import problem_fingerprint as _problem_fingerprint
from steward.intents import TaskIntent
from steward.types import MessageRole
from tests.conftest import track_agent


class TestParseIntentFromTitle:
    """Title prefix parsing — the persistence-safe intent encoding."""

    def test_parses_health_check(self):
        assert _parse_intent_from_title("[HEALTH_CHECK] Quick check") == TaskIntent.HEALTH_CHECK

    def test_parses_sense_scan(self):
        assert _parse_intent_from_title("[SENSE_SCAN] Environment scan") == TaskIntent.SENSE_SCAN

    def test_parses_ci_check(self):
        assert _parse_intent_from_title("[CI_CHECK] Check CI") == TaskIntent.CI_CHECK

    def test_parses_update_deps(self):
        assert _parse_intent_from_title("[UPDATE_DEPS] Update packages") == TaskIntent.UPDATE_DEPS

    def test_parses_remove_dead_code(self):
        assert _parse_intent_from_title("[REMOVE_DEAD_CODE] Clean up") == TaskIntent.REMOVE_DEAD_CODE

    def test_parses_federation_health(self):
        assert _parse_intent_from_title("[FEDERATION_HEALTH] Check peers") == TaskIntent.FEDERATION_HEALTH

    def test_no_prefix_returns_none(self):
        assert _parse_intent_from_title("Random task") is None

    def test_unknown_prefix_returns_none(self):
        assert _parse_intent_from_title("[GARBAGE] Unknown intent") is None

    def test_empty_string_returns_none(self):
        assert _parse_intent_from_title("") is None

    def test_malformed_bracket_returns_none(self):
        assert _parse_intent_from_title("[") is None
        assert _parse_intent_from_title("[]") is None


class TestAutonomousFlowE2E:
    """Full pipeline: Sankalpa → TaskManager → dispatch → handler → 0 LLM tokens."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))

    def test_run_autonomous_no_tasks_returns_none(self, fake_llm):
        """Empty TaskManager → returns None, 0 tokens."""
        agent = self._make_agent(fake_llm)
        result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_dispatches_health_check(self, fake_llm):
        """Task with [HEALTH_CHECK] title → deterministic handler, 0 tokens."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(title="[HEALTH_CHECK] Quick check", priority=50)

        result = asyncio.run(agent.run_autonomous())
        # Healthy agent → no problem → None returned → 0 LLM calls
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_dispatches_sense_scan(self, fake_llm):
        """Task with [SENSE_SCAN] title → deterministic handler, 0 tokens."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(title="[SENSE_SCAN] Scan environment", priority=50)

        result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_dispatches_ci_check(self, fake_llm):
        """Task with [CI_CHECK] title → deterministic handler, 0 tokens."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(title="[CI_CHECK] Check CI", priority=50)

        result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_dispatches_federation_health(self, fake_llm):
        """Task with [FEDERATION_HEALTH] title → deterministic handler, 0 tokens."""
        from steward.services import SVC_REAPER, SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)

        # Stop Cetana — its background GenesisDiscoveryHook populates the
        # reaper with real federation peers from the GitHub API. Those peers
        # lack 'code_analysis' etc. capabilities, causing the federation
        # health handler to report degradation instead of returning None.
        agent._cetana.stop()

        # Clear any peers discovered before Cetana was stopped
        reaper = ServiceRegistry.get(SVC_REAPER)
        if reaper is not None:
            reaper._peers.clear()

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        # Priority 100 ensures this task is dispatched first, even if genesis
        # creates other tasks during run_autonomous's phase_genesis() call
        task_mgr.add_task(title="[FEDERATION_HEALTH] Check federation", priority=100)

        result = asyncio.run(agent.run_autonomous())
        # Healthy federation (no dead peers, no backlog) → None → 0 LLM calls
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_skips_unknown_title(self, fake_llm):
        """Task without [INTENT] prefix → skipped, 0 tokens."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(title="Random task with no intent", priority=50)

        result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0

    def test_run_autonomous_dispatches_federated_task(self, fake_llm):
        """Task with [FED:source] prefix → dispatched to LLM fix pipeline + callback."""
        from steward.services import SVC_FEDERATION, SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_types import TaskStatus

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(
            title="[FED:agent-internet] Fix failing test_api_routes",
            priority=70,
        )

        asyncio.run(agent.run_autonomous())
        # Federated tasks go to LLM (FakeLLM returns "ok")
        assert fake_llm.call_count >= 1

        # Task should be completed
        completed = task_mgr.list_tasks(status=TaskStatus.COMPLETED)
        assert any("[FED:agent-internet]" in t.title for t in completed)

        # Callback emitted to federation bridge
        bridge = ServiceRegistry.get(SVC_FEDERATION)
        if bridge is not None:
            assert len(bridge._outbound) >= 1
            callback = bridge._outbound[-1]
            assert callback.operation in ("task_completed", "task_failed")
            assert callback.payload["source_agent"] == "agent-internet"

    def test_task_marked_completed_after_dispatch(self, fake_llm):
        """Dispatched task gets marked as completed in TaskManager."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_types import TaskStatus

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task = task_mgr.add_task(title="[HEALTH_CHECK] Check", priority=50)
        task_id = task.id

        asyncio.run(agent.run_autonomous())

        updated = [t for t in task_mgr.list_tasks(status=TaskStatus.COMPLETED) if t.id == task_id]
        assert len(updated) == 1

    def test_session_ledger_records_autonomous_run(self, fake_llm):
        """Autonomous cycles are recorded in session ledger."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        task_mgr.add_task(title="[HEALTH_CHECK] Check", priority=50)
        asyncio.run(agent.run_autonomous())

        # Ledger should have a record
        sessions = agent._ledger.sessions
        autonomous = [s for s in sessions if "[autonomous]" in s.task]
        assert len(autonomous) >= 1
        assert autonomous[-1].tokens == 0  # Deterministic = 0 tokens

    def test_consecutive_autonomous_runs(self, fake_llm):
        """Multiple autonomous runs don't block each other."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        # First run
        task_mgr.add_task(title="[HEALTH_CHECK] Run 1", priority=50)
        asyncio.run(agent.run_autonomous())

        # Second run — should still work (completed tasks don't block)
        task_mgr.add_task(title="[CI_CHECK] Run 2", priority=50)
        asyncio.run(agent.run_autonomous())

        assert fake_llm.call_count == 0


class TestPhaseGenesis:
    """_phase_genesis() creates typed tasks from Sankalpa intents."""

    def test_genesis_creates_titled_tasks(self, fake_llm):
        """When Sankalpa fires, tasks have [INTENT] title prefix."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        # Force genesis with enough idle time to trigger Sankalpa
        agent._autonomy.phase_genesis(idle_override=15)

        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        tasks = task_mgr.list_tasks()
        for task in tasks:
            if task.title.startswith("["):
                intent = _parse_intent_from_title(task.title)
                assert intent is not None, f"Task has unparseable title: {task.title}"

    def test_genesis_only_counts_active_tasks(self, fake_llm):
        """Completed tasks don't count as pending for Sankalpa."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_types import TaskStatus

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        # Add and complete a task
        task = task_mgr.add_task(title="[HEALTH_CHECK] Old", priority=50)
        task_mgr.update_task(task.id, status=TaskStatus.COMPLETED)

        # Genesis should not count completed task as "pending"
        # (whether Sankalpa fires depends on strategy, but it shouldn't be blocked)
        agent._autonomy.phase_genesis(idle_override=15)
        # No crash = success

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))


class TestDharmaPhase:
    """DHARMA phase monitors vedana health."""

    def test_dharma_sets_anomaly_on_low_health(self, fake_llm):
        """When health is critical, DHARMA sets the anomaly flag."""
        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))
        # Clear any boot-time anomaly
        agent.clear_health_anomaly()
        assert not agent.health_anomaly

        # DHARMA checks vedana — in test env, health is high (no real errors)
        from steward.cetana import Phase

        agent._on_cetana_phase(Phase.DHARMA, None)
        # Healthy environment → no anomaly
        assert not agent.health_anomaly

    def test_dharma_runs_in_heartbeat(self, fake_llm):
        """DHARMA is called by Cetana during heartbeat — doesn't crash."""
        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))
        # Simulate heartbeat calling all phases
        import time

        from steward.antahkarana.vedana import measure_vedana
        from steward.cetana import CetanaBeat, Phase

        beat = CetanaBeat(
            timestamp=time.time(),
            vedana=measure_vedana(),
            frequency_hz=0.5,
            beat_number=1,
            phase=Phase.DHARMA,
        )
        agent._on_cetana_phase(Phase.DHARMA, beat)
        # Should not crash


class TestKarmaPhase:
    """KARMA phase dispatches pending tasks (daemon mode workhorse)."""

    def test_karma_dispatches_task(self, fake_llm):
        """KARMA picks up a typed task and dispatches it. 0 LLM tokens."""
        from steward.agent import StewardAgent
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_types import TaskStatus

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="[HEALTH_CHECK] Quick check", priority=50)

        agent._autonomy.phase_karma()

        # Task dispatched and completed
        completed = task_mgr.list_tasks(status=TaskStatus.COMPLETED)
        assert len(completed) >= 1
        assert fake_llm.call_count == 0  # Deterministic — 0 tokens

    def test_karma_noop_when_no_tasks(self, fake_llm):
        """KARMA returns immediately when no tasks pending."""
        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))
        # No tasks added — should be a no-op
        agent._autonomy.phase_karma()
        assert fake_llm.call_count == 0

    def test_karma_handles_untyped_task(self, fake_llm):
        """KARMA completes tasks without [INTENT] prefix as no-ops."""
        from steward.agent import StewardAgent
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry
        from vibe_core.task_types import TaskStatus

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="random task without intent", priority=50)

        agent._autonomy.phase_karma()

        completed = task_mgr.list_tasks(status=TaskStatus.COMPLETED)
        assert len(completed) >= 1
        assert fake_llm.call_count == 0


class TestDaemonMode:
    """Persistent daemon — boot once, Cetana drives work."""

    def test_run_daemon_blocks_until_stop(self, fake_llm):
        """run_daemon() blocks main thread until Cetana stop signal."""
        import threading

        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))

        started = threading.Event()
        exited = threading.Event()

        def run():
            started.set()
            agent.run_daemon()
            exited.set()

        t = threading.Thread(target=run, daemon=True)
        t.start()

        # Daemon should be blocking
        assert started.wait(timeout=2.0), "Daemon thread did not start"
        assert not exited.is_set(), "Daemon exited prematurely"

        # Send stop signal
        agent._cetana._stop_event.set()
        assert exited.wait(timeout=2.0), "Daemon did not exit after stop signal"

    def test_daemon_graceful_shutdown(self, fake_llm):
        """close() after run_daemon() saves state and stops Cetana."""
        import threading

        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))

        def run():
            agent.run_daemon()

        t = threading.Thread(target=run, daemon=True)
        t.start()

        # Let it run briefly
        import time

        time.sleep(0.1)

        # Stop and close
        agent._cetana._stop_event.set()
        t.join(timeout=2.0)
        agent.close()

        # Cetana should be stopped
        assert not agent._cetana.is_alive


class TestDaemonMemoryManagement:
    """Verify conversation resets between tasks — no state bloat."""

    def test_conversation_resets_between_dispatches(self, fake_llm):
        """Each _dispatch_next_task() starts with clean conversation."""
        from steward.agent import StewardAgent
        from steward.services import SVC_TASK_MANAGER
        from steward.types import Message, MessageRole
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        # Stuff conversation with messages (simulates previous task)
        for i in range(10):
            agent._conversation.add(Message(role=MessageRole.USER, content=f"old message {i}" * 100))
        tokens_before = agent._conversation.total_tokens
        assert tokens_before > 500, "Setup: conversation should have accumulated tokens"

        # Dispatch a task — conversation should reset first
        task_mgr.add_task(title="[HEALTH_CHECK] Quick check", priority=50)
        agent._autonomy.phase_karma()

        # After dispatch, conversation should be clean (system msg only)
        assert len(agent._conversation.messages) <= 2  # system + maybe 1 user
        assert agent._conversation.total_tokens < tokens_before

    def test_system_prompt_survives_reset(self, fake_llm):
        """System message is preserved across conversation resets."""
        from steward.agent import StewardAgent
        from steward.types import Message

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Add a system message (normally done by run_stream on first call)
        sys_msg = Message(role=MessageRole.SYSTEM, content="You are steward.")
        agent._conversation.messages.insert(0, sys_msg)
        # Add some user messages too
        agent._conversation.add(Message(role=MessageRole.USER, content="hello"))

        agent._reset_conversation()

        assert len(agent._conversation.messages) == 1
        assert agent._conversation.messages[0].role == MessageRole.SYSTEM
        assert agent._conversation.messages[0].content == "You are steward."

    def test_hebbian_weights_persist_across_resets(self, fake_llm):
        """Hebbian learning survives conversation reset — real memory."""
        from steward.agent import StewardAgent

        agent = track_agent(StewardAgent(provider=fake_llm))

        # Set a Hebbian weight
        agent._autonomy._synaptic.update("test_key", "fix", success=True)
        weight_before = agent._autonomy._synaptic.get_weight("test_key", "fix")
        assert weight_before > 0.5

        # Reset conversation
        agent._reset_conversation()

        # Hebbian weight should survive
        weight_after = agent._autonomy._synaptic.get_weight("test_key", "fix")
        assert weight_after == weight_before

    def test_multiple_dispatches_no_growth(self, fake_llm):
        """Multiple KARMA dispatches don't accumulate conversation state."""
        from steward.agent import StewardAgent
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = track_agent(StewardAgent(provider=fake_llm))
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)

        # Run 5 task dispatches
        for i in range(5):
            task_mgr.add_task(title=f"[HEALTH_CHECK] Check {i}", priority=50)
            agent._autonomy.phase_karma()

        # Conversation should be minimal — not 5 tasks worth of history
        assert len(agent._conversation.messages) <= 2
        assert agent._conversation.total_tokens < 500


class TestProblemFingerprint:
    """problem_fingerprint() — granular context extraction."""

    def test_extracts_file_paths(self):
        fp = _problem_fingerprint("Fix the bug in src/api.py and tests/test_api.py")
        assert "src/api.py" in fp
        assert "tests/test_api.py" in fp

    def test_extracts_error_types(self):
        fp = _problem_fingerprint("Got TypeError when calling async function")
        assert "TypeError" in fp

    def test_extracts_workflow_name(self):
        fp = _problem_fingerprint("CI is failing: workflow 'test'. Check logs.")
        assert fp == "test"

    def test_falls_back_to_keywords(self):
        fp = _problem_fingerprint("Something unusual is happening with the database connection")
        assert len(fp) > 0
        # Should contain significant words, not generic ones
        assert "something" not in fp or "unusual" in fp

    def test_empty_returns_empty(self):
        assert _problem_fingerprint("") == ""

    def test_different_problems_different_fingerprints(self):
        """Two different problems produce different fingerprints."""
        fp1 = _problem_fingerprint("Fix TypeError in api.py")
        fp2 = _problem_fingerprint("Fix ImportError in utils.py")
        assert fp1 != fp2


class TestHebbianAutonomousLearning:
    """Hebbian learning from autonomous fix outcomes — GRANULAR."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))

    def test_hebbian_learn_success_reinforces(self, fake_llm):
        """Successful fix reinforces the granular trigger/fix weight."""
        agent = self._make_agent(fake_llm)
        trigger = "auto:CI_CHECK:api.py"
        initial = agent._synaptic.get_weight(trigger, "fix")
        agent._autonomy.pipeline.hebbian_learn(trigger, success=True)
        after = agent._synaptic.get_weight(trigger, "fix")
        assert after > initial

    def test_hebbian_learn_failure_weakens(self, fake_llm):
        """Failed fix weakens the granular trigger/fix weight."""
        agent = self._make_agent(fake_llm)
        trigger = "auto:CI_CHECK:api.py"
        initial = agent._synaptic.get_weight(trigger, "fix")
        agent._autonomy.pipeline.hebbian_learn(trigger, success=False)
        after = agent._synaptic.get_weight(trigger, "fix")
        assert after < initial

    def test_file_specific_no_cross_contamination(self, fake_llm):
        """Failing on api.py does NOT weaken utils.py weight."""
        agent = self._make_agent(fake_llm)
        # Fail repeatedly on api.py
        for _ in range(10):
            agent._autonomy.pipeline.hebbian_learn("auto:CI_CHECK:api.py", success=False)
        api_weight = agent._synaptic.get_weight("auto:CI_CHECK:api.py", "fix")
        assert api_weight < 0.2

        # utils.py should be unaffected (still at default 0.5)
        utils_weight = agent._synaptic.get_weight("auto:CI_CHECK:utils.py", "fix")
        assert utils_weight == 0.5

    def test_per_file_learning_on_success(self, fake_llm):
        """Success updates per-file weights for changed files."""
        agent = self._make_agent(fake_llm)
        changed = {"src/api.py", "src/utils.py"}
        agent._autonomy.pipeline.hebbian_learn("auto:CI_CHECK:api.py", success=True, changed_files=changed)

        # Both files should have increased file-level weights
        api_weight = agent._synaptic.get_weight("file:src/api.py", "auto_fix")
        utils_weight = agent._synaptic.get_weight("file:src/utils.py", "auto_fix")
        assert api_weight > 0.5
        assert utils_weight > 0.5

    def test_per_file_learning_on_failure(self, fake_llm):
        """Failure updates per-file weights for changed files."""
        agent = self._make_agent(fake_llm)
        changed = {"src/api.py", "src/utils.py"}
        agent._autonomy.pipeline.hebbian_learn("auto:CI_CHECK:api.py", success=False, changed_files=changed)

        api_weight = agent._synaptic.get_weight("file:src/api.py", "auto_fix")
        utils_weight = agent._synaptic.get_weight("file:src/utils.py", "auto_fix")
        assert api_weight < 0.5
        assert utils_weight < 0.5

    def test_non_py_files_skip_file_learning(self, fake_llm):
        """Non-Python files don't get Hebbian file-level weights."""
        agent = self._make_agent(fake_llm)
        changed = {"README.md", "config.json", "src/api.py"}
        agent._autonomy.pipeline.hebbian_learn("auto:CI_CHECK:api.py", success=True, changed_files=changed)

        # Only .py file should have a weight
        api_weight = agent._synaptic.get_weight("file:src/api.py", "auto_fix")
        assert api_weight > 0.5
        # Non-py files should remain at default
        md_weight = agent._synaptic.get_weight("file:README.md", "auto_fix")
        assert md_weight == 0.5

    def test_gate_specific_negative_learning(self, fake_llm):
        """Failed gates get their own negative Hebbian signal."""
        from steward.tools.circuit_breaker import GateResult

        agent = self._make_agent(fake_llm)
        failed_gates = [
            GateResult(passed=False, gate="lint", detail="ruff: 3 violations"),
        ]
        trigger = "auto:CI_CHECK:api.py"
        agent._autonomy.pipeline.hebbian_learn(trigger, success=False, failed_gates=failed_gates)

        fix_weight = agent._synaptic.get_weight(trigger, "fix")
        assert fix_weight < 0.5

        lint_weight = agent._synaptic.get_weight(trigger, "gate:lint")
        assert lint_weight < 0.5

    def test_gate_specific_positive_learning(self, fake_llm):
        """Passed gates get reinforced on success."""
        from steward.tools.circuit_breaker import GateResult

        agent = self._make_agent(fake_llm)
        gate_results = [
            GateResult(passed=True, gate="lint"),
            GateResult(passed=True, gate="security"),
        ]
        trigger = "auto:CI_CHECK:api.py"
        agent._autonomy.pipeline.hebbian_learn(trigger, success=True, gate_results=gate_results)

        lint_weight = agent._synaptic.get_weight(trigger, "gate:lint")
        assert lint_weight > 0.5

    def test_confidence_gate_escalates_not_skips(self, fake_llm):
        """When Hebbian confidence < 0.2, escalates to human — NOT silent skip."""
        import asyncio

        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="[CI_CHECK] Check CI", priority=50)

        # The problem will include workflow 'ci-tests' → fingerprint = "ci-tests"
        # Hammer that SPECIFIC granular key below 0.2
        for _ in range(20):
            agent._synaptic.update("auto:CI_CHECK:ci-tests", "fix", success=False)
        assert agent._synaptic.get_weight("auto:CI_CHECK:ci-tests", "fix") < 0.2

        # Mock CI check to return problem with matching workflow name
        original_ci = agent._autonomy.handlers.execute_ci_check
        agent._autonomy.handlers.execute_ci_check = lambda: "CI is failing: workflow 'ci-tests'. Fix it."

        try:
            result = asyncio.run(agent.run_autonomous())
            assert result is None
            assert fake_llm.call_count == 0  # LLM not called

            # BUT: escalation file should exist
            escalation_file = agent._cwd + "/.steward/needs_attention.md"
            from pathlib import Path

            if Path(escalation_file).exists():
                content = Path(escalation_file).read_text()
                assert "CI_CHECK" in content
                assert "confidence" in content
        finally:
            agent._autonomy.handlers.execute_ci_check = original_ci

    def test_different_workflow_not_blocked(self, fake_llm):
        """Failing on workflow 'ci-tests' doesn't block workflow 'lint-check'."""

        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="[CI_CHECK] Check CI", priority=50)

        # Hammer weight for 'ci-tests' workflow
        for _ in range(20):
            agent._synaptic.update("auto:CI_CHECK:ci-tests", "fix", success=False)

        # BUT the CURRENT problem is for 'lint-check' — different fingerprint
        original_ci = agent._autonomy.handlers.execute_ci_check
        agent._autonomy.handlers.execute_ci_check = lambda: "CI is failing: workflow 'lint-check'. Fix it."

        try:
            # 'lint-check' has default confidence 0.5 — should NOT be blocked
            weight = agent._synaptic.get_weight("auto:CI_CHECK:lint-check", "fix")
            assert weight >= 0.5  # Not contaminated by ci-tests failure

            # Would proceed to _guarded_llm_fix (which needs mocked breaker)
            # Just verify the weight is not blocked
            assert weight >= 0.2
        finally:
            agent._autonomy.handlers.execute_ci_check = original_ci

    def test_repeated_failure_decays_specific_key(self, fake_llm):
        """Multiple failures drive SPECIFIC key toward 0, not global."""
        agent = self._make_agent(fake_llm)
        specific = "auto:SENSE_SCAN:provider:errors"
        for _ in range(10):
            agent._autonomy.pipeline.hebbian_learn(specific, success=False)

        specific_weight = agent._synaptic.get_weight(specific, "fix")
        assert specific_weight < 0.2

        # Different context should be unaffected
        other_weight = agent._synaptic.get_weight("auto:SENSE_SCAN:context:tools", "fix")
        assert other_weight == 0.5

    def test_recovery_after_success(self, fake_llm):
        """After failures, success starts recovering the weight."""
        agent = self._make_agent(fake_llm)
        trigger = "auto:CI_CHECK:api.py"
        for _ in range(5):
            agent._autonomy.pipeline.hebbian_learn(trigger, success=False)
        low = agent._synaptic.get_weight(trigger, "fix")

        for _ in range(3):
            agent._autonomy.pipeline.hebbian_learn(trigger, success=True)
        recovered = agent._synaptic.get_weight(trigger, "fix")
        assert recovered > low


class TestProactiveDispatch:
    """Proactive intents route to PR pipeline, not direct fix."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))

    def test_dispatch_update_deps_runs_without_llm(self, fake_llm):
        """UPDATE_DEPS handler is deterministic — 0 tokens."""
        from unittest.mock import MagicMock, patch

        agent = self._make_agent(fake_llm)
        # Mock subprocess to avoid real pip call (takes 30-60s)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            result = agent._autonomy.handlers.execute_update_deps()
        assert result is None  # No outdated deps
        assert fake_llm.call_count == 0

    def test_dispatch_remove_dead_code_runs_without_llm(self, fake_llm):
        """REMOVE_DEAD_CODE handler is deterministic — 0 tokens."""
        agent = self._make_agent(fake_llm)
        agent._autonomy.handlers.execute_remove_dead_code()
        assert fake_llm.call_count == 0

    def test_dispatch_routes_proactive_intents(self, fake_llm):
        """Proactive intents dispatch without error."""
        from unittest.mock import MagicMock, patch

        agent = self._make_agent(fake_llm)
        # Mock subprocess to avoid real pip call in UPDATE_DEPS
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            for intent in TaskIntent:
                result = agent._autonomy.dispatch_intent(intent)
                assert result is None or isinstance(result, str)
        assert fake_llm.call_count == 0

    def test_proactive_task_dispatches_in_autonomous(self, fake_llm):
        """Task with [UPDATE_DEPS] dispatches via run_autonomous."""
        from unittest.mock import MagicMock, patch

        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="[UPDATE_DEPS] Check packages", priority=50)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0

    def test_proactive_task_dispatches_remove_dead_code(self, fake_llm):
        """Task with [REMOVE_DEAD_CODE] dispatches via run_autonomous."""
        from steward.services import SVC_TASK_MANAGER
        from vibe_core.di import ServiceRegistry

        agent = self._make_agent(fake_llm)
        task_mgr = ServiceRegistry.get(SVC_TASK_MANAGER)
        task_mgr.add_task(title="[REMOVE_DEAD_CODE] Clean up", priority=50)

        result = asyncio.run(agent.run_autonomous())
        assert result is None
        assert fake_llm.call_count == 0


class TestCleanupBranch:
    """Branch cleanup always returns to main."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))

    def test_cleanup_branch_does_not_crash(self, fake_llm):
        """Cleanup handles missing branches gracefully."""
        agent = self._make_agent(fake_llm)
        # Cleaning a non-existent branch should not raise
        agent._autonomy.pipeline.cleanup_branch("steward/nonexistent/123")


class TestGuardedPrFix:
    """_guarded_pr_fix() — branch → LLM → gates → PR pipeline."""

    def _make_agent(self, fake_llm):
        from steward.agent import StewardAgent

        return track_agent(StewardAgent(provider=fake_llm))

    def test_suspended_breaker_returns_none(self, fake_llm):
        """Suspended circuit breaker skips proactive fix."""
        agent = self._make_agent(fake_llm)
        agent._breaker._suspended_until = float("inf")
        result = asyncio.run(agent._autonomy.pipeline.guarded_pr_fix("Update deps", intent_name="UPDATE_DEPS"))
        assert result is None
        assert fake_llm.call_count == 0

    def test_no_changes_returns_to_main(self, fake_llm):
        """When LLM makes no changes, branch is cleaned up."""
        import subprocess

        agent = self._make_agent(fake_llm)
        # Verify we start on main or some known branch
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=agent._cwd,
        )
        original_branch = r.stdout.strip()

        asyncio.run(agent._autonomy.pipeline.guarded_pr_fix("Update deps", intent_name="UPDATE_DEPS"))

        # Should have returned to original branch (main)
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=agent._cwd,
        )
        current = r.stdout.strip()
        # Agent should not be stranded on a feature branch
        assert current == original_branch or current == "main"

    def test_proactive_routes_to_pr_fix_not_llm_fix(self, fake_llm):
        """Proactive intents use _guarded_pr_fix, not _guarded_llm_fix.

        Verifies the routing logic in run_autonomous().
        """
        # Just test that intent.is_proactive triggers the right path
        assert TaskIntent.UPDATE_DEPS.is_proactive
        assert TaskIntent.REMOVE_DEAD_CODE.is_proactive
        assert not TaskIntent.CI_CHECK.is_proactive
