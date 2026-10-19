"""How each agent reaches the orq router through Harbor.

Harbor 0.24 has no base-URL flag. It reads the endpoint and key from the host
environment, keyed by the provider prefix of ``-m`` (its PROVIDERS table). The
key goes through the process environment and never an argument, so it cannot land
in ``ps`` or in the trial's recorded ``config.json``.

What was measured against the router (docs/harness-mode.md has the details):

* claude-code speaks the Anthropic wire format at ``/v3/anthropic``.
* pi speaks chat completions at ``/v3/router``; routed as an ``openai/`` model so
  any provider's model id passes through unchanged.
* codex speaks the Responses API at ``/v3/router``, which needs the full
  ``provider/model`` id, and stock Harbor strips the provider, hence ``OrqCodex``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_AGENTS = ("claude-code", "pi", "codex")
AGENT_DIR = Path(__file__).parent / "harbor_agents"

# A short, honest description of the wire format, for the run plan.
WIRE = {
    "claude-code": "anthropic messages",
    "pi": "openai chat completions",
    "codex": "openai responses",
}


@dataclass
class Route:
    harbor_agent: str  # value for -a
    model: str  # value for -m
    env: dict[str, str]  # extra process environment (holds the key)
    kwargs: dict[str, str] = field(default_factory=dict)  # --ak
    pythonpath: str | None = None  # prepended for custom agents


def model_problem(agent: str, model_id: str) -> str | None:
    """Why ``model_id`` cannot be driven by ``agent`` through the router, or None."""
    if agent not in SUPPORTED_AGENTS:
        return f"agent {agent!r} is not supported (use one of {', '.join(SUPPORTED_AGENTS)})"
    provider = model_id.split("/", 1)[0]
    if "/" not in model_id:
        return f"model_id {model_id!r} must look like 'provider/model'"
    if agent == "claude-code" and provider != "anthropic":
        return "claude-code needs an anthropic/ model (it speaks the Anthropic wire format)"
    if agent == "codex" and provider != "openai":
        return "codex needs an openai/ model (it speaks the Responses API)"
    return None


def route(agent: str, model_id: str, router_host: str, api_key: str) -> Route:
    host = router_host.rstrip("/")
    if agent == "claude-code":
        return Route(
            "claude-code",
            model_id,
            {"ANTHROPIC_BASE_URL": f"{host}/v3/anthropic", "ANTHROPIC_API_KEY": api_key},
        )
    env = {"OPENAI_BASE_URL": f"{host}/v3/router", "OPENAI_API_KEY": api_key}
    if agent == "pi":
        return Route("pi", f"openai/{model_id}", env, {"model_api": "openai-completions"})
    if agent == "codex":
        return Route("orq_codex:OrqCodex", model_id, env, pythonpath=str(AGENT_DIR))
    raise ValueError(f"agent {agent!r} is not supported")
