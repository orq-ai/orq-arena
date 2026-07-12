"""Click CLI entry point."""

from __future__ import annotations

import click
from loguru import logger

from .config import load_config
from .data.prompts import load_prompts
from .tui.app import ArenaApp

DEFAULT_CONFIG = "orc_arena.yaml"
DEFAULT_PROMPTS = "prompts/starter.jsonl"
DEFAULT_OUTPUT = "battles.jsonl"
DEFAULT_FIXTURE = "fixtures/demo_tournament.json"


def _quiet_logs() -> None:
    """evaluatorq logs via loguru to stderr, which would corrupt the TUI."""
    import sys

    logger.remove()
    logger.add(sys.stderr, level="ERROR")


@click.group()
def cli() -> None:
    """orc-arena — LLM arena benchmark: orq.ai router + evaluatorq jury."""


@cli.command()
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--prompts", "prompts_path", default=DEFAULT_PROMPTS, show_default=True)
@click.option("--output", "output_path", default=DEFAULT_OUTPUT, show_default=True)
def run(config_path: str, prompts_path: str, output_path: str) -> None:
    """Run the full round-robin arena live (hits orq.ai)."""
    _quiet_logs()
    cfg = load_config(config_path)
    prompts = load_prompts(prompts_path)
    app = ArenaApp(cfg=cfg, prompts=prompts, battle_log_path=output_path, live=True)
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
    click.echo(f"{'Seed':<5} {'Orc name':<26} Model ID")
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
    """Re-judge a recorded run with a different panel — zero regeneration.

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
