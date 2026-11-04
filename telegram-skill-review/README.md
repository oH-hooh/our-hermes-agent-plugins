# Telegram Skill Review

`telegram-skill-review` sends autonomous Hermes skill proposals to Telegram for delayed human review. Each proposal receives a separate Telegram DM topic containing the complete proposed content, followed by **Approve** and **Reject** buttons.

## Behavior

1. Hermes stages a skill operation under `<HERMES_HOME>/pending/skills/` when `skills.write_approval` is enabled.
2. The plugin scans the durable pending directory without blocking the originating conversation.
3. Every autonomous proposal receives a new Telegram topic.
4. Each content message identifies the Hermes profile that produced the proposal.
5. The complete proposal is sent through `sendRichMessage`. Long content is divided among messages in the same topic.
6. **Approve** calls Hermes `apply_skill_pending()` directly.
7. **Reject** removes the pending proposal directly.
8. The content messages remain in Telegram after either decision.
9. The plugin removes the buttons, posts the final status, renames the topic, and writes a local review ledger.
10. One bot-owning profile can review several source profiles. Skill application runs inside the source profile's Hermes home.

No LLM request occurs during delivery, approval, rejection, or status updates.

## Requirements

- A Hermes version that provides:
  - `skills.write_approval`
  - `tools.write_approval`
  - `tools.skill_manager_tool.apply_skill_pending`
  - `ctx.register_platform_handler()`
  - `ctx.spawn_task()`
- Telegram configured for the same Hermes profile.
- Telegram Threaded Mode enabled for the bot through BotFather.
- A private Telegram chat ID supplied through plugin settings or `TELEGRAM_HOME_CHANNEL`.

## Installation

Install the plugin directory using your normal local plugin workflow, enable it for the target profile, and restart that profile's gateway.

Install and configure the plugin only in the profile that owns the Telegram bot. Every listed source profile must enable `skills.write_approval`; source profiles do not need Telegram configuration or their own plugin installation.

Configure the profile:

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

`chat_id` may be omitted when `TELEGRAM_HOME_CHANNEL` already points to the intended private chat.

The bot owner's Telegram authorization governs every listed source profile. Adding a name to `source_profiles` grants the bot's authorized reviewers permission to approve skill changes for that profile. Configuration fails when a listed profile directory does not exist.

With `include_foreground: false`, only records whose origin is `background_review` are sent. Foreground records remain available through Hermes `/skills pending` commands.

## Telegram review lifecycle

A proposal topic contains:

- one or more numbered content messages;
- the originating Hermes profile in every content-message header and topic title;
- one control message with **Approve** and **Reject** buttons;
- one final status message after a decision.

Approval failures preserve the pending record and buttons. A successful decision is recorded before Telegram presentation updates. When Telegram is unavailable, the scanner resumes the missing button, status, and topic updates without applying the skill operation again.

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
| `chat_id` | empty | Target private Telegram chat; falls back to `TELEGRAM_HOME_CHANNEL` |
| `source_profiles` | `[]` | Profiles reviewed through this bot; empty selects the plugin's own profile |
| `include_foreground` | `false` | Include foreground skill operations |
| `max_message_chars` | `30000` | Character budget for each Rich Message |
| `scan_interval_seconds` | `2` | Pending-directory scan interval |

## Tests

```bash
uv run --with pytest --python 3.12 pytest tests/test_review.py -q
```

From the repository root:

```bash
uv run --with pytest --python 3.12 pytest telegram-skill-review/tests/test_review.py -q
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
