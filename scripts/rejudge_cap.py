"""Run an orq-arena command under a given evaluatorq in-flight judge cap.

    uv run python scripts/rejudge_cap.py 48 rejudge LOG --config CFG --concurrency 8

Used for docs/research/rejudge-cap-timing.json; the CLI has no flag for the cap.
"""

import sys

from evaluatorq import llm_concurrency_limit

from orq_arena.cli import cli

with llm_concurrency_limit(int(sys.argv[1])):
    cli.main(sys.argv[2:], prog_name="orq-arena")
