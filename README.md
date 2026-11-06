# Our Hermes Agent Plugins

Shared Hermes Agent plugins maintained as separate installable directories in
an uv workspace. Each plugin owns its runtime metadata and can be installed,
validated, and released independently.

## Development

The repository uses the Python 3.14 runtime required by current Hermes Agent
installations. The root `pyproject.toml` and `uv.lock` coordinate development;
each plugin keeps its deployment dependencies in a colocated `pyproject.toml`.

```bash
uv sync
uv run pytest
```

## Plugins

| Plugin | Description |
|---|---|
| [`telegram-skill-review`](./plugins/telegram-skill-review/) | Sends autonomous pending skill proposals to separate Telegram topics and applies delayed Approve or Reject decisions without an LLM call. |

Each directory under `plugins/` contains its own `plugin.yaml`,
`pyproject.toml`, implementation, tests, configuration instructions, and
operational notes.
