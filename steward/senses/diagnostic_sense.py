"""
DiagnosticSense — Structured repo analysis for cross-repo diagnostics.

A Jnanendriya (knowledge sense) that deterministically analyzes a target
repo's health. 0 LLM tokens — pure infrastructure observation.

1. Shallow-clones a target repo
2. Runs pytest --co -q (test collection, no execution)
3. Checks CI status via gh run list
4. Parses .well-known/agent-federation.json
5. Reads data/federation/peer.json
6. Returns DiagnosticReport dataclass (structured, not prose)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("STEWARD.SENSE.DIAGNOSTIC")


@dataclass(frozen=True)
class CIStatus:
    """CI workflow status from gh run list."""

    workflow: str
    conclusion: str  # success, failure, cancelled, ""
    status: str  # completed, in_progress, queued


@dataclass(frozen=True)
class DiagnosticReport:
    """Structured diagnostic output — no prose, pure data."""

    repo: str
    clone_ok: bool = False
    test_count: int = 0
    test_collection_error: str = ""
    ci_statuses: tuple[CIStatus, ...] = ()
    ci_error: str = ""
    has_federation_descriptor: bool = False
    federation_descriptor: dict = field(default_factory=dict)
    has_peer_json: bool = False
    peer_capabilities: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_healthy(self) -> bool:
        """Quick health check: clone OK, tests collectible, CI not failing."""
        if not self.clone_ok:
            return False
        if self.test_collection_error:
            return False
        if any(ci.conclusion == "failure" for ci in self.ci_statuses):
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "clone_ok": self.clone_ok,
            "test_count": self.test_count,
            "test_collection_error": self.test_collection_error,
            "ci_statuses": [
                {"workflow": ci.workflow, "conclusion": ci.conclusion, "status": ci.status}
                for ci in self.ci_statuses
            ],
            "ci_error": self.ci_error,
            "has_federation_descriptor": self.has_federation_descriptor,
            "has_peer_json": self.has_peer_json,
            "peer_capabilities": list(self.peer_capabilities),
            "is_healthy": self.is_healthy,
            "errors": list(self.errors),
        }


def diagnose_repo(repo_url: str, *, timeout: int = 60) -> DiagnosticReport:
    """Run deterministic diagnostic on a target repo. 0 LLM tokens.

    Args:
        repo_url: Git clone URL or GitHub owner/repo shorthand
        timeout: Timeout for subprocess calls in seconds

    Returns:
        DiagnosticReport with structured findings
    """
    errors: list[str] = []
    clone_dir = None

    try:
        # 1. Shallow clone
        clone_dir = Path(tempfile.mkdtemp(prefix="steward_diag_"))
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", "--single-branch", repo_url, str(clone_dir / "repo")],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            repo_path = clone_dir / "repo"
            clone_ok = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            errors.append(f"clone failed: {e}")
            return DiagnosticReport(repo=repo_url, clone_ok=False, errors=tuple(errors))

        # 2. Test collection (no execution)
        test_count = 0
        test_error = ""
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", "--co", "-q"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(repo_path),
            )
            if result.returncode == 0:
                # Count lines that look like test items
                lines = [l for l in result.stdout.strip().splitlines() if l and not l.startswith("=")]
                test_count = len(lines)
            else:
                test_error = result.stderr[:200] if result.stderr else f"exit code {result.returncode}"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            test_error = str(e)[:200]

        # 3. CI status via gh run list
        ci_statuses: list[CIStatus] = []
        ci_error = ""
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--limit=5", "--json=name,conclusion,status"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=str(repo_path),
            )
            if result.returncode == 0 and result.stdout.strip():
                runs = json.loads(result.stdout)
                for run in runs:
                    ci_statuses.append(
                        CIStatus(
                            workflow=run.get("name", ""),
                            conclusion=run.get("conclusion", ""),
                            status=run.get("status", ""),
                        )
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            ci_error = str(e)[:200]

        # 4. Federation descriptor
        descriptor_path = repo_path / ".well-known" / "agent-federation.json"
        has_descriptor = descriptor_path.exists()
        descriptor = {}
        if has_descriptor:
            try:
                descriptor = json.loads(descriptor_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # 5. Peer JSON
        peer_path = repo_path / "data" / "federation" / "peer.json"
        has_peer = peer_path.exists()
        peer_caps: tuple[str, ...] = ()
        if has_peer:
            try:
                peer_data = json.loads(peer_path.read_text())
                peer_caps = tuple(peer_data.get("capabilities", []))
            except (json.JSONDecodeError, OSError):
                pass

        return DiagnosticReport(
            repo=repo_url,
            clone_ok=clone_ok,
            test_count=test_count,
            test_collection_error=test_error,
            ci_statuses=tuple(ci_statuses),
            ci_error=ci_error,
            has_federation_descriptor=has_descriptor,
            federation_descriptor=descriptor,
            has_peer_json=has_peer,
            peer_capabilities=peer_caps,
            errors=tuple(errors),
        )

    except Exception as e:
        errors.append(f"unexpected: {e}")
        return DiagnosticReport(repo=repo_url, errors=tuple(errors))

    finally:
        if clone_dir and clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
