# Our Hermes Agent Plugins

[![CI](https://github.com/oH-hooh/our-hermes-agent-plugins/actions/workflows/ci.yml/badge.svg)](https://github.com/oH-hooh/our-hermes-agent-plugins/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

Open-source plugins for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
Each plugin lives in its own directory under `plugins/`, with its own
`plugin.yaml`, version, changelog, tests, and README. Install, validate, and
release each one independently.

## Plugins

| Plugin | Description | Hermes |
|---|---|---|
| [`telegram-skill-review`](./plugins/telegram-skill-review/) | Sends autonomous pending skill proposals to separate Telegram topics and applies Approve or Reject decisions without an LLM call. | `>=0.21.6` |

## Install

Install a plugin straight from this repository by its subdirectory:

```bash
hermes plugins install oH-hooh/our-hermes-agent-plugins/plugins/<plugin> --no-enable
hermes plugins enable <plugin>
```

Read the plugin's README first. Its **Disclosure** section lists network calls,
file access, and background tasks, and its **Installation** section covers the
configuration it needs.

## Development

```bash
uv sync
uv run pytest -q
hermes plugins validate plugins/<plugin> --install-deps
```

The repository is a uv workspace. The root `pyproject.toml` and `uv.lock`
coordinate development, and each plugin keeps its deployment metadata in a
colocated `pyproject.toml`. CI runs the tests on Python 3.11 and 3.14, and runs
`hermes plugins validate` against each plugin's `requires_hermes` floor and the
latest Hermes release.

See [CONTRIBUTING.md](./CONTRIBUTING.md) and [SECURITY.md](./SECURITY.md).

## License

[MIT](./LICENSE)
