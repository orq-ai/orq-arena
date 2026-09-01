"""Model metadata from the orq.ai catalog, plus the workspace-enabled subset.

Two questions, two sources, because only one of them needs a credential:

* **What exists, what it costs, what it can do** comes from
  ``GET {host}/v2/model-catalog``. It is public, needs no key, and states
  ``endpoints``, ``pricing`` per 1M tokens, ``deprecated`` and
  ``context_window`` outright. This is why the model picker and the cost
  projection work before the user has authenticated at all.
* **What this workspace turned on** comes from ``GET {host}/v2/router/models``,
  which does need a key. Models disabled in the Model Garden simply don't
  appear. When a key is present the catalog is narrowed to that subset; when it
  isn't, the full catalog stands, which is a better answer than the empty list
  the old key-gated path returned.

This replaced a substring regex over model ids that guessed chat capability
from fragments like "whisper" and "dall-e", and a price reader that reconciled
two different Model Garden cost representations by hand. The catalog states
both, so neither guess is needed.

Results cache for 24h at ``~/.cache/orq-arena/models.json``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import DEFAULT_ORQ_HOST, ORQ_API_KEY_ENV, OrqAIGatewayConfig

CACHE_DIR = Path.home() / ".cache" / "orq-arena"
CACHE_FILE = CACHE_DIR / "models.json"
CACHE_TTL_SECONDS = 24 * 3600

# The cached rows carry catalog fields now. A file written before that lacks
# `endpoints`, and reading it as though it had them would drop every model from
# the picker, so the old shape is ignored rather than misread.
CACHE_VERSION = 2


@dataclass
class ModelEntry:
    """A model as the catalog describes it.

    ``endpoints`` is the authoritative capability statement: ``"chat"`` for
    chat completions, ``"responses"`` for the Responses API that evaluatorq
    1.32.4 prefers for judges because it is the endpoint the router prices.
    ``price_in`` / ``price_out`` are dollars per 1M tokens, ``None`` when the
    catalog carries no price, which is not the same as free.
    """

    id: str
    provider: str
    created: int = 0
    endpoints: tuple[str, ...] = ()
    deprecated: bool = False
    context_window: int | None = None
    price_in: float | None = None
    price_out: float | None = None

    @property
    def is_chat(self) -> bool:
        return "chat" in self.endpoints

    @property
    def has_responses(self) -> bool:
        return "responses" in self.endpoints


@dataclass
class ModelList:
    """The result of a fetch, plus provenance for the UI.

    ``source`` is what the fetch did, not what was on disk: ``live`` for rows
    off the network, ``cache`` for a cache still inside its TTL, ``stale`` for a
    cache served because the fetch failed, ``fallback`` for nothing at all.
    ``stale`` exists because ``refresh-catalog`` used to report a failed refresh
    as ``live``, which is the one answer that command must never give.
    ``fetched_at`` is when the rows were fetched, so an age of 0s means fresh.
    """

    models: list[ModelEntry]
    source: str  # "live" | "cache" | "stale" | "fallback"
    fetched_at: float = field(default_factory=time.time)


def catalog_host(cfg: OrqAIGatewayConfig) -> str:
    """The host the catalog and prices come from, resolved like live traffic.

    At default config the completion client is built by evaluatorq's resolver,
    which honours ``ORQ_BASE_URL``. Deriving this host from ``cfg.base_url``
    instead meant a staging run was priced against production, and the manifest
    recorded a host the run never called. A YAML ``base_url`` is still a
    bring-your-own opt-out and wins here exactly as it does for completions.
    """
    if cfg.base_url == OrqAIGatewayConfig().base_url:
        base = os.environ.get("ORQ_BASE_URL", DEFAULT_ORQ_HOST).rstrip("/")
    else:
        base = cfg.base_url
    parsed = urlparse(base)
    return f"{parsed.scheme}://{parsed.netloc}"


def router_base_url(cfg: OrqAIGatewayConfig) -> str:
    """The router base a completion actually goes to, resolved like the catalog.

    Same rule as :func:`catalog_host`, kept beside it so the one-host guarantee
    has one home: at default config evaluatorq's resolver builds the client from
    ``ORQ_BASE_URL`` + ``/v3/router``, and a YAML ``base_url`` is the
    bring-your-own opt-out that wins outright. Anything checking the credential
    has to resolve the host this way or it checks a router the run never calls.
    """
    if cfg.base_url == OrqAIGatewayConfig().base_url:
        return f"{catalog_host(cfg)}/v3/router"
    return cfg.base_url


def _as_int(value: object) -> int | None:
    """The catalog sends ``created`` and ``context_window`` as numeric strings."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _price(pricing: object, side: str) -> float | None:
    """Dollars per 1M tokens for one side of a catalog ``pricing`` block.

    ``None`` for anything that cannot be stated in dollars per 1M tokens. Those
    models land in preflight's ``unpriced`` list, which names them and excludes
    them from both figures. That is the honest answer, and the alternative in
    both cases reads as good news: a guessed unit understates a price by up to
    1e6, and euros read as dollars is a number nobody measured.
    """
    if not isinstance(pricing, dict):
        return None
    leg = pricing.get(side)
    if not isinstance(leg, dict):
        return None
    cost, per = leg.get("cost"), leg.get("per")
    if not isinstance(cost, (int, float)):
        return None
    # The arena's cost path is dollars end to end (`projected_usd`). The live
    # catalog prices 48 models in EUR, 37 of them chat-capable, and reading
    # those as dollars silently understates a projection the user consents to
    # before spending. No conversion here: a rate nobody pinned is not a price.
    currency = leg.get("currency")
    if currency is not None and currency != "USD":
        return None
    # `per` is 1000000, 1000 or 1 depending on the model family, so the unit is
    # normalised from what the row states and never assumed. A row that states
    # no usable unit is unpriced rather than read as though it said 1M.
    if not isinstance(per, (int, float)) or per <= 0:
        return None
    return float(cost) * (1_000_000 / per)


def _parse_catalog(rows: list) -> dict[str, ModelEntry]:
    out: dict[str, ModelEntry] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str):
            continue
        provider = row.get("provider")
        provider_id = (
            provider.get("id") if isinstance(provider, dict) else provider
        ) or model_id.split("/", 1)[0]
        out[model_id] = ModelEntry(
            id=model_id,
            provider=str(provider_id),
            created=_as_int(row.get("created")) or 0,
            endpoints=tuple(e for e in (row.get("endpoints") or []) if isinstance(e, str)),
            deprecated=bool(row.get("deprecated")),
            context_window=_as_int(row.get("context_window")),
            price_in=_price(row.get("pricing"), "input"),
            price_out=_price(row.get("pricing"), "output"),
        )
    return out


def _write_cache(catalog: dict[str, ModelEntry]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "v": CACHE_VERSION,
                    "fetched_at": time.time(),
                    "data": [
                        {
                            "id": m.id,
                            "provider": {"id": m.provider},
                            "created": m.created,
                            "endpoints": list(m.endpoints),
                            "deprecated": m.deprecated,
                            "context_window": m.context_window,
                            "pricing": {
                                "input": {"cost": m.price_in, "per": 1_000_000},
                                "output": {"cost": m.price_out, "per": 1_000_000},
                            },
                        }
                        for m in catalog.values()
                    ],
                }
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # cache is advisory


def _read_cache() -> tuple[dict[str, ModelEntry], float] | None:
    if not CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("v") != CACHE_VERSION:
        return None  # written by an older shape; refetch rather than misread
    return _parse_catalog(raw.get("data") or []), float(raw.get("fetched_at") or 0.0)


async def _fetch_catalog(
    cfg: OrqAIGatewayConfig,
    *,
    force_refresh: bool = False,
) -> tuple[dict[str, ModelEntry], str, float]:
    """The catalog, what produced it, and when those rows were fetched.

    Only this function knows whether the network answered, so it is the only
    place that can say. Deriving the answer afterwards from "is there a cache
    file" reported a failed refresh as ``live`` and a live fetch as ``cache``.
    """
    now = time.time()
    cached = _read_cache()
    if cached is not None and not force_refresh and now - cached[1] < CACHE_TTL_SECONDS:
        return cached[0], "cache", cached[1]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{catalog_host(cfg)}/v2/model-catalog")
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        # A stale catalog beats no catalog: the run still gets prices and
        # capabilities, just older ones. It is reported as stale, because the
        # user who forced a refresh asked precisely whether this happened.
        if cached is not None:
            return cached[0], "stale", cached[1]
        return {}, "fallback", now

    rows = payload.get("data") if isinstance(payload, dict) else payload
    catalog = _parse_catalog(rows or [])
    if not catalog:
        # 200 with nothing usable in it: a schema change, an error envelope
        # served with a success code, an empty deploy. That is a failed fetch
        # wearing a success code, so it is treated as one rather than published
        # as "the catalog says there are no models", which would empty the
        # picker, blank every price, and silence preflight's warnings at once.
        if cached is not None:
            return cached[0], "stale", cached[1]
        return {}, "fallback", now
    _write_cache(catalog)
    return catalog, "live", now


async def fetch_catalog(
    cfg: OrqAIGatewayConfig,
    *,
    force_refresh: bool = False,
) -> dict[str, ModelEntry]:
    """``{router_id: ModelEntry}`` from the public catalog.

    ``{}`` only when the fetch failed and there is no cache to fall back on.

    Sends no Authorization header. The endpoint is public, and attaching a key
    would make it fail closed for exactly the users who have none.
    """
    catalog, _source, _fetched_at = await _fetch_catalog(cfg, force_refresh=force_refresh)
    return catalog


async def fetch_price_map(cfg: OrqAIGatewayConfig) -> dict[str, tuple[float, float]]:
    """``{router_id: ($/M input, $/M output)}``.

    Only models the catalog prices on both sides appear; a half-priced row is
    no more usable than an absent one, and preflight reports the difference
    between priced and unpriced rather than inventing a zero. Empty dict when
    the catalog could not be read and no cache stood in for it: pricing is
    advisory and never blocks a run.
    """
    catalog = await fetch_catalog(cfg)
    return {
        m.id: (m.price_in, m.price_out)
        for m in catalog.values()
        if m.price_in is not None and m.price_out is not None
    }


async def _workspace_enabled_ids(cfg: OrqAIGatewayConfig, api_key: str) -> set[str]:
    """Router ids this workspace has enabled; empty set when unavailable.

    An empty result means "could not narrow", not "nothing is enabled", so the
    caller keeps the full catalog rather than showing the user nothing.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{catalog_host(cfg)}/v2/router/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError):
        return set()
    rows = payload.get("data") if isinstance(payload, dict) else payload
    return {
        row["id"]
        for row in (rows or [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


async def fetch_chat_models(
    cfg: OrqAIGatewayConfig,
    *,
    force_refresh: bool = False,
) -> ModelList:
    """Chat-capable models, narrowed to the workspace's own when a key allows.

    Chat capability is read from the catalog's ``endpoints``, not inferred from
    the model id. Deprecated models are left out of the picker, because offering
    one for a new run is a recommendation; a deprecated model already named in a
    config is preflight's business, and gets flagged there rather than silently
    dropped here.
    """
    catalog, source, fetched_at = await _fetch_catalog(cfg, force_refresh=force_refresh)
    if not catalog:
        return ModelList(models=[], source=source, fetched_at=fetched_at)

    models = [m for m in catalog.values() if m.is_chat and not m.deprecated]

    api_key = os.environ.get(ORQ_API_KEY_ENV, "")
    if api_key:
        enabled = await _workspace_enabled_ids(cfg, api_key)
        if enabled:
            narrowed = [m for m in models if m.id in enabled]
            # An empty intersection is far likelier to mean the two id spaces
            # disagree than that the workspace enabled nothing at all.
            if narrowed:
                models = narrowed

    models.sort(key=lambda m: m.id)
    return ModelList(models=models, source=source, fetched_at=fetched_at)
