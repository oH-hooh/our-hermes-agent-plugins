# Telegram Skill Review

`telegram-skill-review` sends autonomous Hermes skill proposals to Telegram for delayed human review. Each proposal receives a separate Telegram DM topic containing the complete proposed content, followed by **Approve** and **Reject** buttons.

Nothing is applied without a human tapping **Approve**. The plugin never auto-approves, and no LLM request occurs during delivery, approval, rejection, or status updates.

## Behavior

1. Hermes stages a skill operation under `<HERMES_HOME>/pending/skills/` when `skills.write_approval` is enabled.
2. The plugin scans the durable pending directory without blocking the originating conversation.
3. Every autonomous proposal receives a new Telegram topic.
4. Each content message identifies the Hermes profile that produced the proposal.
5. The complete proposal is sent through `sendRichMessage`. Long content is divided among messages in the same topic.
6. **Approve** replays the exact staged write through Hermes `apply_skill_pending()`.
7. **Reject** removes the pending proposal.
8. The content messages remain in Telegram after either decision.
9. The plugin removes the buttons, posts the final status, renames the topic, and writes a local review ledger.
10. One bot-owning profile can review several source profiles. Skill application runs inside the source profile's Hermes home.

## Disclosure

What this plugin does that you should know before installing:

- **Network calls to Telegram.** Proposal content, skill names, and the source profile name are sent to the Telegram Bot API through the bot the Hermes gateway already runs. The plugin stores no credential of its own.
- **Full skill content leaves the machine.** Every eligible staged skill write is sent in full to the configured Telegram chat and stays in that chat after the decision.
- **Reads and writes outside its own data.** It reads and updates `pending/skills/*.json` and, on approval, writes skills in each listed source profile's Hermes home, including profiles other than the one it is installed in.
- **Background task.** While the gateway runs, one scanner per source profile polls the pending directory every `scan_interval_seconds` (default 2 s).
- **Local ledger.** Decisions are appended to `plugin-data/telegram-skill-review/review-ledger.jsonl` (mode `0600`) with the reviewer's Telegram user ID.
- **No shell commands, no subprocesses, no telemetry.**
- **Uses Hermes internals.** Approval calls `tools.skill_manager_tool.apply_skill_pending`, authorization calls the Telegram adapter's callback authorization check, and profile binding uses `hermes_constants.set_hermes_home_override`. These are not yet public plugin APIs, so a future Hermes release may require a plugin update.

## Requirements

- Hermes Agent `>=0.21.6`, with the gateway running for the profile that owns the Telegram bot.
- Python 3.11 to 3.14, the same range Hermes supports. No third-party Python dependencies.
- Telegram configured for that profile, with Threaded Mode enabled for the bot through BotFather.
- A private Telegram chat ID, supplied through the `chat_id` setting or the profile's `TELEGRAM_HOME_CHANNEL`.

## Installation

Install and configure the plugin only in the profile that owns the Telegram bot (`<BOT_PROFILE>` below):

```bash
hermes -p <BOT_PROFILE> plugins install oH-hooh/our-hermes-agent-plugins/plugins/telegram-skill-review --no-enable
hermes -p <BOT_PROFILE> plugins enable telegram-skill-review
```

Every listed source profile must enable `skills.write_approval`. Source profiles do not need Telegram configuration or their own plugin installation.

Configure the bot profile's `config.yaml`:

```yaml
skills:
  write_approval: true

plugins:
  enabled:
    - telegram-skill-review
  entries:
    telegram-skill-review:
      settings:
        chat_id: "<TG_ID>"
        source_profiles: [<PROFILE_NAME>, <PROFILE_NAME2>]
        include_foreground: false
```

Then restart the gateway:

```bash
hermes -p <BOT_PROFILE> gateway restart
```

`chat_id` may be omitted when the bot profile's `TELEGRAM_HOME_CHANNEL` already points to the intended private chat. The fallback is read through Hermes's profile secret scope, so it never picks up another profile's value. When the scope is unavailable, the plugin logs a warning and stays idle until `chat_id` is set.

The bot owner's Telegram authorization governs every listed source profile. Adding a name to `source_profiles` grants the bot's authorized reviewers permission to approve skill changes for that profile. Configuration fails when a listed profile directory does not exist.

With `include_foreground: false`, only records whose origin is `background_review` are sent. Foreground records remain available through Hermes `/skills pending` commands.

## Telegram review lifecycle

A proposal topic contains:

- one or more numbered content messages;
- the originating Hermes profile in every content-message header and topic title;
- one control message with **Approve** and **Reject** buttons;
- one final status message after a decision.

Approval failures preserve the pending record and buttons. A successful decision is recorded before Telegram presentation updates. When Telegram is unavailable, the scanner resumes the missing button, status, and topic updates without applying the skill operation again.

## Unattended runs

Proposals wait for a human indefinitely, but nothing in Hermes waits on them. Staging returns immediately, so background review, cron, and the gateway keep running. A staged write stays pending until someone taps a button or uses `/skills pending`.

## Persistent files

The plugin reads staged records from:

```text
<HERMES_HOME>/pending/skills/*.json
```

It writes coordination data under:

```text
<HERMES_HOME>/plugin-data/telegram-skill-review/
├── locks/
└── review-ledger.jsonl
```

The ledger records pending ID, skill name, decision, Telegram user, topic, content message IDs, control message ID, status message ID, and decision time.

## Recovery

The pending JSON record stores delivery progress. The scanner resumes after a gateway restart and retries interrupted deliveries with bounded exponential backoff. Telegram callbacks resolve against the pending record on disk, so approval can occur after process restarts.

## Settings

| Setting | Default | Meaning |
|---|---:|---|
| `chat_id` | empty | Target private Telegram chat; falls back to the profile's `TELEGRAM_HOME_CHANNEL` |
| `source_profiles` | `[]` | Profiles reviewed through this bot; empty selects the plugin's own profile |
| `include_foreground` | `false` | Include foreground skill operations |
| `max_message_chars` | `30000` | Character budget for each Rich Message |
| `scan_interval_seconds` | `2` | Pending-directory scan interval |

## Tests

From the repository root:

```bash
uv run pytest plugins/telegram-skill-review/tests -q
hermes plugins validate plugins/telegram-skill-review
```

## Security properties

- Telegram button callers pass the Hermes Telegram authorization check.
- Callback data contains the source profile and a bounded pending ID, so one shared Telegram bot can route decisions to the correct profile plugin instance.
- Chat and topic identifiers must match the stored proposal delivery record.
- Decisions use a filesystem lock.
- Approval replays the exact stored payload.
- Approval binds Hermes path and skill configuration resolution to the source profile.
- A callback profile, stored profile, chat, or topic mismatch performs no skill mutation.
- The pending record is retained when application fails.

Report vulnerabilities as described in [SECURITY.md](../../SECURITY.md).

## License

MIT. See [LICENSE](../../LICENSE).
