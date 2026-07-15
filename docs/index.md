# orq-arena documentation

Guides for running, configuring, and trusting the arena. The
[project README](https://github.com/orq-ai/orq-arena/blob/master/README.md) is the front door; these pages carry the detail.

![HTML report page: verdict banner with the top three models, badges, ELO leaderboard with CI bars, and the ELO-vs-cost value map](assets/report-page.png)

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install, run the zero-key demo, and get your first live tournament running.

    [:octicons-arrow-right-24: Getting Started](getting-started.md)

-   :material-console:{ .lg .middle } **CLI Reference**

    ---

    Every command and flag with its expected output: `run`, `demo`, `rejudge`
    (with `--compare`), `report`, `annotate`, `anchor`, `list-models`,
    `refresh-models`.

    [:octicons-arrow-right-24: CLI Reference](cli.md)

-   :material-tune:{ .lg .middle } **Configuration**

    ---

    Every `orq_arena.yaml` key, its type, default, and effect, plus the
    prompts file format and `.env` loading.

    [:octicons-arrow-right-24: Configuration](configuration.md)

-   :material-scale-balance:{ .lg .middle } **Methodology**

    ---

    How the ranking is made, the bias controls, confidence intervals, and
    when to trust the number.

    [:octicons-arrow-right-24: Methodology](methodology.md)

</div>

## Suggested reading order

- **Running benchmarks?** [Getting Started](getting-started.md) → [Configuration](configuration.md) → [CLI Reference](cli.md)
- **Contributing code?** [CONTRIBUTING.md](https://github.com/orq-ai/orq-arena/blob/master/CONTRIBUTING.md) has the dev setup, project shape, and PR conventions
