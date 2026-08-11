"""Tests for PR Verdict Poster — GitHub API review posting."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from steward.pr_verdict_poster import VERDICT_TO_GITHUB_EVENT, PRVerdictPoster

# ── Verdict Mapping ────────────────────────────────────────────────


def test_verdict_mapping():
    assert VERDICT_TO_GITHUB_EVENT["approve"] == "APPROVE"
    assert VERDICT_TO_GITHUB_EVENT["request_changes"] == "REQUEST_CHANGES"
    assert VERDICT_TO_GITHUB_EVENT["comment"] == "COMMENT"


# ── Availability ───────────────────────────────────────────────────


def test_not_available_without_token():
    poster = PRVerdictPoster()
    poster._token = ""
    assert not poster.available


def test_available_with_token():
    poster = PRVerdictPoster()
    poster._token = "ghp_test123"
    assert poster.available


# ── Post Verdict ───────────────────────────────────────────────────


def test_post_verdict_no_token():
    poster = PRVerdictPoster()
    poster._token = ""

    result = poster.post_verdict(
        repo="org/repo",
        pr_number=42,
        verdict="approve",
        reason="all good",
    )
    assert result is False


def test_agent_city_legacy_approve_is_denied_without_network_call():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    with patch("urllib.request.urlopen") as mock_open:
        result = poster.post_verdict(
            repo="kimeisele/agent-city",
            pr_number=42,
            verdict="approve",
            reason="All checks passed",
            diagnostics={"ci_failing": False, "blast_radius": 3},
            source_agent="steward",
        )

    assert result is False
    mock_open.assert_not_called()
    assert poster._post_count == 0


def test_own_steward_review_can_still_post():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"
    mock_response = MagicMock(status=201)
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
        result = poster.post_verdict(repo="kimeisele/steward", pr_number=42, verdict="comment")

    assert result is True
    req = mock_open.call_args[0][0]
    assert "kimeisele/steward/pulls/42/reviews" in req.full_url
    assert json.loads(req.data)["event"] == "COMMENT"


def test_post_verdict_request_changes():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    mock_response = MagicMock()
    mock_response.status = 201
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = poster.post_verdict(
            repo="org/repo",
            pr_number=10,
            verdict="request_changes",
            reason="CI is failing",
        )

    assert result is True


def test_post_verdict_network_error():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    with patch("urllib.request.urlopen", side_effect=Exception("network error")):
        result = poster.post_verdict(
            repo="org/repo",
            pr_number=10,
            verdict="approve",
        )

    assert result is False
    assert poster._errors == 1


# ── Post from NADI Event ──────────────────────────────────────────


def test_post_from_nadi_event_missing_fields():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    # Missing repo
    assert poster.post_from_nadi_event({"pr_number": 42}) is False
    # Missing pr_number
    assert poster.post_from_nadi_event({"repo": "org/repo"}) is False


def test_post_from_nadi_event_full_payload():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    mock_response = MagicMock()
    mock_response.status = 201
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    payload = {
        "repo": "kimeisele/steward",
        "pr_number": 42,
        "verdict": "approve",
        "reason": "all checks passed",
        "diagnostics": {"ci_failing": False, "author_is_peer": True},
        "source_agent": "steward",
    }

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = poster.post_from_nadi_event(payload)

    assert result is True


def test_post_from_nadi_event_rejects_malformed_repository():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"

    assert (
        poster.post_from_nadi_event({"repo": "https://evil.example/kimeisele/steward/pull/42", "pr_number": 42})
        is False
    )


# ── Stats ──────────────────────────────────────────────────────────


def test_stats():
    poster = PRVerdictPoster()
    poster._token = "ghp_test"
    poster._post_count = 5
    poster._errors = 2

    stats = poster.stats()
    assert stats["available"] is True
    assert stats["post_count"] == 5
    assert stats["errors"] == 2
