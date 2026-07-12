<!-- generated-by: gsd-doc-writer -->
# orq-arena documentation

Guides for running, configuring, trusting, and extending the arena. The
[project README](../README.md) is the front door; these pages carry the detail.

| Guide | Read it when you want to |
|-------|--------------------------|
| [Getting Started](getting-started.md) | Install, run the zero-key demo, and get your first live tournament running |
| [CLI Reference](cli.md) | Look up any command or flag, `run`, `demo`, `rejudge`, `report`, `list-warriors`, `refresh-models` |
| [Configuration](configuration.md) | Understand every `orq_arena.yaml` key, its type, default, and effect |
| [Methodology](methodology.md) | See exactly how the ELO is made, judging protocol, Bradley-Terry, CIs, κ, and what a real run measured |
| [Architecture](architecture.md) | Learn the component layout, event flow, and design invariants before changing code |
| [Testing](testing.md) | Run the suite, understand the test map, write a new test |
| [Development](development.md) | Set up a dev environment and follow the project's conventions |

## Suggested reading order

- **Evaluating the tool?** [Getting Started](getting-started.md) → [Methodology](methodology.md)
- **Running benchmarks?** [Getting Started](getting-started.md) → [Configuration](configuration.md) → [CLI Reference](cli.md)
- **Contributing code?** [Architecture](architecture.md) → [Development](development.md) → [Testing](testing.md), plus [CONTRIBUTING.md](../CONTRIBUTING.md)
