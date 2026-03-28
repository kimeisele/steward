"""Tests for PhaseHook infrastructure and concrete hooks.

Verifies:
- PhaseHookRegistry registers, dispatches, deduplicates
- Priority ordering works
- should_run gates are respected
- Concrete DHARMA hooks: health, reaper, marketplace, federation
- Concrete MOKSHA hooks: synapse, persistence, federation
- PhaseContext mutation (health_anomaly written by hooks, read by agent)
"""

from steward.phase_hook import (
    ALL_PHASES,
    DHARMA,
    GENESIS,
    KARMA,
    MOKSHA,
    BasePhaseHook,
    PhaseContext,
    PhaseHookRegistry,
)

# ── PhaseHookRegistry ────────────────────────────────────────────────


class DummyHook(BasePhaseHook):
    """Minimal hook for testing."""

    def __init__(self, name: str, phase: str, priority: int = 50, gate: bool = True):
        self._name = name
        self._phase = phase
        self._priority = priority
        self._gate = gate
        self.executed = False
        self.execution_order = -1

    @property
    def name(self) -> str:
        return self._name

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def priority(self) -> int:
        return self._priority

    def should_run(self, ctx: PhaseContext) -> bool:
        return self._gate

    def execute(self, ctx: PhaseContext) -> None:
        self.executed = True


class FailingHook(BasePhaseHook):
    """Hook that raises on execute."""

    def __init__(self, name: str, phase: str):
        self._name = name
        self._phase = phase

    @property
    def name(self) -> str:
        return self._name

    @property
    def phase(self) -> str:
        return self._phase

    def execute(self, ctx: PhaseContext) -> None:
        raise RuntimeError("hook exploded")


class TestPhaseHookRegistry:
    def test_register_and_dispatch(self):
        reg = PhaseHookRegistry()
        hook = DummyHook("test_hook", DHARMA)
        reg.register(hook)
        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(DHARMA, ctx)
        assert hook.executed

    def test_dedup_by_name(self):
        reg = PhaseHookRegistry()
        h1 = DummyHook("same_name", DHARMA)
        h2 = DummyHook("same_name", DHARMA)
        reg.register(h1)
        reg.register(h2)
        assert reg.hook_count(DHARMA) == 1

    def test_priority_ordering(self):
        """Hooks execute in priority order (lowest first)."""
        reg = PhaseHookRegistry()
        execution_order = []

        class OrderHook(BasePhaseHook):
            def __init__(self, n, pri):
                self._name = n
                self._priority = pri

            @property
            def name(self):
                return self._name

            @property
            def phase(self):
                return DHARMA

            @property
            def priority(self):
                return self._priority

            def execute(self, ctx):
                execution_order.append(self._name)

        reg.register(OrderHook("last", 90))
        reg.register(OrderHook("first", 10))
        reg.register(OrderHook("middle", 50))

        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(DHARMA, ctx)
        assert execution_order == ["first", "middle", "last"]

    def test_gate_skips_execution(self):
        reg = PhaseHookRegistry()
        hook = DummyHook("gated", DHARMA, gate=False)
        reg.register(hook)
        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(DHARMA, ctx)
        assert not hook.executed

    def test_failing_hook_doesnt_stop_others(self):
        """Exception in one hook doesn't prevent subsequent hooks."""
        reg = PhaseHookRegistry()
        failing = FailingHook("bad_hook", DHARMA)
        good = DummyHook("good_hook", DHARMA, priority=90)
        reg.register(failing)
        reg.register(good)
        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(DHARMA, ctx)
        assert good.executed
        assert any("bad_hook:error" in op for op in ctx.operations)

    def test_unregister(self):
        reg = PhaseHookRegistry()
        hook = DummyHook("removable", DHARMA)
        reg.register(hook)
        assert reg.hook_count(DHARMA) == 1
        assert reg.unregister(DHARMA, "removable")
        assert reg.hook_count(DHARMA) == 0

    def test_unregister_nonexistent(self):
        reg = PhaseHookRegistry()
        assert not reg.unregister(DHARMA, "ghost")

    def test_dispatch_wrong_phase_is_noop(self):
        reg = PhaseHookRegistry()
        hook = DummyHook("dharma_only", DHARMA)
        reg.register(hook)
        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(MOKSHA, ctx)
        assert not hook.executed

    def test_stats(self):
        reg = PhaseHookRegistry()
        reg.register(DummyHook("a", DHARMA))
        reg.register(DummyHook("b", DHARMA))
        reg.register(DummyHook("c", MOKSHA))
        s = reg.stats()
        assert s[DHARMA]["count"] == 2
        assert s[MOKSHA]["count"] == 1
        assert s[GENESIS]["count"] == 0

    def test_hook_count_all(self):
        reg = PhaseHookRegistry()
        reg.register(DummyHook("a", DHARMA))
        reg.register(DummyHook("b", MOKSHA))
        assert reg.hook_count() == 2

    def test_operations_logged(self):
        reg = PhaseHookRegistry()
        reg.register(DummyHook("my_hook", DHARMA))
        ctx = PhaseContext(cwd="/tmp")
        reg.dispatch(DHARMA, ctx)
        assert "my_hook:ok" in ctx.operations

    def test_all_phases_constant(self):
        assert GENESIS in ALL_PHASES
        assert DHARMA in ALL_PHASES
        assert KARMA in ALL_PHASES
        assert MOKSHA in ALL_PHASES
        assert len(ALL_PHASES) == 4


# ── PhaseContext ─────────────────────────────────────────────────────


class TestPhaseContext:
    def test_default_no_anomaly(self):
        ctx = PhaseContext(cwd="/tmp")
        assert not ctx.health_anomaly
        assert ctx.health_anomaly_detail == ""

    def test_mutable_anomaly(self):
        ctx = PhaseContext(cwd="/tmp")
        ctx.health_anomaly = True
        ctx.health_anomaly_detail = "test"
        assert ctx.health_anomaly
        assert ctx.health_anomaly_detail == "test"

    def test_operations_start_empty(self):
        ctx = PhaseContext(cwd="/tmp")
        assert ctx.operations == []


# ── Concrete DHARMA Hooks ────────────────────────────────────────────


class TestDharmaHealthHook:
    def test_healthy_vedana_no_anomaly(self):
        from steward.hooks.dharma import DharmaHealthHook

        class FakeVedana:
            health = 0.8
            guna = "sattva"
            error_pressure = 0.1
            context_pressure = 0.1

        hook = DharmaHealthHook()
        ctx = PhaseContext(cwd="/tmp", vedana=FakeVedana())
        hook.execute(ctx)
        assert not ctx.health_anomaly

    def test_critical_vedana_sets_anomaly(self):
        from steward.hooks.dharma import DharmaHealthHook

        class FakeVedana:
            health = 0.1
            guna = "tamas"
            error_pressure = 0.9
            context_pressure = 0.8

        hook = DharmaHealthHook()
        ctx = PhaseContext(cwd="/tmp", vedana=FakeVedana())
        hook.execute(ctx)
        assert ctx.health_anomaly
        assert "0.10" in ctx.health_anomaly_detail

    def test_none_vedana_noop(self):
        from steward.hooks.dharma import DharmaHealthHook

        hook = DharmaHealthHook()
        ctx = PhaseContext(cwd="/tmp", vedana=None)
        hook.execute(ctx)
        assert not ctx.health_anomaly


class TestDharmaReaperHook:
    def test_runs_with_reaper(self, fake_llm):
        """DharmaReaperHook calls reaper.reap() when reaper is registered."""
        from steward.agent import StewardAgent
        from steward.hooks.dharma import DharmaReaperHook
        from steward.services import SVC_REAPER
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        track_agent(StewardAgent(provider=fake_llm))
        reaper = ServiceRegistry.get(SVC_REAPER)
        assert reaper is not None

        hook = DharmaReaperHook()
        ctx = PhaseContext(cwd="/tmp")
        hook.execute(ctx)  # Should not crash


class TestDharmaMarketplaceHook:
    def test_runs_with_marketplace(self, fake_llm):
        from steward.agent import StewardAgent
        from steward.hooks.dharma import DharmaMarketplaceHook
        from steward.services import SVC_MARKETPLACE
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        track_agent(StewardAgent(provider=fake_llm))
        marketplace = ServiceRegistry.get(SVC_MARKETPLACE)
        assert marketplace is not None

        hook = DharmaMarketplaceHook()
        ctx = PhaseContext(cwd="/tmp")
        hook.execute(ctx)  # Should not crash


class TestDharmaFederationHook:
    def test_emits_heartbeat(self, fake_llm):
        from steward.agent import StewardAgent
        from steward.hooks.dharma import DharmaFederationHook
        from steward.services import SVC_FEDERATION
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        track_agent(StewardAgent(provider=fake_llm))
        federation = ServiceRegistry.get(SVC_FEDERATION)
        assert federation is not None
        initial_pending = federation.stats()["outbound_pending"]

        class FakeVedana:
            health = 0.9

        hook = DharmaFederationHook()
        ctx = PhaseContext(cwd="/tmp", vedana=FakeVedana())
        hook.execute(ctx)
        assert federation.stats()["outbound_pending"] > initial_pending


# ── Concrete MOKSHA Hooks ────────────────────────────────────────────


class TestMokshaSynapseHook:
    def test_runs_with_synapse_store(self, fake_llm):
        from steward.agent import StewardAgent
        from steward.hooks.moksha import MokshaSynapseHook
        from tests.conftest import track_agent

        track_agent(StewardAgent(provider=fake_llm))
        hook = MokshaSynapseHook()
        ctx = PhaseContext(cwd="/tmp")
        hook.execute(ctx)  # Should not crash


class TestMokshaPersistenceHook:
    def test_persists_reaper_and_marketplace(self, fake_llm, tmp_path):
        from steward.agent import StewardAgent
        from steward.hooks.moksha import MokshaPersistenceHook
        from tests.conftest import track_agent

        track_agent(StewardAgent(provider=fake_llm))
        steward_dir = tmp_path / ".steward"
        steward_dir.mkdir()
        federation_dir = tmp_path / "data" / "federation"
        federation_dir.mkdir(parents=True)

        hook = MokshaPersistenceHook()
        ctx = PhaseContext(cwd=str(tmp_path))
        hook.execute(ctx)
        # Files should be created in new locations
        assert (federation_dir / "peers.json").exists()
        assert (steward_dir / "marketplace.json").exists()


class TestMokshaFederationHook:
    def test_flush_without_transport_is_noop(self, fake_llm):
        from steward.agent import StewardAgent
        from steward.hooks.moksha import MokshaFederationHook
        from tests.conftest import track_agent

        track_agent(StewardAgent(provider=fake_llm))
        hook = MokshaFederationHook()
        ctx = PhaseContext(cwd="/tmp")
        hook.execute(ctx)  # No transport → no crash


# ── Integration: Default Hooks Registered at Boot ─────────────────────


class TestDefaultHookRegistration:
    def test_boot_registers_all_hooks(self, fake_llm):
        """boot() registers PhaseHookRegistry with all default hooks."""
        from steward.agent import StewardAgent
        from steward.services import SVC_PHASE_HOOKS
        from tests.conftest import track_agent
        from vibe_core.di import ServiceRegistry

        track_agent(StewardAgent(provider=fake_llm))
        hooks = ServiceRegistry.get(SVC_PHASE_HOOKS)
        assert hooks is not None
        assert hooks.hook_count(DHARMA) == 5  # health, reaper, marketplace, federation, immune
        assert hooks.hook_count(GENESIS) == 1  # discovery
        assert hooks.hook_count(MOKSHA) == 5  # synapse, health_report, persistence, federation, context_bridge

    def test_dharma_dispatch_through_agent(self, fake_llm):
        """Agent._phase_dharma() dispatches through PhaseHookRegistry."""
        from steward.agent import StewardAgent
        from steward.cetana import Phase
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent.clear_health_anomaly()
        agent._on_cetana_phase(Phase.DHARMA, None)
        # Healthy env → no anomaly, but hooks ran without crash
        assert not agent.health_anomaly

    def test_moksha_dispatch_through_agent(self, fake_llm):
        """Agent._phase_moksha() dispatches through PhaseHookRegistry."""
        from steward.agent import StewardAgent
        from steward.cetana import Phase
        from tests.conftest import track_agent

        agent = track_agent(StewardAgent(provider=fake_llm))
        agent._on_cetana_phase(Phase.MOKSHA, None)
        # Should not crash — all hooks execute cleanly
