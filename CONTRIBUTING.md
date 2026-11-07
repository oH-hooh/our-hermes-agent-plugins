# Contributing

## Setup

```bash
uv sync
uv run pytest -q
```

Python 3.11 to 3.14 is supported, matching Hermes Agent. Development defaults to
the version in `.python-version`.

## Before opening a pull request

1. Run the tests: `uv run pytest -q`.
2. Run the Hermes catalog check against your change:
   `hermes plugins validate plugins/<plugin> --install-deps`.
   Fix every failure and read every warning.
3. Update the plugin's `CHANGELOG.md` under `Unreleased`.
4. Keep the plugin's README **Disclosure** section accurate. Any new network
   call, file access outside the plugin's data, background task, or credential
   use must be listed there.

## Rules for plugin code

These follow the
[Hermes plugin catalog admission rules](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission#admission-rules):

- Extend Hermes only through public surfaces (`ctx.*`, hooks, `register_*`).
  Never patch Hermes code at runtime. Every remaining use of a Hermes internal
  must be listed in the README disclosure.
- Read secrets and profile-scoped variables through Hermes
  (`agent.secret_scope.get_secret`), never through `os.environ` or `.env` files.
- No self-updating code, no committed binaries or bytecode, no telemetry unless
  it is opt-in.
- Python dependencies need a floor and an upper bound.

## Releasing

1. Bump `version` in the plugin's `plugin.yaml` and `pyproject.toml`, and move
   `Unreleased` changelog entries under the new version.
2. Tag the commit `<plugin>-v<version>`, for example
   `telegram-skill-review-v0.1.0`.
3. For catalog-listed plugins, open a SHA-bump PR to
   `plugin-catalog/<plugin>.yaml` in NousResearch/hermes-agent that pins the
   tagged commit's full 40-character SHA.
