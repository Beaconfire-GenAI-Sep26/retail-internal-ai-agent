"""The Claude adapter for the `reason` node.

One streamed structured-output call per turn on the beta client, so server-side fallbacks apply.
No tools, no sampling parameters, adaptive thinking (Opus 5.5's only mode). Retries live in the
SDK only (`max_retries`). The control message goes last as a mid-conversation system message.
"""

from __future__ import annotations

import json
import time
from typing import Any

import anthropic

from app.config import Settings
from app.errors import INTERNAL, MODEL_REFUSED, MODEL_TRUNCATED, UPSTREAM_UNAVAILABLE
from app.llm.base import ModelError, ModelReply, RenderedPrompt
from app.llm.schemas import output_config_format

BETAS = ["server-side-fallback-2026-07-01"]
MAX_TOKENS = 32000
RETRY_MAX_TOKENS = 64000


def usage_dict(usage: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        value = getattr(usage, key, None)
        if isinstance(value, int):
            out[key] = value
    return out


class AnthropicReasonModel:
    name = "anthropic"

    def __init__(self, settings: Settings, *, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.client = client or anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None,
            max_retries=settings.agent_max_retries,
            timeout=anthropic.Timeout(600.0, read=180.0, write=60.0, connect=10.0),
        )

    def request_params(self, prompt: RenderedPrompt, max_tokens: int = MAX_TOKENS) -> dict[str, Any]:
        system, messages = prompt.to_messages()
        params: dict[str, Any] = {
            "model": self.settings.anthropic_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "output_config": {"format": output_config_format(), "effort": self.settings.agent_effort},
            "betas": BETAS,
            "fallbacks": "default",
        }
        if self.settings.agent_speed == "fast":
            params["speed"] = "fast"
        return params

    async def _call(self, params: dict[str, Any]) -> tuple[Any, int]:
        started = time.monotonic()
        try:
            async with self.client.beta.messages.stream(**params) as stream:
                message = await stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ModelError(INTERNAL, "The Claude API rejected the credentials. Check ANTHROPIC_API_KEY in agent/.env.") from exc
        except anthropic.BadRequestError as exc:
            raise ModelError(INTERNAL, f"The Claude API rejected the request: {exc.message}") from exc
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise ModelError(UPSTREAM_UNAVAILABLE, f"The Claude API is unavailable: {type(exc).__name__}") from exc
        except anthropic.APIStatusError as exc:
            code = UPSTREAM_UNAVAILABLE if exc.status_code >= 500 else INTERNAL
            raise ModelError(code, f"The Claude API returned {exc.status_code}: {exc.message}") from exc
        return message, int((time.monotonic() - started) * 1000)

    async def reason(self, prompt: RenderedPrompt, state: dict[str, Any]) -> ModelReply:
        params = self.request_params(prompt)
        message, latency = await self._call(params)
        if message.stop_reason == "max_tokens":
            params = self.request_params(prompt, RETRY_MAX_TOKENS)
            message, latency = await self._call(params)
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise ModelError(MODEL_REFUSED, f"The model declined the turn (category {category}).")
        if message.stop_reason == "max_tokens":
            raise ModelError(MODEL_TRUNCATED, f"The turn hit max_tokens twice (last limit {RETRY_MAX_TOKENS}).")
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text")
        try:
            output = json.loads(text)
        except ValueError:
            output = None
        return ModelReply(
            output=output if isinstance(output, dict) else None,
            raw_text=text,
            model=getattr(message, "model", self.settings.anthropic_model),
            stop_reason=message.stop_reason or "",
            usage=usage_dict(message.usage),
            latency_ms=latency,
            request_id=getattr(message, "_request_id", None),
        )
