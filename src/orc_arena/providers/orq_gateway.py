"""orq.ai router gateway client — single provider for all warrior + judge calls.

Adapted from orq-battlebench/providers/orq_gateway.py. Uses ``AsyncOpenAI``
pointed at ``api.orq.ai/v2/router``; the gateway is OpenAI-compatible.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import AsyncIterator

from openai import AsyncOpenAI

from ..config import GatewayConfig


@dataclass
class GenerationResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    error: str | None = None


class OrqGateway:
    """OpenAI-compatible async client pointed at the orq.ai router gateway."""

    def __init__(self, cfg: GatewayConfig) -> None:
        api_key = os.environ.get(cfg.api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{cfg.api_key_env} is not set. Export it before running orc-arena."
            )
        self._cfg = cfg
        self._client = AsyncOpenAI(api_key=api_key, base_url=cfg.base_url)

    @property
    def client(self) -> AsyncOpenAI:
        """Exposed for ``instructor.from_openai`` usage in the judge panel."""
        return self._client

    async def stream_completion(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield response text chunks as they arrive from the gateway."""
        max_tokens = max_tokens or self._cfg.warrior_max_tokens
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        max_tokens: int | None = None,
    ) -> GenerationResult:
        """Non-streaming single call — used for judge invocations."""
        max_tokens = max_tokens or self._cfg.warrior_max_tokens
        t0 = time.time()
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            text = resp.choices[0].message.content or "" if resp.choices else ""
            tin = resp.usage.prompt_tokens if resp.usage else 0
            tout = resp.usage.completion_tokens if resp.usage else 0
            return GenerationResult(
                text=text,
                tokens_in=tin,
                tokens_out=tout,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception as exc:
            return GenerationResult(
                text="",
                latency_ms=int((time.time() - t0) * 1000),
                error=str(exc),
            )
