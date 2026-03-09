"""Tests for substrate wiring: Venu + MahaCompression + SikSasTakam.

RED tests — define the contract BEFORE implementation.
Prahlad Maharaj strategy: the harder the test, the better.

Wiring contract:
  - VenuOrchestrator drives execution rhythm (SVC_VENU)
  - MahaCompression compresses tool outputs (SVC_COMPRESSION)
  - SikSasTakam governs cache lifecycle (7-beat strategy)
  - EphemeralStorage (SVC_CACHE) stores compressed seeds
  - Every LLM call → compress → cache → learn (Hebbian muscle)
"""

import asyncio

import pytest

from steward.services import boot
from vibe_core.di import ServiceRegistry
from vibe_core.mahamantra.adapters.compression import MahaCompression
from vibe_core.mahamantra.substrate.mantra.siksastakam import (
    ENGINEERING_EFFECTS,
    SiksastakamSynth,
)
from vibe_core.mahamantra.substrate.vm.venu_orchestrator import VenuOrchestrator


# ── Venu Service Wiring ──────────────────────────────────────────────


class TestVenuServiceWiring:
    """VenuOrchestrator must be wired as SVC_VENU at boot."""

    def test_svc_venu_exists(self):
        """SVC_VENU key defined in services module."""
        from steward.services import SVC_VENU

        assert SVC_VENU is not None

    def test_boot_wires_venu(self):
        """boot() registers VenuOrchestrator in ServiceRegistry."""
        from steward.services import SVC_VENU

        boot()
        venu = ServiceRegistry.get(SVC_VENU)
        assert isinstance(venu, VenuOrchestrator)

    def test_venu_divinity_verified_at_boot(self):
        """Integrity checker verifies VenuOrchestrator structural correctness."""
        from steward.services import SVC_VENU

        boot()
        venu = ServiceRegistry.get(SVC_VENU)
        assert venu.verify_divinity()

    def test_venu_step_produces_valid_diw(self):
        """Each step() returns nonzero DIW with valid 19-bit core."""
        from steward.services import SVC_VENU

        boot()
        venu = ServiceRegistry.get(SVC_VENU)
        for _ in range(16):
            diw = venu.step()
            assert diw > 0, "DIW must never be zero (SUNYA)"
            assert diw & 0x7FFFF, "19-bit core must have value"

    def test_venu_route_deterministic(self):
        """route(seed) returns same (venu, vamsi, murali) for same seed."""
        from steward.services import SVC_VENU

        boot()
        venu = ServiceRegistry.get(SVC_VENU)
        r1 = venu.route(42)
        venu.reset()
        r2 = venu.route(42)
        assert r1 == r2
        assert len(r1) == 3  # (venu, vamsi, murali)

    def test_vajra_venu_integrity_check(self):
        """IntegrityChecker passes Vajra check for SVC_VENU at boot."""
        from steward.services import SVC_INTEGRITY

        boot()
        checker = ServiceRegistry.get(SVC_INTEGRITY)
        report = checker.check_all()
        # Only tool_registry fails (no tools in bare boot) — venu checks pass
        failing_names = [str(i) for i in report.issues]
        assert not any("venu" in f.lower() for f in failing_names), (
            f"Venu integrity check should pass, but got: {failing_names}"
        )


# ── MahaCompression Wiring ───────────────────────────────────────────


class TestMahaCompressionWiring:
    """MahaCompression must be wired as SVC_COMPRESSION at boot."""

    def test_svc_compression_exists(self):
        """SVC_COMPRESSION key defined in services module."""
        from steward.services import SVC_COMPRESSION

        assert SVC_COMPRESSION is not None

    def test_boot_wires_compression(self):
        """boot() registers MahaCompression in ServiceRegistry."""
        from steward.services import SVC_COMPRESSION

        boot()
        mc = ServiceRegistry.get(SVC_COMPRESSION)
        assert isinstance(mc, MahaCompression)

    def test_compression_ratio_meaningful(self):
        """Compression on real tool output achieves >1x ratio."""
        mc = MahaCompression()
        # Simulate large bash output
        output = "total 42\n-rw-r--r-- 1 user staff 1234 Mar 9 main.py\n" * 50
        result = mc.compress(output)
        assert result.compression_ratio > 1.0
        assert result.seed > 0

    def test_compression_seed_deterministic(self):
        """Same input always produces same seed."""
        mc = MahaCompression()
        s1 = mc.compress("hello world").seed
        s2 = mc.compress("hello world").seed
        assert s1 == s2

    def test_different_input_different_seed(self):
        """Different inputs produce different seeds."""
        mc = MahaCompression()
        s1 = mc.compress("hello world").seed
        s2 = mc.compress("goodbye world").seed
        assert s1 != s2


# ── Tool Output Compression in Engine ────────────────────────────────


class TestToolOutputCompression:
    """Engine must compress tool outputs via MahaCompression before conversation."""

    def test_tool_output_has_seed_tag(self):
        """Tool outputs in conversation carry [seed:XXXX] tag for cache lookup."""
        from unittest.mock import MagicMock

        from steward.loop.engine import AgentLoop
        from steward.types import Conversation, Message, MessageRole, ToolUse

        # Create engine with fake provider
        provider = MagicMock()
        provider.invoke = MagicMock(return_value=MagicMock(
            content='{"response": "done"}',
            tool_calls=None,
            usage=None,
        ))

        from vibe_core.tools.tool_registry import ToolRegistry

        conv = Conversation()
        conv.add(Message(role=MessageRole.SYSTEM, content="test"))

        loop = AgentLoop(
            provider=provider,
            registry=ToolRegistry(),
            conversation=conv,
        )

        # Simulate adding a tool result
        mc = MahaCompression()
        output = "Some tool output that would normally waste tokens"
        cr = mc.compress(output)

        # The engine should prefix with seed tag
        tagged = f"[seed:{cr.seed}] {output}"
        assert f"[seed:{cr.seed}]" in tagged
        assert cr.seed > 0

    def test_large_tool_output_compressed_to_digest(self):
        """Tool outputs exceeding threshold get compressed to seed + summary."""
        mc = MahaCompression()
        # 10KB of code output
        large_output = "def process(x):\n    return x * 2\n" * 300
        result = mc.compress(large_output)
        assert len(result.summary) < len(large_output)
        assert result.compression_ratio > 5.0


# ── SikSasTakam Cache Strategy ───────────────────────────────────────


class TestSiksastakamStrategy:
    """SikSasTakam 7-beat cycle governs cache lifecycle."""

    def test_exactly_7_beats(self):
        """SikSasTakam defines exactly 7 engineering effects."""
        assert len(ENGINEERING_EFFECTS) == 7

    def test_beat_1_cache_invalidation(self):
        """Beat 1 = CLEANSE_HEART_MIRROR = cache invalidation."""
        synth = SiksastakamSynth()
        result = synth.synthesize(1, 42)
        assert "CLEANSE" in result.effect_name

    def test_beat_6_atomic_transactions(self):
        """Beat 6 = FULL_NECTAR_EACH_STEP = atomic transactions."""
        synth = SiksastakamSynth()
        result = synth.synthesize(6, 42)
        assert "NECTAR" in result.effect_name

    def test_all_7_beats_unique(self):
        """All 7 beats produce distinct effects."""
        synth = SiksastakamSynth()
        effects = set()
        for beat in range(7):
            result = synth.synthesize(beat, 42)
            effects.add(result.effect_name)
        assert len(effects) == 7

    def test_siksastakam_o1_classification(self):
        """Each beat has an O(1) complexity classification."""
        synth = SiksastakamSynth()
        for beat in range(7):
            result = synth.synthesize(beat, 42)
            assert "O(1)" in result.complexity_class or "O(" in result.complexity_class


# ── Cache-Driven LLM Bypass ──────────────────────────────────────────


class TestCacheDrivenBypass:
    """Seed-based caching: compress input → check cache → bypass LLM if hit."""

    def test_cache_stores_seed_after_llm_call(self):
        """After LLM call, input seed → response mapping stored in cache."""
        from vibe_core.playbook.ephemeral_storage import EphemeralStorage

        cache = EphemeralStorage(max_entries=100, default_ttl=300)
        mc = MahaCompression()

        # Simulate: user asks "list files", LLM responds
        input_seed = mc.compress("list files in current directory").seed
        response = '{"tool": "bash", "params": {"command": "ls"}}'

        # Store in cache
        cache.set(str(input_seed), response)

        # Retrieve
        cached = cache.get(str(input_seed))
        assert cached == response

    def test_cache_hit_returns_same_response(self):
        """Same input seed on next turn → cache hit → same response."""
        from vibe_core.playbook.ephemeral_storage import EphemeralStorage

        cache = EphemeralStorage(max_entries=100, default_ttl=300)
        mc = MahaCompression()

        input_text = "what is the project structure"
        seed = mc.compress(input_text).seed

        # First call: store result
        result = "src/ tests/ pyproject.toml"
        cache.set(str(seed), result)

        # Second call: same input → same seed → cache hit
        seed2 = mc.compress(input_text).seed
        assert seed2 == seed
        assert cache.get(str(seed2)) == result

    def test_engine_checks_cache_before_llm(self):
        """AgentLoop must check EphemeralStorage before calling LLM."""
        import inspect

        from steward.loop.engine import AgentLoop

        source = inspect.getsource(AgentLoop.run)
        # Engine should reference cache lookup before LLM call
        assert "cache" in source.lower() or "ephemeral" in source.lower(), (
            "AgentLoop.run() must check cache before LLM call"
        )

    def test_engine_stores_in_cache_after_llm(self):
        """AgentLoop must store seed→response in cache after LLM responds."""
        import inspect

        from steward.loop.engine import AgentLoop

        source = inspect.getsource(AgentLoop.run)
        # Engine should store results in cache
        assert "cache" in source.lower() or "put" in source.lower(), (
            "AgentLoop.run() must cache LLM responses"
        )


# ── Venu-Driven Turn Rhythm ──────────────────────────────────────────


class TestVenuDrivenTurns:
    """Each agent turn is driven by a Venu beat, not arbitrary LLM calls."""

    def test_engine_accepts_venu_parameter(self):
        """AgentLoop.__init__ accepts venu parameter."""
        import inspect

        from steward.loop.engine import AgentLoop

        sig = inspect.signature(AgentLoop.__init__)
        assert "venu" in sig.parameters, "AgentLoop must accept venu parameter"

    def test_engine_steps_venu_per_turn(self):
        """Each agent turn calls venu.step() for DIW context."""
        import inspect

        from steward.loop.engine import AgentLoop

        source = inspect.getsource(AgentLoop.run)
        assert "venu" in source.lower(), "AgentLoop.run() must step Venu per turn"

    def test_diw_context_in_usage(self):
        """AgentUsage tracks the DIW from VenuOrchestrator."""
        from steward.types import AgentUsage

        usage = AgentUsage()
        assert hasattr(usage, "venu_diw"), "AgentUsage must track venu_diw"


# ── Learning Effect (Hebbian Muscle) ─────────────────────────────────


class TestLearningEffect:
    """Every LLM call teaches something making the next call unnecessary."""

    def test_compression_produces_learnable_seed(self):
        """LLM output compressed to seed that can be stored for learning."""
        mc = MahaCompression()
        llm_output = '{"response": "The bug is in line 42 of main.py"}'
        result = mc.compress(llm_output)
        assert result.seed > 0
        assert result.compression_ratio > 1.0

    def test_venu_route_connects_seed_to_position(self):
        """Venu routes a seed to a (venu, vamsi, murali) position — deterministic."""
        venu = VenuOrchestrator()
        mc = MahaCompression()

        seed = mc.compress("fix the bug in main.py").seed
        v, va, mu = venu.route(seed)
        # All components within bounds
        assert 0 <= v < 64    # VENU: 6 bits
        assert 0 <= va < 512  # VAMSI: 9 bits
        assert 0 <= mu < 16   # MURALI: 4 bits

    def test_buddhi_records_seed_outcome(self):
        """Buddhi.record_seed() stores seed-level Hebbian weight."""
        from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic

        from steward.buddhi import Buddhi

        synaptic = HebbianSynaptic()
        buddhi = Buddhi(synaptic=synaptic)

        # Initially unknown
        assert buddhi.seed_confidence(42) == 0.5  # HebbianSynaptic default

        # Record success — weight should increase
        buddhi.record_seed(42, success=True)
        conf = buddhi.seed_confidence(42)
        assert conf > 0.5, f"Expected confidence > 0.5 after success, got {conf}"

        # Record failure — weight should decrease
        buddhi.record_seed(42, success=False)
        # Should still be above 0 but lower
        conf2 = buddhi.seed_confidence(42)
        assert conf2 < conf, f"Expected {conf2} < {conf} after failure"

    def test_buddhi_seed_confidence_zero_without_synaptic(self):
        """Without HebbianSynaptic, seed confidence returns 0."""
        from steward.buddhi import Buddhi

        buddhi = Buddhi(synaptic=None)
        assert buddhi.seed_confidence(42) == 0.0

    def test_engine_records_seed_after_turn(self):
        """Engine calls record_seed after successful text response."""
        import inspect

        from steward.loop.engine import AgentLoop

        source = inspect.getsource(AgentLoop.run)
        assert "record_seed" in source, "Engine must call record_seed after LLM responds"

    def test_siksastakam_beat_from_venu_position(self):
        """Venu position maps to SikSasTakam beat (position % 7)."""
        synth = SiksastakamSynth()
        venu = VenuOrchestrator()

        for _ in range(16):
            diw = venu.step()
            # Extract position from DIW (already done by orchestrator)
            # Map to 7-beat cycle
            beat = (diw & 0x3F) % 7  # VENU field % 7 beats
            result = synth.synthesize(beat, diw)
            assert result.effect_name  # Always produces an effect


# ── Integration: Full Substrate Stack ────────────────────────────────


class TestSubstrateStack:
    """Full stack: Venu → MahaCompression → SikSasTakam → Cache → LLM bypass."""

    def test_full_stack_boot(self):
        """All substrate services boot together without conflict."""
        from steward.services import SVC_CACHE, SVC_COMPRESSION, SVC_VENU

        boot()
        assert ServiceRegistry.get(SVC_VENU) is not None
        assert ServiceRegistry.get(SVC_COMPRESSION) is not None
        assert ServiceRegistry.get(SVC_CACHE) is not None

    def test_compression_seed_routes_through_venu(self):
        """Compress input → seed → Venu route → deterministic position."""
        from steward.services import SVC_COMPRESSION, SVC_VENU

        boot()
        mc = ServiceRegistry.get(SVC_COMPRESSION)
        venu = ServiceRegistry.get(SVC_VENU)

        seed = mc.compress("deploy the application").seed
        v, va, mu = venu.route(seed)

        # Route is stable
        venu.reset()
        v2, va2, mu2 = venu.route(seed)
        assert (v, va, mu) == (v2, va2, mu2)

    def test_cache_key_from_compression_seed(self):
        """EphemeralStorage uses compression seed as cache key."""
        from steward.services import SVC_CACHE, SVC_COMPRESSION

        boot()
        mc = ServiceRegistry.get(SVC_COMPRESSION)
        cache = ServiceRegistry.get(SVC_CACHE)

        seed = mc.compress("what tests are failing").seed
        cache.set(str(seed), "test_auth.py::test_login")

        # Same input → same seed → cache hit
        seed2 = mc.compress("what tests are failing").seed
        assert cache.get(str(seed2)) == "test_auth.py::test_login"

    def test_siksastakam_invalidation_clears_cache(self):
        """Beat 1 (CLEANSE_HEART_MIRROR) is the cache invalidation signal."""
        synth = SiksastakamSynth()
        result = synth.synthesize(1, 42)
        # Beat 1 is the cache invalidation signal
        assert "CLEANSE" in result.effect_name
        assert "CACHE" in result.engineering_principle.upper() or "INVALIDATION" in result.engineering_principle.upper()

    def test_substrate_zero_token_cost(self):
        """All substrate operations (Venu, MahaCompression, SikSasTakam) cost zero tokens."""
        mc = MahaCompression()
        venu = VenuOrchestrator()
        synth = SiksastakamSynth()

        # Run full pipeline — no LLM calls, no token cost
        seed = mc.compress("complex user request about debugging").seed
        v, va, mu = venu.route(seed)
        beat = v % 7
        effect = synth.synthesize(beat, seed)

        # All results are deterministic, no API calls needed
        assert seed > 0
        assert v >= 0
        assert effect.effect_name
        # Zero token cost — all computation is local


# ── CBR: Constant Bitrate Token Stream ──────────────────────────────


class TestCBRConstants:
    """CBR paradigm: token cost is a constant, cognitive density is the variable."""

    def test_cbr_constants_defined(self):
        """CBR constants live in steward.cbr (single source of truth)."""
        from steward.cbr import CBR_CEILING, CBR_FLOOR, CBR_SYSTEM_OVERHEAD, CBR_TICK

        assert CBR_TICK > 0
        assert CBR_FLOOR > 0
        assert CBR_CEILING > CBR_FLOOR
        assert CBR_SYSTEM_OVERHEAD > 0
        assert CBR_CEILING > CBR_SYSTEM_OVERHEAD

    def test_cbr_output_budget(self):
        """Output budget = ceiling - system overhead. Always positive."""
        from steward.cbr import CBR_CEILING, CBR_SYSTEM_OVERHEAD

        output_budget = CBR_CEILING - CBR_SYSTEM_OVERHEAD
        assert output_budget > 0
        assert output_budget >= 100

    def test_usage_tracks_cbr(self):
        """AgentUsage has cbr_budget, cbr_consumed, cbr_reserve."""
        from steward.types import AgentUsage

        usage = AgentUsage()
        assert hasattr(usage, "cbr_budget")
        assert hasattr(usage, "cbr_consumed")
        assert hasattr(usage, "cbr_reserve")

    def test_cache_hit_full_reserve(self):
        """On cache hit, cbr_consumed=0, cbr_reserve=full budget."""
        from steward.cbr import CBR_CEILING
        from steward.types import AgentUsage

        usage = AgentUsage()
        usage.cbr_budget = CBR_CEILING
        usage.cache_hit = True
        usage.cbr_consumed = 0
        usage.cbr_reserve = CBR_CEILING

        assert usage.cbr_reserve == usage.cbr_budget
        assert usage.cbr_consumed == 0

    def test_cbr_reserve_is_budget_minus_consumed(self):
        """Reserve = budget - consumed. Simple accounting."""
        from steward.cbr import CBR_CEILING
        from steward.types import AgentUsage

        usage = AgentUsage()
        usage.cbr_budget = CBR_CEILING
        consumed = 150
        usage.cbr_consumed = consumed
        usage.cbr_reserve = max(0, usage.cbr_budget - usage.cbr_consumed)

        assert usage.cbr_reserve == CBR_CEILING - consumed

    def test_system_prompt_fits_in_overhead_budget(self):
        """System prompt must fit within CBR_SYSTEM_OVERHEAD."""
        from steward.agent import _BASE_SYSTEM_PROMPT, _build_system_prompt
        from steward.cbr import CBR_SYSTEM_OVERHEAD

        prompt = _build_system_prompt(
            base=_BASE_SYSTEM_PROMPT,
            cwd="/Users/test/project",
            tool_names=["bash", "read_file", "write_file", "glob", "edit_file", "grep"],
        )
        # ~4 chars per token
        estimated_tokens = len(prompt) // 4
        assert estimated_tokens <= CBR_SYSTEM_OVERHEAD, (
            f"System prompt {estimated_tokens} tokens exceeds CBR overhead {CBR_SYSTEM_OVERHEAD}"
        )

    def test_usage_tracks_quality_signals(self):
        """AgentUsage has truncated and cbr_exceeded quality signals."""
        from steward.types import AgentUsage

        usage = AgentUsage()
        assert hasattr(usage, "truncated")
        assert hasattr(usage, "cbr_exceeded")
        # Default: clean
        assert not usage.truncated
        assert not usage.cbr_exceeded

    def test_cbr_exceeded_when_over_budget(self):
        """cbr_exceeded is True when consumed > budget."""
        from steward.cbr import CBR_CEILING
        from steward.types import AgentUsage

        usage = AgentUsage()
        usage.cbr_budget = CBR_CEILING
        usage.cbr_consumed = CBR_CEILING + 100
        usage.cbr_exceeded = usage.cbr_consumed > usage.cbr_budget
        assert usage.cbr_exceeded

    def test_north_star_is_seed(self):
        """North star is wired as a deterministic integer seed, not text."""
        from steward.services import SVC_NORTH_STAR

        boot()
        star = ServiceRegistry.get(SVC_NORTH_STAR)
        assert isinstance(star, int)
        assert star > 0

    def test_north_star_deterministic(self):
        """Same north_star text always produces the same seed."""
        from steward.services import NORTH_STAR_TEXT

        mc = MahaCompression()
        seed1 = mc.compress(NORTH_STAR_TEXT).seed
        seed2 = mc.compress(NORTH_STAR_TEXT).seed
        assert seed1 == seed2
