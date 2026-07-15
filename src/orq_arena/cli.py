"""Click CLI entry point."""

from __future__ import annotations

import click
from loguru import logger

from .config import load_config
from .data.prompts import load_prompts

DEFAULT_CONFIG = "orq_arena.yaml"
DEFAULT_PROMPTS = "prompts/starter.jsonl"
DEFAULT_OUTPUT = "battles.jsonl"
DEFAULT_FIXTURE = "fixtures/demo_tournament.json"


def _arena_app_cls(hint: str):
    """Import ArenaApp lazily so the core CLI runs without the [tui] extra.

    A missing textual becomes a friendly install hint; a real bug inside
    orq_arena.tui still tracebacks.
    """
    try:
        from .tui.app import ArenaApp
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] == "textual":
            raise click.ClickException(hint) from exc
        raise
    return ArenaApp


_PICKER_HINT = (
    "The interactive roster picker needs the TUI. Install it with: "
    "pip install 'orq-arena[tui]' (or uv sync --extra tui), or pass "
    "--config <yaml> to run headless with a fixed roster."
)
_TUI_HINT = (
    "The live TUI show needs the extra. Install it with: "
    "pip install 'orq-arena[tui]' (or uv sync --extra tui), or drop --tui "
    "to run headless."
)
_DEMO_HINT = (
    "orq-arena demo replays inside the TUI. Install it with: "
    "pip install 'orq-arena[tui]' (or uv sync --extra tui)."
)


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
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@click.group()
def cli() -> None:
    """orq-arena, LLM arena benchmark: orq.ai router + evaluatorq jury."""
    _load_dotenv()


@cli.command()
@click.option(
    "--config",
    "config_path",
    default=None,
    show_default=False,
    help="Use this YAML roster as-is and skip the interactive picker.",
)
@click.option(
    "--prompts",
    "prompts_path",
    default=DEFAULT_PROMPTS,
    show_default=True,
    help="JSONL file, or orq:<dataset_id> to pull an orq.ai Dataset.",
)
@click.option("--output", "output_path", default=DEFAULT_OUTPUT, show_default=True)
@click.option(
    "--rounds",
    "rounds",
    type=int,
    default=None,
    help="Rounds per match (overrides match.max_rounds). Use len(prompts) to see every prompt.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Allow replacing an existing non-empty battle log at --output.",
)
@click.option(
    "--tui",
    "tui",
    is_flag=True,
    default=False,
    help="Watch the live TUI show instead of the default headless logs.",
)
@click.option(
    "--headless",
    is_flag=True,
    default=False,
    help="Deprecated: headless is already the default with --config.",
)
@click.option(
    "--no-open",
    "no_open",
    is_flag=True,
    default=False,
    help="Do not open the HTML report in a browser when the run ends.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the preflight confirmation pause.",
)
def run(
    config_path: str | None,
    prompts_path: str,
    output_path: str,
    rounds: int | None,
    overwrite: bool,
    tui: bool,
    headless: bool,
    no_open: bool,
    assume_yes: bool,
) -> None:
    """Run the arena benchmark (hits orq.ai): headless logs by default,
    then the HTML report opens in your browser.

    With --config the run is headless (matches in parallel); pass --tui to
    watch the live show instead. Without --config the interactive roster
    picker opens first, which needs the TUI. The YAML still supplies
    judges, rules, and gateway settings.
    """
    import asyncio
    from pathlib import Path

    from .preflight import (
        call_counts,
        cost_ceiling,
        judge_family_overlaps,
        surprises,
        thinking_probe,
    )
    from .providers.models_list import fetch_price_map

    _quiet_logs()
    out = Path(output_path)
    if out.exists() and out.stat().st_size > 0 and not overwrite:
        raise click.ClickException(
            f"{output_path} already holds a recorded run; a new run would erase it. "
            "Pass a fresh --output, or --overwrite to replace it."
        )
    pick_roster = config_path is None
    # Fail fast on a missing TUI extra before any preflight work.
    arena_app_cls = (
        _arena_app_cls(_PICKER_HINT if pick_roster else _TUI_HINT) if (pick_roster or tui) else None
    )
    cfg = load_config(config_path or DEFAULT_CONFIG)
    prompts = load_prompts(prompts_path, api_key_env=cfg.gateway.api_key_env)
    if rounds is not None:
        if rounds < 1:
            raise click.ClickException("--rounds must be >= 1")
        cfg.match.max_rounds = rounds
    if cfg.match.max_rounds < len(prompts):
        click.echo(
            f"  ⚠ each match samples {cfg.match.max_rounds} of your {len(prompts)} prompts "
            f"(a seeded random slice per match). Pass --rounds {len(prompts)} to use every "
            "prompt each match, or raise match.max_rounds in the YAML."
        )
    dataset = None
    if prompts_path.startswith("orq:"):
        from .data.prompts import orq_dataset_meta

        dataset = orq_dataset_meta(prompts_path[len("orq:") :], api_key_env=cfg.gateway.api_key_env)

    if tui and headless:
        raise click.ClickException("--tui and --headless contradict each other")
    if pick_roster:
        # The picker is a TUI screen, so this path always runs the live show.
        app = arena_app_cls(
            cfg=cfg,
            prompts=prompts,
            battle_log_path=output_path,
            live=True,
            pick_roster=True,
            dataset=dataset,
        )
        app.run()
        _open_report(output_path, no_open)
        return

    counts = call_counts(cfg, prompts)
    click.echo(
        f"preflight: {counts.matches} matches × {counts.rounds_per_match} rounds → "
        f"{counts.model_streams} model streams + {counts.judge_calls} judge calls"
        + (f" + {counts.probe_calls} probe calls" if counts.probe_calls else "")
    )
    overlap = judge_family_overlaps(list(cfg.judges), cfg.candidates)
    if overlap:
        click.echo(
            f"  ⚖ judge/contestant family overlap: {', '.join(overlap)}. "
            "Self-preference bias is not corrected by seat swapping; "
            "prefer judges from families outside the pool."
        )

    # Persist the caveat so the manifest and forwarded report carry it, not
    # just this console line (the report is the thing users hand to others).
    preflight_data: dict = {"counts": counts.__dict__, "family_overlaps": overlap}
    ceiling = cost_ceiling(cfg, prompts, counts, asyncio.run(fetch_price_map(cfg.gateway)))
    if ceiling.total_usd > 0:
        click.echo(
            f"  spend ceiling ≈ ${ceiling.total_usd:.2f} "
            f"(models ${ceiling.models_usd:.2f} + judges ${ceiling.judges_usd:.2f}"
            + (f" + probe ${ceiling.probe_usd:.2f}" if ceiling.probe_usd else "")
            + "; every output cap fully hit, live runs land under)"
        )
        preflight_data["cost_ceiling"] = ceiling.__dict__
    if ceiling.unpriced:
        click.echo(
            f"  ⚠ no catalog price for: {', '.join(ceiling.unpriced)}; excluded from ceiling"
        )
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

    if tui:
        app = arena_app_cls(
            cfg=cfg,
            prompts=prompts,
            battle_log_path=output_path,
            live=True,
            preflight=preflight_data,
            dataset=dataset,
        )
        app.run()
    else:
        from .headless import run_headless

        asyncio.run(
            run_headless(
                cfg=cfg,
                prompts=prompts,
                battle_log_path=output_path,
                preflight=preflight_data,
                dataset=dataset,
            )
        )
    _open_report(output_path, no_open)


def _open_report(battle_log_path: str, no_open: bool) -> None:
    """Point the user at the finished report; open it when a human is watching."""
    import os
    import sys
    import webbrowser
    from pathlib import Path

    from .report import report_path_for

    page = report_path_for(Path(battle_log_path))
    if not page.exists():
        return
    click.echo(f"report page -> {page}")
    if not no_open and sys.stdout.isatty() and not os.environ.get("CI"):
        webbrowser.open(page.resolve().as_uri())


@cli.command()
@click.option("--fixture", "fixture_path", default=DEFAULT_FIXTURE, show_default=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
def demo(fixture_path: str, config_path: str) -> None:
    """Replay a recorded tournament from a fixture file (no API calls)."""
    _quiet_logs()
    cfg = load_config(config_path)
    app = _arena_app_cls(_DEMO_HINT)(
        cfg=cfg, prompts=[], battle_log_path="", live=False, fixture=fixture_path
    )
    app.run()


@cli.command("list-models")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
def list_models(config_path: str) -> None:
    """Print the configured candidate roster."""
    cfg = load_config(config_path)
    click.echo(f"{'Seed':<5} {'Name':<26} Model ID")
    click.echo("-" * 70)
    for i, w in enumerate(cfg.candidates, 1):
        click.echo(f"{i:<5} {w.name:<26} {w.model_id}")


@cli.command()
@click.argument("log_path", default=DEFAULT_OUTPUT)
@click.option("--judge", "judges", multiple=True, help="Router model id; repeat for a panel.")
@click.option("--criteria", default=None, help="Override judging criteria.")
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option("--output", "output_path", default=None, help="Write re-judged rounds to this JSONL.")
@click.option("--report-json", default=None, help="Write the summary as JSON.")
@click.option(
    "--compare",
    "compare_jsons",
    multiple=True,
    type=click.Path(exists=True),
    help="Tabulate saved --report-json files side by side; no API calls. "
    "Repeat per file. Use instead of --judge.",
)
@click.option("--concurrency", default=4, show_default=True)
def rejudge(
    log_path: str,
    judges: tuple[str, ...],
    criteria: str | None,
    config_path: str,
    output_path: str | None,
    report_json: str | None,
    compare_jsons: tuple[str, ...],
    concurrency: int,
) -> None:
    """Re-judge a recorded run with a different panel, zero regeneration.

    The evaluatorq demo inside the demo: the responses are already on disk,
    so swapping the jury costs judge tokens only. Prints the new jury's
    behaviour and the Spearman correlation against the recorded ranking.

    The jury-selection loop: run `--judge ... --report-json candidate.json`
    per candidate panel, then `--compare a.json b.json ...` to tabulate them
    side by side (no API calls).
    """
    import asyncio

    _quiet_logs()
    if compare_jsons:
        if judges:
            raise click.ClickException("--compare tabulates saved reports; drop --judge")
        from .rejudge import compare_reports, render_comparison

        render_comparison(compare_reports(list(compare_jsons)))
        return
    if not judges:
        raise click.ClickException("pass --judge <model> (repeatable), or --compare <report.json>")

    from .rejudge import load_records, rejudge_run, render_result, save_report_json, write_rejudged

    cfg = load_config(config_path)
    records = load_records(log_path)
    if not records:
        raise click.ClickException(f"no judgeable rounds in {log_path}")
    click.echo(f"re-judging {len(records)} rounds with panel: {', '.join(judges)}")
    result = asyncio.run(
        rejudge_run(
            cfg=cfg,
            records=records,
            judges=list(judges),
            criteria=criteria,
            concurrency=concurrency,
        )
    )
    render_result(result)
    if output_path:
        write_rejudged(output_path, records, result["comparisons"])
        click.echo(f"re-judged rounds -> {output_path}")
    if report_json:
        save_report_json(report_json, result)
        click.echo(f"summary -> {report_json}")


@cli.command("report")
@click.argument("log_path", default=DEFAULT_OUTPUT)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.option(
    "--output",
    "output_path",
    default=None,
    help="Destination HTML (default: <log>.report.html next to the log).",
)
def report_cmd(log_path: str, config_path: str, output_path: str | None) -> None:
    """Render the single-file HTML report page from a recorded run.

    Reads battles.jsonl and its *.run.json manifest; makes no model calls
    (one catalog read prices the cost section when a key is present).
    The same page is written automatically at the end of every run.
    """
    import asyncio
    import json as _json
    from pathlib import Path

    from .data.schemas import BattleRecord
    from .report import build_report_html, report_path_for
    from .tournament.driver import rebuild_from_log

    cfg = load_config(config_path)
    log = Path(log_path)
    if not log.exists():
        raise click.ClickException(f"{log_path} not found")
    records = [
        BattleRecord.model_validate_json(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records:
        raise click.ClickException(f"no rounds in {log_path}")
    manifest_path = log.with_suffix(".run.json")
    manifest = (
        _json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    elo, rep = rebuild_from_log(cfg, records, preflight=manifest.get("preflight"))

    from .providers.models_list import fetch_price_map

    try:
        prices = asyncio.run(fetch_price_map(cfg.gateway))
    except Exception:
        prices = {}

    out = Path(output_path) if output_path else report_path_for(log)
    out.write_text(
        build_report_html(
            cfg=cfg,
            records=records,
            elo=elo,
            report=rep,
            manifest=manifest,
            prices=prices or None,
        ),
        encoding="utf-8",
    )
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


@cli.command()
@click.argument("battle_log", type=click.Path(exists=True))
@click.option("--out", "out_path", default="annotate.html", show_default=True)
@click.option(
    "--sample",
    type=int,
    default=None,
    help="Annotate a seeded random subset instead of every round.",
)
@click.option("--seed", type=int, default=42, show_default=True)
@click.option(
    "--criteria",
    default=None,
    help="Judging guidelines shown to the rater; default matches the jury's default.",
)
@click.option(
    "--exclude",
    "exclude_files",
    multiple=True,
    type=click.Path(exists=True),
    help="votes.json to exclude already-voted rounds; repeat per file. "
    "Builds a resume page with only the remaining rounds.",
)
@click.option(
    "--serve",
    is_flag=True,
    default=False,
    help="Serve the page on localhost instead of writing a file; votes save "
    "automatically next to the log. Ctrl-C prints the anchor numbers.",
)
@click.option(
    "--port",
    type=int,
    default=8765,
    show_default=True,
    help="Port for --serve (0 picks a free one).",
)
def annotate(
    battle_log: str,
    out_path: str,
    sample: int | None,
    seed: int,
    criteria: str | None,
    exclude_files: tuple[str, ...],
    serve: bool,
    port: int,
) -> None:
    """Render a blinded human-annotation page from a recorded run.

    The page is one self-contained HTML file: open it locally or send it
    to a rater; no model names, no jury votes, seeded side order. Votes
    come back as votes.json for `orq-arena anchor`.
    """
    from pathlib import Path

    from .anchor import DEFAULT_CRITERIA, annotation_items, load_votes, render_annotate_page
    from .rejudge import load_records

    records = load_records(battle_log)
    if not records:
        raise click.ClickException(f"no judgeable rounds in {battle_log}")
    excluded: set[str] = set()
    for vs in load_votes(list(exclude_files)):
        excluded.update(vs.votes)
    items = annotation_items(records, seed=seed, sample=sample, exclude=excluded)
    if not items:
        raise click.ClickException("every round is already voted in the --exclude files")
    page = render_annotate_page(
        items, seed=seed, source=Path(battle_log).name, criteria=criteria or DEFAULT_CRITERIA
    )
    if serve:
        import webbrowser

        from .anchor import anchor_result, make_annotation_server, render_anchor_result

        server = make_annotation_server(page, Path(battle_log).parent, port=port)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        click.echo(f"serving {len(items)} rounds at {url} (Ctrl-C when done)")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        files = sorted(server.votes_written)  # type: ignore[attr-defined]
        if not files:
            click.echo("\nno votes saved")
            return
        click.echo(f"\nvotes: {', '.join(str(f) for f in files)}")
        render_anchor_result(anchor_result(records, load_votes(files)))
        return
    Path(out_path).write_text(page, encoding="utf-8")
    click.echo(
        f"{len(items)} rounds -> {out_path} (blind; votes export as votes.json)"
        + (f", {len(excluded)} already-voted excluded" if excluded else "")
    )


@cli.command()
@click.argument("battle_log", type=click.Path(exists=True))
@click.argument("vote_files", nargs=-1, required=True, type=click.Path(exists=True))
def anchor(battle_log: str, vote_files: tuple[str, ...]) -> None:
    """Merge human vote files against a recorded run: κ + rank correlation.

    Prints per-annotator Cohen's κ vs the panel majority, Spearman rank
    correlation between the human and panel Bradley-Terry rankings, and
    inter-annotator κ when more than one vote file is given.
    """
    from .anchor import anchor_result, load_votes, render_anchor_result
    from .rejudge import load_records

    render_anchor_result(anchor_result(load_records(battle_log), load_votes(list(vote_files))))


@cli.command("list-warriors", hidden=True)
@click.option("--config", "config_path", default=DEFAULT_CONFIG, show_default=True)
@click.pass_context
def list_warriors(ctx: click.Context, config_path: str) -> None:
    """Deprecated alias for list-models."""
    click.echo("list-warriors is deprecated; use list-models", err=True)
    ctx.invoke(list_models, config_path=config_path)


if __name__ == "__main__":
    cli()
