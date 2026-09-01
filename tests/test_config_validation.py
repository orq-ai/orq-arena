"""Preflight says what is wrong with a config before the run spends anything.

Three facts the catalog makes available, none of which anything could check
before, and none of which may block a run:

* a model the catalog does not list at all;
* a model the catalog lists as deprecated;
* a judge whose model has no `responses` endpoint. evaluatorq 1.32.4 sends
  judge calls to the router's Responses endpoint because that is the one the
  router prices, falling back to chat completions per model. The fallback works,
  so this is not an error; it silently costs judge-cost attribution, so it is
  worth saying.

Not blocking is the point. `fetch_catalog` carries deprecated entries with the flag set, so
"absent" and "unusable" are different claims, and a run whose judge aged out of
the catalog must still be runnable.
"""

from __future__ import annotations

from orq_arena.config import ArenaConfig
from orq_arena.preflight import config_warnings
from orq_arena.providers.models_list import ModelEntry


def _entry(model_id: str, *, endpoints=("chat", "responses"), deprecated=False) -> ModelEntry:
    return ModelEntry(
        id=model_id,
        provider=model_id.split("/")[0],
        endpoints=tuple(endpoints),
        deprecated=deprecated,
        price_in=1.0,
        price_out=2.0,
    )


def _cfg(candidates: list[str], judges: list[str], replacements: list[str] | None = None):
    body: dict = {
        "candidates": [{"model_id": m} for m in candidates],
        "judges": judges,
    }
    if replacements:
        body["replacement_judges"] = replacements
    return ArenaConfig.model_validate(body)


HEALTHY = {m: _entry(m) for m in ("p/cand-a", "p/cand-b", "p/judge-1", "p/judge-2", "p/spare")}


def test_a_healthy_config_says_nothing():
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"])
    assert config_warnings(cfg, HEALTHY) == []


def test_an_empty_catalog_says_nothing():
    """The catalog is unreachable, not a verdict on the config. Warning about
    every model because the network blipped would train the user to skip the
    whole section."""
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"])
    assert config_warnings(cfg, {}) == []


def test_a_model_absent_from_the_catalog_is_named():
    cfg = _cfg(["p/cand-a", "p/ghost"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, HEALTHY)
    assert "p/ghost" in warning
    assert "p/cand-a" not in warning
    # absence is a fact about the catalog, and the wording must not dress it as
    # a claim about the model: a deprecated model takes the other branch, so
    # calling this one "deprecated or unknown" was never true here.
    assert "not listed in the model catalog" in warning
    assert "deprecated" not in warning


def test_a_deprecated_model_is_named_as_deprecated_not_missing():
    catalog = HEALTHY | {"p/old": _entry("p/old", deprecated=True)}
    cfg = _cfg(["p/cand-a", "p/old"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, catalog)
    assert "p/old" in warning
    assert "deprecated" in warning
    assert "unknown" not in warning


def test_a_judge_without_the_responses_endpoint_is_flagged():
    catalog = HEALTHY | {"p/judge-2": _entry("p/judge-2", endpoints=("chat",))}
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, catalog)
    assert "p/judge-2" in warning
    assert "responses" in warning
    assert "p/judge-1" not in warning


def test_a_candidate_without_the_responses_endpoint_is_not_flagged():
    """Only judges go through evaluatorq's Responses path. A candidate is
    streamed over chat completions either way."""
    catalog = HEALTHY | {"p/cand-b": _entry("p/cand-b", endpoints=("chat",))}
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"])
    assert config_warnings(cfg, catalog) == []


def test_replacement_judges_are_checked_like_judges():
    """A stand-in gets promoted into the panel on failure, so it judges under
    exactly the same rules."""
    catalog = HEALTHY | {"p/spare": _entry("p/spare", endpoints=("chat",))}
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"], ["p/spare"])
    (warning,) = config_warnings(cfg, catalog)
    assert "p/spare" in warning
    assert "responses" in warning


def test_each_model_is_reported_once_even_when_it_is_both_absent_and_a_judge():
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/nowhere"])
    warnings = config_warnings(cfg, HEALTHY)
    assert sum(w.count("p/nowhere") for w in warnings) == 1


def test_warnings_are_stable_in_order_and_content():
    """Rendered in a run plan the user reads before paying, so it must not
    reshuffle between invocations.

    Comparing the function against itself proved nothing: it is pure, so the two
    calls agreed whatever the order was, and removing every `sorted()` left the
    suite green while the ids came back in set order. The expected string is
    written out instead, so the ordering is asserted rather than assumed.
    """
    catalog = HEALTHY | {"p/old": _entry("p/old", deprecated=True)}
    cfg = _cfg(["p/zzz", "p/old"], ["p/judge-1", "p/aaa"])

    unknown, deprecated = config_warnings(cfg, catalog)

    assert unknown.startswith("not listed in the model catalog: p/aaa, p/zzz.")
    assert deprecated.startswith("the catalog lists these as deprecated: p/old.")
