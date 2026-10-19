"""Pre-run checks: exact call counts, a spend projection, a thinking probe.

Counts are exact. The dollar figures are not a guarantee, and the code no
longer pretends otherwise: prices come from the router's own catalog and every
output cap is assumed fully hit, but prompt tokens are estimated from character
count, which under-counts CJK, code and dense punctuation. Two figures come
out, because one number cannot honestly answer both questions a user has:
``projected_usd`` is what a clean run costs, and ``worst_case_usd`` adds the
retry every stream may take and the replacement panel every judge may need.
The probe automates the audit that caught kimi-k2.6 burning its whole token
budget on vendor-default thinking: one tiny call per candidate, flag anything
that produces reasoning despite its config.
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from .candidates import AnyCandidate, CandidateSpec, HarnessCandidate
from .config import ArenaConfig
from .data.prompts import PromptItem, item_key
from .harness.routing import WIRE
from .providers.models_list import ModelEntry, catalog_host
from .providers.orq_gateway import OrqGateway

_PROBE_PROMPT = "Reply with the single word: ok"
# A harness round's judge input is a dossier, not a capped model answer: 8 KB of
# diff, 6 KB of key steps and a test tail, at four characters a token.
_DOSSIER_TOKENS = 4_000


def _models(cfg: ArenaConfig) -> list[CandidateSpec]:
    """The candidates that are routed models; harness candidates call no model directly."""
    return [c for c in cfg.candidates if isinstance(c, CandidateSpec)]


@dataclass(frozen=True)
class CallCounts:
    matches: int
    rounds_per_match: int
    model_streams: int
    judge_calls: int  # panel × seat orders; replacements add more on failure
    probe_calls: int


def call_counts(cfg: ArenaConfig, prompts: list[PromptItem]) -> CallCounts:
    pairs = list(combinations(cfg.candidates, 2))
    matches = len(pairs)
    rounds = min(cfg.match.max_rounds, len(prompts))
    # A harness side is a Harbor trial, not a model stream.
    sides = sum(isinstance(c, CandidateSpec) for pair in pairs for c in pair)
    return CallCounts(
        matches=matches,
        rounds_per_match=rounds,
        model_streams=sides * rounds,
        judge_calls=matches * rounds * len(cfg.judges) * seat_orders(cfg),
        probe_calls=len(_models(cfg)) if cfg.preflight.thinking_probe else 0,
    )


def seat_orders(cfg: ArenaConfig) -> int:
    """Calls per judge per round: both seat orders, or one with ``judge_swap`` off."""
    return 2 if cfg.judge_swap else 1


_PROBE_MAX_TOKENS = 1000  # headroom for coerced minimum thinking budgets
# Judge input = prompt + both responses + instruction/criteria wrapper.
_JUDGE_WRAPPER_TOKENS = 300


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class CostRow:
    """One line of the run-plan cost table; usd=None means unpriced, not $0."""

    role: str  # "candidate" | "judge" | "replacement" | "probe"
    model_id: str
    calls: int  # streams for candidates, judge calls for judges, probes for probe
    price_in: float | None  # $/M input tokens; None when absent from the catalog
    price_out: float | None
    usd: float | None


@dataclass(frozen=True)
class CostProjection:
    """What a run costs, with every output cap assumed fully hit.

    Two figures, because a single one would have to lie about something.
    ``projected_usd`` prices the calls a clean run makes. ``worst_case_usd``
    adds the failure paths that spend real money without appearing in any call
    count: the one retry each stream takes, and a replacement panel for every
    judge call, when replacements are configured. Neither is a hard bound,
    since prompt tokens are estimated from characters; see the module docstring.
    """

    projected_usd: float
    worst_case_usd: float
    models_usd: float
    judges_usd: float
    probe_usd: float
    unpriced: list[str]  # router ids absent from the catalog, excluded
    rows: tuple[CostRow, ...] = ()


def cost_projection(
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    counts: CallCounts,
    prices: dict[str, tuple[float, float]],
) -> CostProjection:
    """Price the run from exact call counts, config caps and catalog prices.

    Estimated inputs: prompt tokens (chars/4, taken at the longest prompt) and
    the judge-input term, which assumes both responses hit the model output
    cap. Retries and replacement judges never appear in a call count, so they
    are priced into ``worst_case_usd`` rather than left for the user to discover
    on the invoice.
    """
    prompt_tok = max((_est_tokens(p.text) for p in prompts), default=1)
    rounds = counts.rounds_per_match
    n = len(cfg.candidates)
    unpriced: list[str] = []
    rows: list[CostRow] = []

    models_usd = 0.0
    max_cap = 0
    for w in cfg.candidates:
        if isinstance(w, HarnessCandidate):
            max_cap = max(max_cap, _DOSSIER_TOKENS)  # what the jury reads for this side
            continue
        cap = w.max_tokens or cfg.gateway.candidate_max_tokens
        max_cap = max(max_cap, cap)
        streams = (n - 1) * rounds  # each candidate meets every other once
        if w.model_id not in prices:
            unpriced.append(w.model_id)
            rows.append(CostRow("candidate", w.model_id, streams, None, None, None))
            continue
        cin, cout = prices[w.model_id]
        usd = streams * (cin * prompt_tok + cout * cap) / 1e6
        models_usd += usd
        rows.append(CostRow("candidate", w.model_id, streams, cin, cout, usd))

    judge_in_tok = prompt_tok + 2 * max_cap + _JUDGE_WRAPPER_TOKENS
    # A decision judge returns a probability per option, not text: the Decisions
    # API bills input tokens only, whatever the model's chat output rate is.
    judge_out_tok = 0 if cfg.judge_api == "decisions" else cfg.gateway.judge_max_tokens
    judges_usd = 0.0
    calls_per_judge = counts.matches * rounds * seat_orders(cfg)
    for j in cfg.judges:
        if j not in prices:
            unpriced.append(j)
            rows.append(CostRow("judge", j, calls_per_judge, None, None, None))
            continue
        cin, cout = prices[j]
        usd = calls_per_judge * (cin * judge_in_tok + cout * judge_out_tok) / 1e6
        judges_usd += usd
        rows.append(CostRow("judge", j, calls_per_judge, cin, cout, usd))

    probe_usd = 0.0
    if counts.probe_calls:
        probe_prompt_tok = _est_tokens(_PROBE_PROMPT)
        for w in _models(cfg):
            if w.model_id not in prices:
                continue  # already recorded above
            cin, cout = prices[w.model_id]
            probe_usd += (cin * probe_prompt_tok + cout * _PROBE_MAX_TOKENS) / 1e6
        rows.append(CostRow("probe", "thinking probe", counts.probe_calls, None, None, probe_usd))

    # Stand-ins are priced at their own worst rate, not the primary panel's: a
    # cheap panel backed by an expensive replacement would otherwise slip past
    # the figure entirely.
    replacement_usd = 0.0
    if cfg.replacement_judges:
        per_call = [
            (prices[j][0] * judge_in_tok + prices[j][1] * judge_out_tok) / 1e6
            for j in cfg.replacement_judges
            if j in prices
        ]
        unpriced.extend(j for j in cfg.replacement_judges if j not in prices)
        # Every primary call failing and being stood in for is the bound.
        replacement_usd = max(per_call, default=0.0) * calls_per_judge * len(cfg.judges)
        rows.append(
            CostRow(
                "replacement",
                ", ".join(cfg.replacement_judges),
                0,  # only on failure; no call is scheduled up front
                None,
                None,
                replacement_usd or None,
            )
        )

    projected = models_usd + judges_usd + probe_usd
    # Failure paths that spend money without adding a call to any count:
    # `_generate_side` retries a dead stream once, and evaluatorq promotes a
    # stand-in for a judge call that errors outright.
    worst_case = projected + models_usd + replacement_usd
    return CostProjection(
        projected_usd=projected,
        worst_case_usd=worst_case,
        models_usd=models_usd,
        judges_usd=judges_usd,
        probe_usd=probe_usd,
        unpriced=sorted(set(unpriced)),
        rows=tuple(rows),
    )


def referenced_models(cfg: ArenaConfig) -> list[str]:
    """Every model id the config names: candidates, judges, stand-in judges.

    A harness candidate's model is an agent setting, not a router call the catalog
    can vouch for, so it is left out rather than reported as unknown.
    """
    return [
        *(w.model_id for w in _models(cfg)),
        *cfg.judges,
        *cfg.replacement_judges,
    ]


def _deprecation_date(entry: ModelEntry) -> str:
    """`` (deprecation date YYYY-MM-DD)`` for a warning line, or ``""``.

    The catalog sends Unix seconds. A value in another unit (milliseconds, say)
    is out of range for a date and raises, and an advisory line is not worth
    stopping a run before its plan prints. The date is dropped instead; the
    model is still reported as deprecated.
    """
    if not entry.deprecation:
        return ""
    try:
        day = datetime.fromtimestamp(entry.deprecation, timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return ""
    return f" (deprecation date {day})"


def config_warnings(
    cfg: ArenaConfig,
    catalog: dict[str, ModelEntry],
    unchecked: Collection[str] = frozenset(),
) -> list[str]:
    """What the catalog knows that the config should hear about, or ``[]``.

    Advisory only. Every one of these describes a run that still starts, so none
    of them blocks, and the shipped configs already name models the catalog does
    not list.

    "Not listed" and "deprecated" are separate facts, and the catalog's list
    cannot tell them apart: it never includes a deprecated model, so both are
    simply absent from it. The caller therefore passes a catalog from
    `fetch_catalog_covering`, which asks for each unlisted model by id. A
    deprecated model comes back flagged, with its date, and takes the deprecated
    branch here; one the catalog has no entry for at all stays unlisted.

    ``unchecked`` names the models whose lookup got no answer (a 503, a 429, a
    timeout). Nothing is known about those, so they are reported as not checked.
    Saying "no entry, check the id" about them would blame a correct id for the
    catalog's bad minute.

    An empty catalog means it could not be read, not that every model is
    unknown, so no per-model warning is made up from it. It is still reported, as
    one line saying the check did not run. Returning nothing made an outage look
    exactly like a clean config.
    """
    if not catalog:
        return [
            "the model catalog could not be read, so this config was not checked "
            "against it. Unlisted or deprecated models and judges without a responses "
            "endpoint would not be reported for this run."
        ]

    judges = [*cfg.judges, *cfg.replacement_judges]

    unknown: list[str] = []
    not_checked: list[str] = []
    deprecated: list[str] = []
    for model_id in dict.fromkeys(referenced_models(cfg)):
        entry = catalog.get(model_id)
        if entry is None:
            (not_checked if model_id in unchecked else unknown).append(model_id)
        elif entry.deprecated:
            deprecated.append(f"{model_id}{_deprecation_date(entry)}")

    # Only prompted judges take evaluatorq's Responses path; a candidate is
    # streamed over chat completions regardless of what else it supports, and a
    # decision judge answers on the Decisions API.
    no_responses = sorted(
        {
            j
            for j in judges
            if cfg.judge_api == "llm"
            and (e := catalog.get(j)) is not None
            and not e.has_responses
            and e.is_chat
        }
    )

    warnings: list[str] = []
    if unknown:
        warnings.append(
            f"not in the model catalog: {', '.join(sorted(unknown))}. "
            "The catalog has no entry for them, so check the id. The run still calls "
            "them; the cost projection cannot price them."
        )
    if not_checked:
        warnings.append(
            f"could not be checked against the model catalog: {', '.join(sorted(not_checked))}. "
            "They are not in its list, and the lookup that would say whether they are "
            "deprecated or unknown did not answer. This says nothing about the ids."
        )
    if deprecated:
        warnings.append(
            f"the catalog marks these as deprecated: {', '.join(sorted(deprecated))}. "
            "Pick a successor before they stop routing."
        )
    if no_responses:
        warnings.append(
            f"judges without a responses endpoint: {', '.join(no_responses)}. "
            "evaluatorq judges over the router's Responses endpoint because that is the "
            "one the router prices; these fall back to chat completions and their judge "
            "cost goes unattributed."
        )
    return warnings


def answers_on(judge_api: str, entry: ModelEntry | None) -> bool:
    """Whether a judge can answer on ``judge_api``. A model the catalog does not
    list gets the benefit of the doubt; `config_warnings` already flags it."""
    if entry is None:
        return True
    if judge_api == "decisions":
        return entry.has_decisions
    return entry.is_chat or not entry.has_decisions


def judge_api_errors(cfg: ArenaConfig, catalog: dict[str, ModelEntry]) -> list[str]:
    """Judges that cannot answer on the endpoint ``judge_api`` names. Blocking.

    Every call such a judge makes would fail, so the run would pay for every
    candidate response and then decide nothing.
    """
    wrong = [
        j
        for j in dict.fromkeys([*cfg.judges, *cfg.replacement_judges])
        if not answers_on(cfg.judge_api, catalog.get(j))
    ]
    if not wrong:
        return []
    if cfg.judge_api == "decisions":
        return [
            f"judge_api is decisions, but these judges do not serve the Decisions API: "
            f"{', '.join(wrong)}. Pick decision models (typesafe/jev-latest, "
            "orq/decider-4b, openai/gpt-6-luna), or set judge_api: llm."
        ]
    return [
        f"these judges answer only on the Decisions API: {', '.join(wrong)}. "
        "Set judge_api: decisions to seat them, or pick chat models for an llm panel."
    ]


def judge_context_warnings(
    cfg: ArenaConfig, prompts: list[PromptItem], catalog: dict[str, ModelEntry]
) -> list[str]:
    """Judges whose context window a round may overflow: prompt plus two capped responses.

    Matters most for decision models, whose windows are small (orq/decider-4b
    has 32k). Advisory: real responses rarely hit the cap.
    """
    prompt_tok = max((_est_tokens(p.text) for p in prompts), default=1)
    max_cap = max(
        (
            _DOSSIER_TOKENS
            if isinstance(w, HarnessCandidate)
            else (w.max_tokens or cfg.gateway.candidate_max_tokens)
            for w in cfg.candidates
        ),
        default=0,
    )
    need = prompt_tok + 2 * max_cap + _JUDGE_WRAPPER_TOKENS
    tight = [
        f"{j} ({e.context_window:,})"
        for j in dict.fromkeys([*cfg.judges, *cfg.replacement_judges])
        if (e := catalog.get(j)) is not None and e.context_window and e.context_window < need
    ]
    if not tight:
        return []
    return [
        f"a round can reach ~{need:,} judge input tokens (longest prompt plus two responses "
        f"at their cap), over these judges' context windows: {', '.join(tight)}. "
        "A round that overflows fails for that judge; lower candidate max_tokens to be safe."
    ]


async def _probe_one(gateway: OrqGateway, w: CandidateSpec) -> tuple[str, dict[str, Any]]:
    usage: dict[str, Any] = {}
    think_chunks = 0
    try:
        async for kind, _piece in gateway.stream_completion(
            model=w.model_id,
            prompt=_PROBE_PROMPT,
            max_tokens=_PROBE_MAX_TOKENS,
            extra_body=w.reasoning,
            usage_out=usage,
        ):
            if kind == "think":
                think_chunks += 1
        reasoning_tokens = usage.get("reasoning_tokens", 0)
        # The router under-reports reasoning_tokens on some providers
        # (Anthropic returns 0 while thinking), visible CoT chunks count too.
        thinks = reasoning_tokens > 0 or think_chunks > 0
        return w.name, {
            "model": w.model_id,
            "reasoning_tokens": reasoning_tokens,
            "cot_chunks": think_chunks,
            "thinks": thinks,
            "configured": w.thinking_enabled,
            "error": None,
        }
    except Exception as exc:
        return w.name, {
            "model": w.model_id,
            "reasoning_tokens": 0,
            "cot_chunks": 0,
            "thinks": False,
            "configured": w.thinking_enabled,
            "error": str(exc)[:200],
        }


async def thinking_probe(cfg: ArenaConfig) -> dict[str, dict[str, Any]]:
    """One tiny call per candidate; returns {name: probe result}."""
    gateway = OrqGateway(cfg.gateway)
    results = await asyncio.gather(*(_probe_one(gateway, w) for w in _models(cfg)))
    return dict(results)


def surprises(probe: dict[str, dict[str, Any]]) -> list[str]:
    """Candidates whose observed thinking contradicts their config."""
    return [
        name
        for name, r in probe.items()
        if r["error"] is None and r["thinks"] and not r["configured"]
    ]


def judge_family_overlaps(judges: list[str], candidates: Sequence[AnyCandidate]) -> list[str]:
    """Judges sharing a provider family with a contestant.

    Self-preference bias rides on stylistic self-recognition (Panickssery et
    al., NeurIPS 2024): a judge favors its own family's prose, and neither
    blinding nor seat-swapping corrects it. Exact self-judging is already
    excluded per match; this flags the family-level residue so the ranking
    ships with a warning instead of a hidden thumb on the scale.
    """

    # ponytail: provider prefix as family proxy; per-provider lineage tables
    # if one provider ever hosts unrelated model families
    def fam(model_id: str) -> str:
        return model_id.split("/", 1)[0].lower()

    candidate_fams = {fam(c.model_id) for c in candidates}
    return [j for j in judges if fam(j) in candidate_fams]


# ----- harness mode ----------------------------------------------------------

_COST_NOTE = (
    "agent spend is not projected; capped per trial by agent_kwargs (max_budget_usd, max_turns)"
)
_DEFAULT_AGENT_TIMEOUT_S = 900
_UNRESOLVED_VAR = re.compile(r"\$(\w+|\{[^}]*\})")
_DRY_RUN_UNSUPPORTED = ("no such option", "unrecognized", "unknown option", "unexpected extra")


def _run_cmd(argv: list[str], timeout: float = 30.0) -> tuple[int, str]:
    """Run a command, return ``(exit code, stdout + stderr)``; 127 when it cannot start.

    The single place preflight shells out, so tests replace it and never touch Docker.
    """
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


@dataclass(frozen=True)
class _HarnessProbe:
    problems: list[str]  # blocking
    lines: list[str]  # for the run plan: "✓ ...", "⚠ ...", "✗ ..."


_last_probe: tuple[Any, _HarnessProbe] | None = None


def _harnesses(cfg: ArenaConfig) -> list[HarnessCandidate]:
    return [c for c in cfg.candidates if isinstance(c, HarnessCandidate)]


def _task_path(item: PromptItem) -> str:
    return str(item.metadata.get("harbor_task_path") or "")


def _dry_run(
    cfg: ArenaConfig, exe: str, candidate: HarnessCandidate, item: PromptItem
) -> tuple[bool, str]:
    """``(ok, note)`` for one ``harbor run --dry-run``, built from the real argv."""
    from .harness.runner import HarborRunner, HarnessError

    with tempfile.TemporaryDirectory(prefix="orq-arena-dry-") as tmp:
        runner = HarborRunner(
            cfg.harness,
            Path(tmp),
            router_host=cfg.harness.router_host or catalog_host(cfg.gateway),
            keep_awake=False,
        )
        try:
            argv, env = runner._plan(item, candidate, "dry-run")
        except HarnessError as exc:
            return False, str(exc)
        argv[0] = exe
        # A custom agent (codex) is imported from PYTHONPATH; _run_cmd has no env of its own.
        if env.get("PYTHONPATH") != os.environ.get("PYTHONPATH"):
            argv = ["env", f"PYTHONPATH={env['PYTHONPATH']}", *argv]
        code, out = _run_cmd([*argv, "--dry-run"], timeout=60.0)
    tail = out.strip().splitlines()[-1] if out.strip() else ""
    if code == 0:
        return True, ""
    if any(marker in out.lower() for marker in _DRY_RUN_UNSUPPORTED):
        return False, "this harbor has no --dry-run"
    return False, f"exit {code}: {tail[:160]}"


def _existing_tasks(prompts: list[PromptItem]) -> set[str]:
    return {t for p in prompts if (t := _task_path(p)) and Path(t).expanduser().exists()}


def _probe_harness(cfg: ArenaConfig, prompts: list[PromptItem]) -> _HarnessProbe:
    problems: list[str] = []
    lines: list[str] = []
    h = cfg.harness

    def block(msg: str) -> None:
        problems.append(msg)
        lines.append(f"✗ {msg}")

    exe = shutil.which(h.harbor_bin)
    if exe is None:
        block(
            f"{h.harbor_bin!r} is not on PATH. Install Harbor with "
            "`uv tool install --python 3.13 harbor`, or set harness.harbor_bin."
        )
    else:
        code, out = _run_cmd([exe, "--version"])
        version = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if code != 0:
            block(f"`{h.harbor_bin} --version` failed (exit {code}): {version[:160]}")
        elif version.lower().startswith("harbor"):
            lines.append(f"✓ {version}")
        else:
            lines.append(f"✓ harbor {version}")

    code, _out = _run_cmd(["docker", "info"])
    if code != 0:
        block("the Docker daemon is not reachable (`docker info` failed). Start Docker Desktop.")
    else:
        lines.append("✓ docker")

    if os.environ.get(h.api_key_name):
        lines.append(f"✓ {h.api_key_name}")
    else:
        block(
            f"{h.api_key_name} is not set. Harbor passes it to every agent as the router key "
            "(harness.api_key_name names the variable)."
        )

    harnesses = _harnesses(cfg)
    for c in harnesses:
        for path in c.overlay.paths() if c.overlay else []:
            if not Path(path).expanduser().exists():
                block(f"{c.name}: overlay path does not exist: {path}")
        for key, value in c.agent_env.items():
            if _UNRESOLVED_VAR.search(os.path.expandvars(value)):
                block(
                    f"{c.name}: agent_env {key} is {value!r}, which refers to an environment "
                    "variable that is not set."
                )

    no_path = [p for p in prompts if not _task_path(p)]
    if no_path:
        block(
            f"{len(no_path)} of {len(prompts)} prompt rows have no harbor_task_path metadata; "
            "build the prompt file with `orq-arena tasks sample`."
        )
    gone = sorted({_task_path(p) for p in prompts if _task_path(p)} - _existing_tasks(prompts))
    if gone:
        shown = ", ".join(gone[:3]) + (f" and {len(gone) - 3} more" if len(gone) > 3 else "")
        block(f"task directories not found: {shown}")
    tasks_ok = bool(prompts) and not no_path and not gone
    if tasks_ok:
        lines.append(f"✓ {len(prompts)} task directories")

    if exe is not None and tasks_ok:
        first_of_agent: dict[str, HarnessCandidate] = {}
        for c in harnesses:
            first_of_agent.setdefault(c.agent, c)
        for agent, c in first_of_agent.items():
            ok, note = _dry_run(cfg, exe, c, prompts[0])
            lines.append(
                f"✓ harbor dry run: {agent}"
                if ok
                else f"⚠ harbor dry run for {agent} did not pass ({note}); not blocking"
            )

    if platform.machine().lower() in ("arm64", "aarch64"):
        lines.append("⚠ images are linux/amd64, running under emulation")
    return _HarnessProbe(problems, lines)


def _probe_key(cfg: ArenaConfig, prompts: list[PromptItem]) -> Any:
    # The helpers are in the key so a test that swaps them never reads a stale probe.
    return (
        cfg.model_dump_json(),
        tuple(_task_path(p) for p in prompts),
        _run_cmd,
        shutil.which,
        bool(os.environ.get(cfg.harness.api_key_name)),
    )


def harness_checks(cfg: ArenaConfig, prompts: list[PromptItem]) -> list[str]:
    """Problems that stop a harness run before it spends anything; ``[]`` means go.

    Harbor and Docker must be reachable, the router key set, every overlay path and
    task directory present, and every ``agent_env`` value resolvable. A
    ``harbor run --dry-run`` per distinct agent is advisory: a Harbor that lacks the
    flag, or a dry run that fails for some other reason, is reported in the run
    plan but does not block.
    """
    global _last_probe
    probe = _probe_harness(cfg, prompts)
    # `harness_plan` runs right after and shows the same lines; do not repeat the dry runs.
    _last_probe = (_probe_key(cfg, prompts), probe)
    return list(probe.problems)


def _missing_images(prompts: list[PromptItem]) -> tuple[list[str], int, bool]:
    """``(images not present locally, distinct images, whether Docker answered)``."""
    images = list(dict.fromkeys(str(i) for p in prompts if (i := p.metadata.get("image"))))
    if _run_cmd(["docker", "info"])[0] != 0:
        return [], len(images), False
    missing = [img for img in images if _run_cmd(["docker", "image", "inspect", img])[0] != 0]
    return missing, len(images), True


def harness_plan(
    cfg: ArenaConfig,
    prompts: list[PromptItem],
    trials_dir: str | Path | None = None,
) -> dict[str, Any]:
    """The run plan for a harness pool: what will run, what is cached, what it may cost.

    ``trials`` is an upper bound (``harnesses x tasks``): a tie never counts toward a
    match's round cap, so a smaller ``--rounds`` can still draw extra tasks.
    ``wall_estimate_s`` is the worst case, every uncached trial running to its
    timeout (scaled by the timeout multiplier) on ``max_parallel_trials`` lanes.
    Nothing here touches the network.
    """
    from .harness.runner import cached_trial_dir, job_name

    harnesses = _harnesses(cfg)
    where = trials_dir or cfg.harness.trials_dir
    root = Path(where) if where else None

    def timeout_s(item: PromptItem) -> int:
        return int(item.metadata.get("timeout_sec") or _DEFAULT_AGENT_TIMEOUT_S)

    cached = 0
    uncached_s = 0.0
    for c in harnesses:
        mult = c.timeout_multiplier or cfg.harness.timeout_multiplier
        for item in prompts:
            if root is not None and cached_trial_dir(
                root, job_name(item_key(item), c.candidate_id)
            ):
                cached += 1
            else:
                uncached_s += timeout_s(item) * mult

    names: list[str] = []
    for item in prompts:
        name = str(item.metadata.get("task_name") or Path(_task_path(item)).name or "")
        if name and name not in names:
            names.append(name)

    missing, n_images, docker_up = _missing_images(prompts)

    probe = _last_probe[1] if _last_probe and _last_probe[0] == _probe_key(cfg, prompts) else None
    checks = list((probe or _probe_harness(cfg, prompts)).lines)
    if n_images and docker_up:
        have = n_images - len(missing)
        checks.append(
            f"✓ {have}/{n_images} images"
            if not missing
            else f"⚠ {have}/{n_images} images present; harbor pulls the rest on first use"
        )

    def overlay_label(c: HarnessCandidate) -> str:
        summary = c.overlay_summary()
        return summary if summary == "vanilla" or not c.variant else f"{summary} #{c.variant}"

    return {
        "plan": {
            "trials": len(harnesses) * len(prompts),
            "cached": cached,
            "matches": len(list(combinations(cfg.candidates, 2))),
            "tasks_per_match": min(cfg.match.max_rounds, len(prompts)),
            "task_names": names,
            "difficulty_mix": dict(
                Counter(str(p.metadata.get("difficulty") or "unknown") for p in prompts)
            ),
            "images_missing": missing,
            "agent_timeouts_s": sum(timeout_s(p) for p in prompts) * len(harnesses),
            "wall_estimate_s": int(uncached_s / max(1, cfg.harness.max_parallel_trials)),
            "cost_note": _COST_NOTE,
            "harnesses": [
                {
                    "name": c.name,
                    "agent": c.agent,
                    "model": c.model_id,
                    "overlay": overlay_label(c),
                    "api_format": WIRE[c.agent],
                }
                for c in harnesses
            ],
        },
        "checks": checks,
    }
