"""
Provider package — LLM provider failover + vendor adapters.

Split for clarity:
  chamber.py  — ProviderChamber routing/failover (Karmendriya selection)
  adapters.py — Vendor API translation (Google, Mistral, Anthropic)

All public names re-exported here for backward compatibility:
  from steward.provider import ProviderChamber, build_chamber
"""

from __future__ import annotations

import logging
import os

from steward.provider.adapters import (
    GoogleAdapter,
    MistralAdapter,
)
from steward.provider.chamber import (
    _ADDR_GOOGLE,
    _ADDR_GROQ,
    _ADDR_MISTRAL,
    _PRANA_CHEAP,
    _PRANA_FREE,
    ProviderChamber,
    ProviderPayload,
    _is_transient,
    _normalize_usage,
)

logger = logging.getLogger("STEWARD.PROVIDER")


class _LazyAdapter:
    """Defers provider construction to first invoke().

    build_chamber() can take 9+ seconds because provider constructors
    (GoogleProvider, OpenAI client) make network calls to validate keys.
    Wrapping in _LazyAdapter makes build_chamber() instant — the real
    provider only constructs on the first actual LLM call.
    """

    def __init__(self, factory, name: str, supports_streaming: bool = False) -> None:
        self._factory = factory
        self._name = name
        self._delegate = None
        self._supports_streaming = supports_streaming

    def _ensure(self):
        if self._delegate is None:
            logger.info("Lazy init: %s (first call)", self._name)
            self._delegate = self._factory()
        return self._delegate

    def invoke(self, **kwargs):
        return self._ensure().invoke(**kwargs)


class _LazyStreamingAdapter(_LazyAdapter):
    """Lazy adapter that also supports streaming (MistralAdapter, etc.)."""

    def invoke_stream(self, **kwargs):
        return self._ensure().invoke_stream(**kwargs)


__all__ = [
    "ProviderChamber",
    "ProviderPayload",
    "GoogleAdapter",
    "MistralAdapter",
    "build_chamber",
    "_normalize_usage",
    "_is_transient",
    "_PRANA_CHEAP",
    "_PRANA_FREE",
    "_ADDR_GOOGLE",
    "_ADDR_MISTRAL",
    "_ADDR_GROQ",
]


# ── Chamber Builder ──────────────────────────────────────────────────


def _is_valid_key(key: str) -> bool:
    if not key:
        return False
    placeholders = ["your-", "xxx", "placeholder", "example", "test-key"]
    return not any(p in key.lower() for p in placeholders)


def build_chamber() -> ProviderChamber:
    """Build ProviderChamber from available API keys.

    FREE TIER ONLY. Paid providers disabled until operator approval.
    1. Google Gemini (free tier)
    2. Mistral (free tier)
    3. Groq (free tier)

    Loads keys from .env file (python-dotenv) if present.
    """
    # Load .env for local development (GitHub Secrets don't help locally)
    try:
        from dotenv import load_dotenv

        load_dotenv()  # Loads from .env in cwd or parent dirs
    except ImportError:
        pass  # dotenv optional — env vars from shell profile still work

    chamber = ProviderChamber()

    # Cell 1: Google Gemini (FREE)
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key and _is_valid_key(google_key):

        def _make_google(key=google_key):
            from vibe_core.runtime.providers.google import GoogleProvider

            return GoogleAdapter(GoogleProvider(api_key=key))

        chamber.add_provider(
            name="google_flash",
            provider=_LazyAdapter(_make_google, "google_flash"),
            model="gemini-2.5-flash",
            source_address=_ADDR_GOOGLE,
            prana=_PRANA_FREE,
            daily_call_limit=1000,
            cost_per_mtok=0.0,
        )

    # Cell 2: Mistral (FREE experiment)
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if mistral_key and _is_valid_key(mistral_key):

        def _make_mistral(key=mistral_key):
            from openai import OpenAI

            return MistralAdapter(OpenAI(api_key=key, base_url="https://api.mistral.ai/v1"))

        chamber.add_provider(
            name="mistral",
            provider=_LazyStreamingAdapter(_make_mistral, "mistral"),
            model="mistral-small-latest",
            source_address=_ADDR_MISTRAL,
            prana=_PRANA_FREE,
            daily_call_limit=2880,
            daily_token_limit=30_000_000,
            cost_per_mtok=0.10,
            supports_tools=True,
        )

    # Cell 3: Groq (FREE — llama-3.3-70b via OpenAI-compat API)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key and _is_valid_key(groq_key):

        def _make_groq(key=groq_key):
            from openai import OpenAI

            return MistralAdapter(OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1"))

        chamber.add_provider(
            name="groq",
            provider=_LazyStreamingAdapter(_make_groq, "groq"),
            model="llama-3.3-70b-versatile",
            source_address=_ADDR_GROQ,
            prana=_PRANA_FREE,
            daily_call_limit=1000,
            daily_token_limit=100_000,
            cost_per_mtok=0.0,
            supports_tools=True,
        )

    # ── PAID PROVIDERS DISABLED ──
    # DeepSeek (OpenRouter) and Anthropic (Claude) are PAID.
    # Until token budgets, model behavior, and costs are 100% predictable
    # and enterprise-safe, ONLY free-tier providers are allowed.
    # Re-enable only after explicit operator approval.

    if len(chamber) == 0:
        logger.warning("No providers — LLM calls will fail")
    else:
        logger.info("Chamber ready with %d providers", len(chamber))

    return chamber
