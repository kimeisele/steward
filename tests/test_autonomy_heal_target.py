"""Flanke 3: HEAL_REPO heals exactly its target peer (1 Task = 1 Peer),
not a blind degraded[:3] sweep. Command-vs-State-Mismatch fix."""

from steward.autonomy import AutonomyEngine


class TestExtractTargetPeer:
    """The persistence-safe title parser must recover peer_ids, incl. hyphens."""

    def test_simple_peer(self):
        title = "[HEAL_REPO] Peer steward-test — Kirtan escalation"
        assert AutonomyEngine._extract_target_peer(title) == "steward-test"

    def test_hyphenated_peer(self):
        title = "[HEAL_REPO] Peer agent-city — Kirtan escalation"
        assert AutonomyEngine._extract_target_peer(title) == "agent-city"

    def test_peer_without_suffix(self):
        # no " — " delimiter → take rest of string
        title = "[HEAL_REPO] Peer steward-gateway"
        assert AutonomyEngine._extract_target_peer(title) == "steward-gateway"

    def test_non_heal_title(self):
        assert AutonomyEngine._extract_target_peer("[HEALTH_CHECK] something") is None

    def test_garbage(self):
        assert AutonomyEngine._extract_target_peer("no brackets here") is None


class TestHealTargetsOnlyTaskPeer:
    """Core fix: _execute_heal_repo heals ONLY the task's target peer,
    even with multiple degraded peers (no blind degraded[:3] sweep)."""

    def _run_heal(self, monkeypatch, target_title):
        import asyncio
        import time

        import steward.autonomy as autonomy_mod
        import steward.healer as healer_mod
        from steward.reaper import HeartbeatReaper
        from steward.services import SVC_REAPER
        from vibe_core.di import ServiceRegistry

        reaper = HeartbeatReaper(lease_ttl_s=900)
        now = time.time()
        for pid in ["agent-alpha", "steward-test", "agent-gamma"]:
            reaper.record_heartbeat(agent_id=pid, source="setup")
            reaper.get_peer(pid).last_seen = now - 999999
        reaper.reap(now=now)
        ServiceRegistry.register(SVC_REAPER, reaper)

        healed = []

        class _FakeResult:
            findings_fixed = 0
            findings_fixable = 0
            pr_url = None
            repo = "x"

        class _FakeHealer:
            def __init__(self, *a, **k):
                pass

            async def heal_repo(self, path):
                healed.append(str(path))
                return _FakeResult()

        # RepoHealer is imported INSIDE the method via `from steward.healer import RepoHealer`
        # → patch at the source module, not steward.autonomy
        monkeypatch.setattr(healer_mod, "RepoHealer", _FakeHealer)
        monkeypatch.setattr(autonomy_mod, "_resolve_peer_repo", lambda aid: aid)

        class _Task:
            id = "t1"
            title = target_title

        class _TM:
            def update_task(self, *a, **k):
                pass

        class _Status:
            COMPLETED = "COMPLETED"

        eng = AutonomyEngine.__new__(AutonomyEngine)
        eng.pipeline = type("P", (), {"_run_fn": staticmethod(lambda *a, **k: None)})()
        eng._synaptic = None
        eng._ledger = type("L", (), {"record_autonomous": staticmethod(lambda *a, **k: None)})()
        asyncio.run(eng._execute_heal_repo(_Task(), _TM(), _Status()))
        return healed

    def test_heals_only_target_not_all_three(self, monkeypatch):
        healed = self._run_heal(monkeypatch, "[HEAL_REPO] Peer steward-test — Kirtan escalation")
        assert healed == ["steward-test"], f"expected only steward-test, got {healed}"

    def test_targets_a_different_peer(self, monkeypatch):
        healed = self._run_heal(monkeypatch, "[HEAL_REPO] Peer agent-gamma — Kirtan escalation")
        assert healed == ["agent-gamma"], f"expected only agent-gamma, got {healed}"
