"""orq.ai router gateway client, single provider for all model calls.

Uses ``AsyncOpenAI`` pointed at ``api.orq.ai/v3/router``; the gateway is
OpenAI-compatible. Judge calls share ``.client`` via evaluatorq.

At default config, credential/host resolution is delegated to evaluatorq's
``resolve_llm_client`` (the company-wide single source of truth: honors
``ORQ_BASE_URL`` for staging, one shared implementation). Setting ``base_url``
or ``api_key_env`` in the YAML is a bring-your-own-endpoint opt-out: the run
goes exactly where the config says, with no env-precedence surprises.
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

import httpx
from openai import AsyncOpenAI

from ..config import GatewayConfig


class OrqGateway:
    """OpenAI-compatible async client pointed at the orq.ai router gateway."""

    def __init__(self, cfg: GatewayConfig) -> None:
        self._cfg = cfg
        # read = max silence between stream chunks; generous so thinking models
        # can pause for minutes before the first token. No total-duration cap,
        # a model loses on its words, never on its network.
        timeout = httpx.Timeout(
            connect=10.0, read=float(cfg.stream_read_timeout_s), write=60.0, pool=60.0
        )
        defaults = GatewayConfig()
        at_defaults = (cfg.base_url, cfg.api_key_env) == (
            defaults.base_url, defaults.api_key_env
        )
        if at_defaults:
            # api.orq.ai is the user-facing host; require_orq stops OPENAI_API_KEY
            # from silently capturing a run (arena ids are router ids).
            from evaluatorq.common.llm_client import (MissingLLMCredentialsError,
                                                      resolve_llm_client)

            try:
                resolved = resolve_llm_client(
                    default_orq_host="https://api.orq.ai", require_orq=True
                )
            except MissingLLMCredentialsError as exc:
                raise RuntimeError(
                    f"{cfg.api_key_env} is not set. Export it before running orq-arena."
                ) from exc
            self._client = resolved.client.with_options(timeout=timeout)
        else:  # BYO endpoint: the YAML named the endpoint and key explicitly.
            api_key = os.environ.get(cfg.api_key_env, "")
            if not api_key:
                raise RuntimeError(
                    f"{cfg.api_key_env} is not set. Export it before running orq-arena."
                )
            self._client = AsyncOpenAI(
                api_key=api_key, base_url=cfg.base_url, timeout=timeout
            )

    @property
    def client(self) -> AsyncOpenAI:
        """Exposed so evaluatorq's jury rides the same router client."""
        return self._client

    async def stream_completion(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None = None,
        extra_body: dict[str, Any] | None = None,
        usage_out: dict[str, Any] | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield ``(kind, text)`` chunks: kind is ``"text"`` or ``"think"``.

        ``extra_body`` carries raw router controls (``thinking`` /
        ``reasoning_effort``) verbatim. ``"think"`` chunks are best-effort,
        visible reasoning deltas are optional per the router contract. Exact
        token usage and finish_reason land in ``usage_out``.
        """
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens or self._cfg.candidate_max_tokens,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=extra_body or None,
        )
        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None and usage_out is not None:
                usage_out["input_tokens"] = usage.prompt_tokens or 0
                usage_out["output_tokens"] = usage.completion_tokens or 0
                details = getattr(usage, "completion_tokens_details", None)
                usage_out["reasoning_tokens"] = getattr(details, "reasoning_tokens", 0) or 0
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason and usage_out is not None:
                usage_out["finish_reason"] = choice.finish_reason
            delta = choice.delta
            if delta is None:
                continue
            # The router surfaces visible CoT as `reasoning` on the delta
            # (observed for Anthropic/Gemini thinking); `reasoning_content` is
            # the DeepSeek-style spelling. Both optional per the contract.
            extra = delta.model_extra or {}
            reasoning_piece = extra.get("reasoning") or getattr(delta, "reasoning_content", None)
            if reasoning_piece:
                yield ("think", str(reasoning_piece))
            if delta.content:
                yield ("text", delta.content)
