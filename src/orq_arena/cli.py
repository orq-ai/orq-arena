"""Click CLI entry point."""

from __future__ import annotations

import click
from loguru import logger

from .config import load_config
from .data.prompts import load_prompts
from .tui.app import ArenaApp

DEFAULT_CONFIG = "orq_arena.yaml"
DEFAULT_PROMPTS = "prompts/starter.jsonl"
DEFAULT_OUTPUT = "battles.jsonl"
DEFAULT_FIXTURE = "fixtures/demo_tournament.json"


def _quiet_logs() -> None:
    """evaluatorq logs via loguru to stderr, which would corrupt the TUI."""
    import sys

    logger.remove()
    logger.add(sys.stderr, level="ERROR")


def _load_dotenv() -> None:
    """Read KEY=VALUE lines from ./.env into the env (never overriding it)."""
    import os
    from pathlib import Path

    env = Path(".env")
    if not env.is_file():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@click.group()
def cli() -> None:
    """orq-arena, LLM arena benchmark: orq.ai router + evaluatorq jury."""
    _load_dotenv()


@cli.command()
@click.option("--config", "config_path", default=None, show_default=False,
              help="Use this YAML roster as-is and skip the interactive picker.")
@click.option("--prompts", "prompts_path", default=DEFAULT_PROMPTS, show_default=True,
              help="JSONL file, or orq:<dataset_id> to pull an orq.ai Dataset.")
@click.option("--output", "output_path", default=DEFAULT_OUTPUT, show_default=True)
@click.option("--headless", is_flag=True, default=False,
              help="No TUI; matches run in parallel (headless_concurrency). Requires --config.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, default=False,
              help="Skip the preflight confirmation pause.")
def run(config_path: str | None, prompts_path: str, output_path: str,
        headless: bool, assume_yes: bool) -> None:
    """Run the full round-robin arena live (hits orq.ai).

    Without --config the roster picker opens first: choose any >=2 models
    from your workspace-enabled catalog. The YAML still supplies judges,
    rules, and gateway settings.
    """
    import asyncio

    from .preflight import (call_counts, judge_family_overlaps, surprises,
                            thinking_probe)

    _quiet_logs()
    pick_roster = config_path is None
    cfg = load_config(config_path or DEFAULT_CONFIG)
    prompts = load_prompts(prompts_path, api_key_env=cfg.gateway.api_key_env)

    if pick_roster:
        if headless:
            raise click.ClickException("--headless needs --config (no picker without a TUI)")
        # Preflight (probe + counts) runs in-app after the roster is picked.
        app = ArenaApp(
            cfg=cfg, prompts=prompts, battle_log_path=output_path, live=True,
            pick_roster=True,
        )
        app.run()
        return

    counts = call_counts(cfg, prompts)
    click.echo(
        f"preflight: {counts.matches} matches × {counts.rounds_per_match} rounds → "
        f"{counts.warrior_streams} warrior streams + {counts.judge_calls} judge calls"
        + (f" + {counts.probe_calls} probe calls" if counts.probe_calls else "")
    )
    overlap = judge_family_overlaps(list(cfg.judges), cfg.warriors)
    if overlap:
        click.echo(
            f"  ⚖ judge/contestant family overlap: {', '.join(overlap)}. "
            "Self-preference bias is not corrected by seat swapping; "
            "prefer judges from families outside the pool."
        )

    preflight_data: dict = {"counts": counts.__dict__}
    if cfg.preflight.thinking_probe:
        click.echo("thinking probe…")
        probe = asyncio.run(thinking_probe(cfg))
        preflight_data["thinking_probe"] = probe
        for name, r in probe.items():
            if r["error"]:
                click.echo(f"  ⚠ {name} ({r['model']}): probe failed, {r['error']}")
            elif r["thinks"] and not r["configured"]:
                click.echo(
                    f"  🧠 {name} ({r['model']}): thinks despite config "
                    f"({r['reasoning_tokens']} reasoning tok), ranking will be footnoted"
                )
        odd = surprises(probe)
        if not odd:
            click.echo("  pool is thinking-clean ✓")

    if not assume_yes:
        click.confirm("Proceed?", abort=True)

    if headless:
        from .headless import run_headless

        asyncio.run(run_headless(
            cfg=cfg, prompts=prompts, battle_log_path=output_path,
            preflight=preflight_data,
        ))
        return

    app = ArenaApp(
        cfg=cfg, prompts=prompts, battle_log_path=output_path, live=True,
        preflight=preflight_data,
    )
    app.run()


@cli.command()
@click.option("--fixture", "fixture_path", default=DEFAULT_FIXTURE, show_default=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
def demo(fixture_path: str, config_path: str) -> None:
    """Replay a recorded tournament from a fixture file (no API calls)."""
    _quiet_logs()
    cfg = load_config(config_path)
    app = ArenaApp(cfg=cfg, prompts=[], battle_log_path="", live=False, fixture=fixture_path)
    app.run()


@cli.command("list-warriors")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
def list_warriors(config_path: str) -> None:
    """Print the warrior roster."""
    cfg = load_config(config_path)
    click.echo(f"{'Seed':<5} {'Name':<26} Model ID")
    click.echo("-" * 70)
    for i, w in enumerate(cfg.warriors, 1):
        click.echo(f"{i:<5} {w.orc_name:<26} {w.model_id}")


if __name__ == "__main__":
    cli()


@cli.command()
@click.argument("log_path", default=DEFAULT_OUTPUT)
@click.option("--judge", "judges", multiple=True, required=True,
              help="Router model id; repeat for a panel.")
@click.option("--criteria", default=None, help="Override judging criteria.")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--output", "output_path", default=None,
              help="Write re-judged rounds to this JSONL.")
@click.option("--report-json", default=None, help="Write the summary as JSON.")
@click.option("--concurrency", default=4, show_default=True)
def rejudge(log_path: str, judges: tuple[str, ...], criteria: str | None,
            config_path: str, output_path: str | None, report_json: str | None,
            concurrency: int) -> None:
    """Re-judge a recorded run with a different panel, zero regeneration.

    The evaluatorq demo inside the demo: the responses are already on disk,
    so swapping the jury costs judge tokens only. Prints the new jury's
    behaviour and the Spearman correlation against the recorded ranking.
    """
    import asyncio

    from .rejudge import (load_records, rejudge_run, render_result,
                          save_report_json, write_rejudged)

    _quiet_logs()
    cfg = load_config(config_path)
    records = load_records(log_path)
    if not records:
        raise click.ClickException(f"no judgeable rounds in {log_path}")
    click.echo(f"re-judging {len(records)} rounds with panel: {', '.join(judges)}")
    result = asyncio.run(rejudge_run(
        cfg=cfg, records=records, judges=list(judges),
        criteria=criteria, concurrency=concurrency,
    ))
    render_result(result)
    if output_path:
        write_rejudged(output_path, records, result["comparisons"])
        click.echo(f"re-judged rounds -> {output_path}")
    if report_json:
        save_report_json(report_json, result)
        click.echo(f"summary -> {report_json}")


@cli.command("jury-compare")
@click.argument("report_jsons", nargs=-1, required=True)
def jury_compare(report_jsons: tuple[str, ...]) -> None:
    """Compare candidate juries from saved rejudge reports, side by side.

    The jury-selection loop: run once, then `rejudge <log> --judge ...
    --report-json candidate.json` per candidate panel (judge tokens only),
    then compare the candidates here. No API calls.
    """
    from .rejudge import compare_reports, render_comparison

    render_comparison(compare_reports(list(report_jsons)))


@cli.command("report")
@click.argument("log_path", default=DEFAULT_OUTPUT)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--output", "output_path", default=None,
              help="Destination HTML (default: <log>.report.html next to the log).")
def report_cmd(log_path: str, config_path: str, output_path: str | None) -> None:
    """Render the single-file HTML report page from a recorded run.

    Reads battles.jsonl and its *.run.json manifest; makes no API calls.
    The same page is written automatically at the end of every run.
    """
    import json as _json
    from pathlib import Path

    from .data.schemas import BattleRecord
    from .report import build_report_html, report_path_for
    from .tournament.driver import Outcome, _final_report, _triples
    from .tournament.elo import bradley_terry_mle, build_wins_matrix

    cfg = load_config(config_path)
    log = Path(log_path)
    if not log.exists():
        raise click.ClickException(f"{log_path} not found")
    records = [
        BattleRecord.model_validate_json(line)
        for line in log.read_text().splitlines() if line.strip()
    ]
    if not records:
        raise click.ClickException(f"no rounds in {log_path}")
    manifest_path = log.with_suffix(".run.json")
    manifest = _json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    names = sorted({m for r in records for m in (r.model_a, r.model_b)})
    outcomes: list[Outcome] = []
    for r in records:
        if r.error is not None:
            continue
        cat = r.prompt_category or "general"
        if r.majority_verdict == "A":
            outcomes.append((r.model_a, r.model_b, "winner", cat))
        elif r.majority_verdict == "B":
            outcomes.append((r.model_b, r.model_a, "winner", cat))
        elif r.majority_verdict == "tie":
            outcomes.append((r.model_a, r.model_b, "tie", cat))
    elo = bradley_terry_mle(build_wins_matrix(_triples(outcomes)), names)
    rep = _final_report(cfg, records, outcomes, names, preflight=manifest.get("preflight"))

    out = Path(output_path) if output_path else report_path_for(log)
    out.write_text(build_report_html(
        cfg=cfg, records=records, elo=elo, report=rep, manifest=manifest,
    ))
    click.echo(f"report page -> {out}")


@cli.command("refresh-models")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--show/--no-show", default=False, help="Print model ids grouped by provider.")
def refresh_models(config_path: str, show: bool) -> None:
    """Re-fetch the workspace-enabled chat model list from orq.ai.

    Bypasses the 24h cache at ~/.cache/orq-arena/models.json.
    """
    import asyncio
    import time as _time

    from .providers.models_list import CACHE_FILE, fetch_chat_models

    cfg = load_config(config_path)
    ml = asyncio.run(fetch_chat_models(cfg.gateway, force_refresh=True))
    age = _time.time() - ml.fetched_at
    click.echo(f"{len(ml.models)} models (source={ml.source}, age={age:.0f}s, cache={CACHE_FILE})")
    if not show:
        return
    by_provider: dict[str, list[str]] = {}
    for m in ml.models:
        by_provider.setdefault(m.provider, []).append(m.id)
    for provider in sorted(by_provider):
        click.echo(f"\n{provider}  ({len(by_provider[provider])})")
        for mid in sorted(by_provider[provider]):
            click.echo(f"  {mid}")
