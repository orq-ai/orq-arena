"""Preflight says what is wrong with a config before the run spends anything.

Three facts the catalog makes available, none of which anything could check
before, and none of which may block a run:

* a model the catalog has no entry for at all;
* a model the catalog marks as deprecated;
* a judge whose model has no `responses` endpoint. evaluatorq sends
  judge calls to the router's Responses endpoint because that is the one the
  router prices, falling back to chat completions per model. The fallback works,
  so this is not an error; it silently costs judge-cost attribution, so it is
  worth saying.

Not blocking is the point: a run whose judge aged out of the catalog must still
be runnable. The catalog's list never includes a deprecated model, so the dict
these tests pass stands for what `fetch_catalog_covering` returns, where each
unlisted model has been asked for by id and a deprecated one carries its flag.
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


def test_an_unreadable_catalog_says_the_check_did_not_run():
    """Silence here read as "your config is clean".

    An empty catalog is an outage, not a verdict, so no per-model warning is
    invented from it: naming every model because the network blipped would
    train the reader to skip the section. But returning nothing made the outage
    indistinguishable from a healthy config, so it says one thing, once.
    """
    cfg = _cfg(["p/cand-a", "p/cand-b"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, {})
    assert "could not be read" in warning
    assert "not checked" in warning
    assert "p/cand-a" not in warning


def test_a_model_absent_from_the_catalog_is_named():
    cfg = _cfg(["p/cand-a", "p/ghost"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, HEALTHY)
    assert "p/ghost" in warning
    assert "p/cand-a" not in warning
    # absence is a fact about the catalog, and the wording must not dress it as
    # a claim about the model: a deprecated model takes the other branch, so
    # calling this one "deprecated or unknown" was never true here.
    assert "not in the model catalog" in warning
    assert "deprecated" not in warning


def test_a_deprecated_model_is_named_as_deprecated_not_missing():
    catalog = HEALTHY | {"p/old": _entry("p/old", deprecated=True)}
    cfg = _cfg(["p/cand-a", "p/old"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, catalog)
    assert "p/old" in warning
    assert "deprecated" in warning


def test_a_deprecated_model_carries_the_date_the_catalog_gives():
    """The date is what turns "deprecated" into something to act on."""
    old = _entry("p/old", deprecated=True)
    old.deprecation = 1792454400  # 2026-10-20T00:00:00Z, as the catalog sends it
    cfg = _cfg(["p/cand-a", "p/old"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, HEALTHY | {"p/old": old})
    assert "p/old (deprecation date 2026-10-20)" in warning
    assert "unknown" not in warning


def test_a_deprecation_value_that_is_not_a_date_does_not_stop_the_run():
    """An advisory line must not be able to crash the preflight.

    The catalog sends Unix seconds. The same instant in milliseconds is out of
    range for a date and raised, before the run plan had printed. The model is
    still reported as deprecated; only the date is dropped.
    """
    old = _entry("p/old", deprecated=True)
    old.deprecation = 1792454400 * 1_000_000
    cfg = _cfg(["p/cand-a", "p/old"], ["p/judge-1", "p/judge-2"])
    (warning,) = config_warnings(cfg, HEALTHY | {"p/old": old})
    assert "p/old" in warning
    assert "deprecated" in warning
    assert "deprecation date" not in warning


def test_a_model_whose_lookup_got_no_answer_is_not_told_to_check_its_id():
    """ "Could not be checked" and "not in the catalog" are different claims.

    When the by-id lookup fails, nothing is known about the model. It used to
    land in the same line as a misspelt id, which told the user their correct
    id was wrong whenever the catalog had a bad minute.
    """
    cfg = _cfg(["p/cand-a", "p/ghost", "p/flaky"], ["p/judge-1", "p/judge-2"])
    missing, not_checked = config_warnings(cfg, HEALTHY, unchecked={"p/flaky"})

    assert missing.startswith("not in the model catalog: p/ghost.")
    assert "p/flaky" not in missing
    assert not_checked.startswith("could not be checked against the model catalog: p/flaky.")
    assert "check the id" not in not_checked


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

    assert unknown.startswith("not in the model catalog: p/aaa, p/zzz.")
    assert deprecated.startswith("the catalog marks these as deprecated: p/old.")
