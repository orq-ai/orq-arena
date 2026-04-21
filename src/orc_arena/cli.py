"""Click CLI entry point."""

from __future__ import annotations

import click

from .config import load_config
from .data.prompts import load_prompts
from .tui.app import ArenaApp

DEFAULT_CONFIG = "orc_arena.yaml"
DEFAULT_PROMPTS = "prompts/starter.jsonl"
DEFAULT_OUTPUT = "battles.jsonl"
DEFAULT_FIXTURE = "fixtures/demo_tournament.json"


@click.group()
def cli() -> None:
    """orc-arena — LLM tournament routed via orq.ai."""


@cli.command()
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--prompts", "prompts_path", default=DEFAULT_PROMPTS, show_default=True)
@click.option("--output", "output_path", default=DEFAULT_OUTPUT, show_default=True)
def run(config_path: str, prompts_path: str, output_path: str) -> None:
    """Run the full 8-warrior tournament live (hits orq.ai)."""
    cfg = load_config(config_path)
    prompts = load_prompts(prompts_path)
    app = ArenaApp(cfg=cfg, prompts=prompts, battle_log_path=output_path, live=True)
    app.run()


@cli.command()
@click.option("--fixture", "fixture_path", default=DEFAULT_FIXTURE, show_default=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
def demo(fixture_path: str, config_path: str) -> None:
    """Replay a recorded tournament from a fixture file (no API calls)."""
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
