"""Fetch the list of workspace-enabled, chat-capable models from orq.ai.

Endpoint strategy (ported from the chennai research):

* ``GET /v2/router/models``, the **workspace-enabled subset**: models
  disabled in the Model Garden simply don't appear. Primary source.
* ``GET /v3/router/models``, full routable catalog; fallback.
* ``GET /v2/models``, full Model Garden with an authoritative ``type``
  field; used to narrow to ``type == "chat"``. Regex patterns stay as a
  safety net when it's unreachable.

Results cache for 24h at ``~/.cache/orq-arena/models.json``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import GatewayConfig

CACHE_DIR = Path.home() / ".cache" / "orq-arena"
CACHE_FILE = CACHE_DIR / "models.json"
CACHE_TTL_SECONDS = 24 * 3600

_NON_CHAT_PATTERNS: tuple[str, ...] = (
    "embedding",
    "text-embedding",
    "-embed",
    "tts",
    "-tts-",
    "stt",
    "-stt-",
    "whisper",
    "moderation",
    "rerank",
    "ocr",
    "dall-e",
    "imagen",
    "gpt-image",
    "image-",
    "-image-",
    "speech-",
    "voice-",
)
_NON_CHAT_RE = re.compile("|".join(re.escape(p) for p in _NON_CHAT_PATTERNS), re.I)


@dataclass
class ModelEntry:
    """A single gateway-routable model."""

    id: str
    provider: str
    created: int = 0


@dataclass
class ModelList:
    """The result of a fetch, plus provenance for the UI."""

    models: list[ModelEntry]
    source: str  # "live" | "cache" | "fallback"
    fetched_at: float = field(default_factory=time.time)


def _strip_noise(models: list[ModelEntry]) -> list[ModelEntry]:
    kept: list[ModelEntry] = []
    seen: set[str] = set()
    for m in models:
        if _NON_CHAT_RE.search(m.id) or m.id in seen:
            continue
        seen.add(m.id)
        kept.append(m)
    return kept


def _parse_payload(data: dict) -> list[ModelEntry]:
    entries: list[ModelEntry] = []
    for row in data.get("data", []):
        model_id = row.get("id")
        if not isinstance(model_id, str):
            continue
        if row.get("object") not in (None, "model"):
            continue
        provider = row.get("owned_by") or model_id.split("/", 1)[0]
        entries.append(
            ModelEntry(id=model_id, provider=str(provider), created=int(row.get("created") or 0))
        )
    return _strip_noise(entries)


def _write_cache(models: list[ModelEntry]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "data": [
                        {"id": m.id, "owned_by": m.provider, "created": m.created} for m in models
                    ],
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # cache is advisory


def _read_cache() -> tuple[list[ModelEntry], float] | None:
    if not CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return _parse_payload(raw), float(raw.get("fetched_at") or 0.0)


def _host(cfg: GatewayConfig) -> str:
    parsed = urlparse(cfg.base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _catalog_urls(cfg: GatewayConfig) -> list[str]:
    host = _host(cfg)
    urls = [f"{host}/v2/router/models", f"{host}/v3/router/models"]
    configured = cfg.base_url.rstrip("/") + "/models"
    if configured not in urls:
        urls.append(configured)
    return urls


async def _fetch_type_map(
    client: httpx.AsyncClient, cfg: GatewayConfig, api_key: str
) -> dict[str, str]:
    """``{model_id: type}`` from the Model Garden; empty dict on failure."""
    try:
        resp = await client.get(
            f"{_host(cfg)}/v2/models", headers={"Authorization": f"Bearer {api_key}"}
        )
        resp.raise_for_status()
        payload = resp.json()
        rows = (
            payload
            if isinstance(payload, list)
            else (payload.get("data") or payload.get("models") or [])
        )
        return {
            row["id"]: row.get("type", "")
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
    except (httpx.HTTPError, ValueError, KeyError):
        return {}


def _filter_by_type(entries: list[ModelEntry], type_map: dict[str, str]) -> list[ModelEntry]:
    if not type_map:
        return entries
    return [m for m in entries if not type_map.get(m.id) or type_map[m.id] == "chat"]


async def fetch_price_map(cfg: GatewayConfig) -> dict[str, tuple[float, float]]:
    """``{router_id: ($/M input, $/M output)}`` from the Model Garden.

    Garden rows key as ``provider/model_id``, which is exactly the router
    slug (verified 12/12 against the shipped config). Empty dict on any
    failure; pricing is advisory, never blocks a run.
    """
    api_key = os.environ.get(cfg.api_key_env, "")
    if not api_key:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_host(cfg)}/v2/models", headers={"Authorization": f"Bearer {api_key}"}
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return {}
    rows = (
        payload
        if isinstance(payload, list)
        else (payload.get("data") or payload.get("models") or [])
    )
    prices: dict[str, tuple[float, float]] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("model_id"):
            continue
        rid = f"{row.get('provider')}/{row['model_id']}"
        md = row.get("metadata") or {}
        cin = md.get("million_tokens_input_cost")
        cout = md.get("million_tokens_output_cost")
        if cin is None:
            cin = (row.get("input_cost") or 0.0) * 1000  # input_cost is $/1k tok
        if cout is None:
            cout = (row.get("output_cost") or 0.0) * 1000
        if isinstance(cin, (int, float)) and isinstance(cout, (int, float)):
            prices[rid] = (float(cin), float(cout))
    return prices


async def fetch_chat_models(
    cfg: GatewayConfig,
    *,
    force_refresh: bool = False,
) -> ModelList:
    """Chat-capable, workspace-active models; cached, with graceful fallback."""
    api_key = os.environ.get(cfg.api_key_env, "")
    now = time.time()

    cached = _read_cache()
    if cached is not None and not force_refresh and now - cached[1] < CACHE_TTL_SECONDS:
        return ModelList(models=cached[0], source="cache", fetched_at=cached[1])

    if api_key:
        async with httpx.AsyncClient(timeout=10.0) as client:
            type_map = await _fetch_type_map(client, cfg, api_key)
            for url in _catalog_urls(cfg):
                try:
                    resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
                    resp.raise_for_status()
                    models = _filter_by_type(_parse_payload(resp.json()), type_map)
                    if models:
                        _write_cache(models)
                        return ModelList(models=models, source="live", fetched_at=now)
                except (httpx.HTTPError, ValueError):
                    continue

    if cached is not None:
        return ModelList(models=cached[0], source="cache", fetched_at=cached[1])

    return ModelList(models=[], source="fallback", fetched_at=now)
