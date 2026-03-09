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
    AnthropicAdapter,
    GoogleAdapter,
    MistralAdapter,
    _AdapterResponse,
    _StreamDelta,
    _StreamedResponse,
)
from steward.provider.chamber import (
    _ADDR_ANTHROPIC,
    _ADDR_DEEPSEEK,
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

__all__ = [
    "ProviderChamber",
    "ProviderPayload",
    "GoogleAdapter",
    "MistralAdapter",
    "AnthropicAdapter",
    "build_chamber",
    "_normalize_usage",
    "_is_transient",
    "_StreamDelta",
    "_StreamedResponse",
    "_AdapterResponse",
    "_PRANA_FREE",
    "_PRANA_CHEAP",
    "_ADDR_GOOGLE",
    "_ADDR_MISTRAL",
    "_ADDR_DEEPSEEK",
    "_ADDR_ANTHROPIC",
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

    Priority order (free first, cheapest last):
    1. Google Gemini (free tier)
    2. Mistral (free experiment)
    3. Groq (free tier)
    4. DeepSeek via OpenRouter (cheap paid)
    5. Anthropic Claude (paid, highest capability)
    """
    chamber = ProviderChamber()

    # Cell 1: Google Gemini (FREE)
    google_key = os.environ.get("GOOGLE_API_KEY")
    if google_key and _is_valid_key(google_key):
        try:
            from vibe_core.runtime.providers.google import GoogleProvider

            raw_provider = GoogleProvider(api_key=google_key)
            adapter = GoogleAdapter(raw_provider)
            chamber.add_provider(
                name="google_flash",
                provider=adapter,
                model="gemini-2.5-flash",
                source_address=_ADDR_GOOGLE,
                prana=_PRANA_FREE,
                daily_call_limit=1000,
                cost_per_mtok=0.0,
            )
        except Exception as e:
            logger.warning("Google provider failed: %s", e)

    # Cell 2: Mistral (FREE experiment)
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if mistral_key and _is_valid_key(mistral_key):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=mistral_key, base_url="https://api.mistral.ai/v1")
            adapter = MistralAdapter(client)
            chamber.add_provider(
                name="mistral",
                provider=adapter,
                model="mistral-small-latest",
                source_address=_ADDR_MISTRAL,
                prana=_PRANA_FREE,
                daily_call_limit=2880,
                daily_token_limit=30_000_000,
                cost_per_mtok=0.10,
                supports_tools=True,
            )
        except ImportError:
            logger.warning("openai package needed for Mistral")
        except Exception as e:
            logger.warning("Mistral provider failed: %s", e)

    # Cell 3: Groq (FREE — llama-3.3-70b via OpenAI-compat API)
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key and _is_valid_key(groq_key):
        try:
            from openai import OpenAI

            client = OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1")
            adapter = MistralAdapter(client)  # OpenAI-compat, same adapter
            chamber.add_provider(
                name="groq",
                provider=adapter,
                model="llama-3.3-70b-versatile",
                source_address=_ADDR_GROQ,
                prana=_PRANA_FREE,
                daily_call_limit=1000,
                daily_token_limit=100_000,
                cost_per_mtok=0.0,
                supports_tools=True,
            )
        except ImportError:
            logger.warning("openai package needed for Groq")
        except Exception as e:
            logger.warning("Groq provider failed: %s", e)

    # Cell 4: DeepSeek via OpenRouter (cheap paid fallback)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key and _is_valid_key(openrouter_key):
        try:
            from vibe_core.runtime.providers.openrouter import OpenRouterProvider

            provider = OpenRouterProvider(api_key=openrouter_key)
            chamber.add_provider(
                name="deepseek",
                provider=provider,
                model="deepseek/deepseek-v3.2",
                source_address=_ADDR_DEEPSEEK,
                prana=_PRANA_CHEAP,
                daily_call_limit=0,
                cost_per_mtok=0.27,
                supports_tools=True,
            )
        except Exception as e:
            logger.warning("OpenRouter provider failed: %s", e)

    # Cell 5: Anthropic Claude (paid, highest capability)
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key and _is_valid_key(anthropic_key):
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=anthropic_key)
            adapter = AnthropicAdapter(client)
            chamber.add_provider(
                name="claude",
                provider=adapter,
                model="claude-sonnet-4-20250514",
                source_address=_ADDR_ANTHROPIC,
                prana=_PRANA_CHEAP,
                daily_call_limit=0,
                cost_per_mtok=3.0,
                supports_tools=True,
            )
        except ImportError:
            logger.warning("anthropic package needed for Claude")
        except Exception as e:
            logger.warning("Anthropic provider failed: %s", e)

    if len(chamber) == 0:
        logger.warning("No providers — LLM calls will fail")
    else:
        logger.info("Chamber ready with %d providers", len(chamber))

    return chamber
