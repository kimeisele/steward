"""RepoHealer — the orchestrator. Diagnose → Classify → Fix → Verify → PR."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from steward.healer.compound import _COMPOUND_FIXERS
from steward.healer.helpers import _build_pr_body, _extract_ci_error_summary
from steward.healer.types import FixStrategy, HealResult, _FIXERS, classify
from steward.senses.diagnostic_sense import diagnose_repo

if TYPE_CHECKING:
    from steward.fix_pipeline import FixPipeline
    from steward.senses.diagnostic_sense import Finding
    from vibe_core.mahamantra.substrate.manas.synaptic import HebbianSynaptic

logger = logging.getLogger("STEWARD.HEALER")

# ── RepoHealer ─────────────────────────────────────────────────────────


class RepoHealer:
    """Stateless per-attempt repo healer.

    Neuro-symbolic pipeline: deterministic fixers first, compound
    (deterministic + gated LLM) for complex issues. The LLM is a tool
    in the registry — budget-controlled, one-shot, Iron-Gated.
    """

    def __init__(
        self,
        pipeline: "FixPipeline",
        run_fn: Callable[[str], Awaitable[str]],
        synaptic: "HebbianSynaptic",
    ) -> None:
        self._pipeline = pipeline
        self._run_fn = run_fn
        self._synaptic = synaptic

    async def _llm_compound_fix(
        self,
        finding: "Finding",
        workspace: Path,
    ) -> list[str]:
        """Phase B of COMPOUND: one LLM call via the agent's tool loop.

        The LLM uses the agent's existing tools (read, edit, bash) to
        investigate and fix. No context dumping, no response parsing.
        Changes land on disk through tool use. We detect them via git diff.
        """
        import subprocess

        # Extract the error summary from the CI log deterministically
        error_summary = _extract_ci_error_summary(finding, workspace)

        # Minimal instruction — the agent has tools, it can read files itself
        instruction = f"Fix CI failure in {workspace}. {error_summary}"

        try:
            await self._run_fn(instruction)
        except Exception as e:
            logger.warning("LLM compound fix failed: %s", e)
            return []

        # Detect what the LLM changed via git diff
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(workspace),
            )
            if r.returncode == 0 and r.stdout.strip():
                return [f.strip() for f in r.stdout.strip().split("\n") if f.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return []

    async def heal_repo(self, workspace: Path) -> HealResult:
        """Run full healing pipeline on an already-cloned repo.

        1. Diagnose (0 tokens)
        2. Classify: deterministic / compound / skip
        3. Apply deterministic fixes (0 tokens)
        4. Apply compound fixes (deterministic pipeline + gated LLM fallback)
        5. Run Iron Gate on all changed files
        6. Gate pass → create PR; gate fail → rollback + Hebbian failure
        """
        repo_name = workspace.name

        # Step 1: Diagnose
        try:
            report = diagnose_repo(str(workspace))
        except Exception as e:
            logger.error("Diagnosis failed for %s: %s", repo_name, e)
            return HealResult(repo=repo_name, error=str(e))

        if not report.findings:
            logger.info("Repo %s has no findings — nothing to heal", repo_name)
            return HealResult(repo=repo_name, findings_total=0)

        # Step 2: Classify
        deterministic: list["Finding"] = []
        compound: list["Finding"] = []
        for finding in report.findings:
            strategy = classify(finding.kind)
            if strategy == FixStrategy.DETERMINISTIC:
                deterministic.append(finding)
            elif strategy == FixStrategy.COMPOUND:
                compound.append(finding)

        total_fixable = len(deterministic) + len(compound)
        if total_fixable == 0:
            logger.info("Repo %s: %d findings but none fixable", repo_name, len(report.findings))
            return HealResult(
                repo=repo_name,
                findings_total=len(report.findings),
                findings_fixable=0,
            )

        # Step 3: Apply deterministic fixes (0 tokens)
        all_changed: list[str] = []
        applied: list[tuple["Finding", bool]] = []
        fixed_count = 0

        for finding in deterministic:
            fixer_fn = _FIXERS.get(finding.kind)
            if fixer_fn is None:
                continue
            try:
                changed = fixer_fn(finding, workspace)
                if changed:
                    all_changed.extend(changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info("Fixed %s: %s", finding.kind.value, finding.detail)
                else:
                    applied.append((finding, False))
            except Exception as e:
                logger.warning("Fixer %s failed: %s", finding.kind.value, e)
                applied.append((finding, False))

        # Step 4: Apply compound fixes (deterministic pipeline + gated LLM)
        for finding in compound:
            compound_fn = _COMPOUND_FIXERS.get(finding.kind)
            if compound_fn is None:
                applied.append((finding, False))
                continue
            try:
                # Phase A: deterministic extraction + classification
                changed = compound_fn(finding, workspace)
                if changed:
                    all_changed.extend(changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info("Compound-fixed %s: %s (deterministic)", finding.kind.value, finding.detail)
                    continue

                # Phase B: deterministic failed → one gated LLM call
                llm_changed = await self._llm_compound_fix(finding, workspace)
                if llm_changed:
                    all_changed.extend(llm_changed)
                    applied.append((finding, True))
                    fixed_count += 1
                    logger.info(
                        "Compound-fixed %s: %s (LLM, %d files)", finding.kind.value, finding.detail, len(llm_changed)
                    )
                else:
                    applied.append((finding, False))
            except Exception as e:
                logger.warning("Compound fixer %s failed: %s", finding.kind.value, e)
                applied.append((finding, False))

        if not all_changed and fixed_count == 0:
            return HealResult(
                repo=repo_name,
                findings_total=len(report.findings),
                findings_fixable=total_fixable,
                findings_fixed=0,
            )

        # Step 5: Verify via Iron Gate
        changed_set = set(all_changed)
        gate_passed = True

        if changed_set and hasattr(self._pipeline, "_breaker"):
            gate_results = self._pipeline._breaker.run_gates(changed_set)
            failed_gates = [g for g in gate_results if not g.passed]

            if failed_gates:
                gate_passed = False
                details = "; ".join(g.detail for g in failed_gates)
                logger.warning("Iron Gate FAILED for %s: %s", repo_name, details)

                self._pipeline._breaker.rollback_files(changed_set)
                self._pipeline._breaker.record_rollback()

                for finding in deterministic + compound:
                    self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=False)

                return HealResult(
                    repo=repo_name,
                    findings_total=len(report.findings),
                    findings_fixable=total_fixable,
                    findings_fixed=0,
                    error=f"Gate failure: {details}",
                )

        # Step 6: Gate passed — create PR
        pr_url = ""
        if changed_set:
            body = _build_pr_body(applied, gate_passed)
            pr_url = (
                self._pipeline._create_pr(
                    branch_name=f"steward/heal/{repo_name}",
                    intent_name="HEAL_REPO",
                    problem=f"Healing {repo_name}: {fixed_count} findings fixed",
                    changed_files=changed_set,
                )
                or ""
            )

        for finding in deterministic + compound:
            self._synaptic.update(f"heal:{finding.kind.value}:{repo_name}", "fix", success=True)

        logger.info(
            "Healed %s: %d/%d findings fixed, PR=%s",
            repo_name,
            fixed_count,
            total_fixable,
            pr_url or "(none)",
        )

        return HealResult(
            repo=repo_name,
            findings_total=len(report.findings),
            findings_fixable=total_fixable,
            findings_fixed=fixed_count,
            pr_url=pr_url,
        )
