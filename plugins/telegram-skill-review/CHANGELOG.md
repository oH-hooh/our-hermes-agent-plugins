# Changelog

All notable changes to `telegram-skill-review` are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0]

### Added

- Deliver autonomous pending skill writes to a separate Telegram topic per
  proposal, with the full proposed content split across Rich Messages.
- Approve and Reject buttons that apply or discard the staged write without an
  LLM call, after the Hermes Telegram callback authorization check.
- Multi-profile review: one bot-owning profile reviews several source profiles
  and applies each skill inside its source profile's Hermes home.
- Durable delivery and decision state with restart recovery, bounded
  exponential retry backoff, and a private local review ledger.
- `TELEGRAM_HOME_CHANNEL` fallback read through the Hermes profile secret scope.

[Unreleased]: https://github.com/oH-hooh/our-hermes-agent-plugins/compare/telegram-skill-review-v0.1.0...HEAD
[0.1.0]: https://github.com/oH-hooh/our-hermes-agent-plugins/releases/tag/telegram-skill-review-v0.1.0
