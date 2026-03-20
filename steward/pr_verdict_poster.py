"""
PR Verdict Poster — Post federation PR review verdicts to GitHub API.

Closes the gap where FederationBridge emits OP_PR_REVIEW_VERDICT events
but never actually posts the review to GitHub. This module takes verdict
payloads and creates real GitHub PR reviews via the REST API.

Integration:
    MOKSHA phase: after flush_outbound(), post any pending verdicts
    Or: called directly by FederationBridge._handle_pr_review_request()

Requires GITHUB_TOKEN or GH_TOKEN in environment.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("STEWARD.PR_VERDICT")

GITHUB_API = "https://api.github.com"

# A2A/NADI verdict → GitHub review event
VERDICT_TO_GITHUB_EVENT: dict[str, str] = {
    "approve": "APPROVE",
    "request_changes": "REQUEST_CHANGES",
    "comment": "COMMENT",
}


class PRVerdictPoster:
    """Post PR review verdicts to GitHub.

    Usage:
        poster = PRVerdictPoster()
        posted = poster.post_verdict(
            repo="kimeisele/agent-city",
            pr_number=42,
            verdict="approve",
            reason="All checks passed",
            diagnostics={"ci_passing": True},
        )
    """

    def __init__(self) -> None:
        self._token = self._load_token()
        self._post_count: int = 0
        self._errors: int = 0

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _load_token(self) -> str:
        token = os.environ.get("GITHUB_TOKEN", "") or os.environ.get("GH_TOKEN", "")
        if not token:
            token_file = Path.home() / ".config" / "gh_token"
            if token_file.exists():
                token = token_file.read_text().strip()
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "steward-pr-verdict/1.0",
        }

    def post_verdict(
        self,
        repo: str,
        pr_number: int,
        verdict: str,
        reason: str = "",
        diagnostics: dict | None = None,
        source_agent: str = "steward",
    ) -> bool:
        """Post a PR review verdict to GitHub.

        Args:
            repo: Repository in "owner/name" format
            pr_number: Pull request number
            verdict: One of "approve", "request_changes", "comment"
            reason: Human-readable reason for the verdict
            diagnostics: Optional diagnostic details
            source_agent: Who produced the verdict

        Returns:
            True if review was posted successfully
        """
        if not self._token:
            logger.warning("PR_VERDICT: no GitHub token, skipping post")
            return False

        event = VERDICT_TO_GITHUB_EVENT.get(verdict, "COMMENT")

        # Build review body
        body_parts = [f"## Federation PR Review by `{source_agent}`\n"]
        body_parts.append(f"**Verdict**: {verdict.upper()}\n")
        if reason:
            body_parts.append(f"**Reason**: {reason}\n")

        if diagnostics:
            body_parts.append("\n### Diagnostics\n")
            for key, value in diagnostics.items():
                if key == "blast_radius":
                    body_parts.append(f"- Blast radius: {value} files\n")
                elif key == "ci_failing":
                    body_parts.append(f"- CI status: {'failing' if value else 'passing'}\n")
                elif key == "has_core_files":
                    body_parts.append(f"- Core files modified: {'yes' if value else 'no'}\n")
                elif key == "author_is_peer":
                    body_parts.append(f"- Author is federation peer: {'yes' if value else 'no'}\n")

        body_parts.append("\n---\n*Posted automatically by Steward federation PR review pipeline.*")
        body = "".join(body_parts)

        return self._create_review(repo, pr_number, event, body)

    def _create_review(self, repo: str, pr_number: int, event: str, body: str) -> bool:
        """Create a PR review via GitHub REST API."""
        import urllib.request

        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/reviews"
        payload = json.dumps({"body": body, "event": event}).encode()

        req = urllib.request.Request(url, data=payload, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 201):
                    self._post_count += 1
                    logger.info(
                        "PR_VERDICT: posted %s review on %s#%d",
                        event,
                        repo,
                        pr_number,
                    )
                    return True
                logger.warning(
                    "PR_VERDICT: unexpected status %d for %s#%d",
                    resp.status,
                    repo,
                    pr_number,
                )
                self._errors += 1
                return False
        except Exception as e:
            logger.warning("PR_VERDICT: failed to post review on %s#%d: %s", repo, pr_number, e)
            self._errors += 1
            return False

    def post_from_nadi_event(self, payload: dict) -> bool:
        """Post a verdict from a NADI OP_PR_REVIEW_VERDICT payload.

        This is the integration point: FederationBridge emits the verdict,
        MokshaFederationHook calls this to actually post it.
        """
        repo = payload.get("repo", "")
        pr_number = payload.get("pr_number")
        verdict = payload.get("verdict", "comment")
        reason = payload.get("reason", "")
        diagnostics = payload.get("diagnostics", {})
        source_agent = payload.get("source_agent", "steward")

        if not repo or not pr_number:
            logger.warning("PR_VERDICT: missing repo or pr_number in NADI event")
            return False

        return self.post_verdict(
            repo=repo,
            pr_number=pr_number,
            verdict=verdict,
            reason=reason,
            diagnostics=diagnostics,
            source_agent=source_agent,
        )

    def stats(self) -> dict:
        return {
            "available": self.available,
            "post_count": self._post_count,
            "errors": self._errors,
        }
