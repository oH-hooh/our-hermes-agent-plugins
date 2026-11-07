# session-notes

A Hermes Desktop plugin. It drafts a short summary of the focused chat session, lets you edit it, and saves it to a Notion database with topic tags.

## Requirements

- Hermes Desktop with Hermes `>=0.22`.
- `hermes` on the `PATH` of the process that runs the plugin. Summaries are produced by running `hermes chat -Q -t ""` (no tools), so they use your configured model and count against its usage.
- A Notion account where you can create an internal integration.

## Install

### 1. Create the Notion database

Create a database with exactly these properties (names are case-sensitive):

| Property | Type |
|---|---|
| `Name` | Title |
| `Date` | Date |
| `Session ID` | Text |
| `Topics` | Multi-select |

### 2. Create a Notion integration

1. Go to <https://www.notion.so/profile/integrations> and create an **internal** integration. It needs read, update and insert content capabilities.
2. Copy its token.
3. Open the database in Notion, choose **⋯ → Connections**, and add the integration. Without this the API returns 404.

### 3. Find the data source ID

The plugin uses Notion API version `2025-09-03`, which addresses a database through its *data source*. Get the ID with:

```bash
curl -s https://api.notion.com/v1/databases/<DATABASE_ID> \
  -H "Authorization: Bearer $NOTION_API_KEY" \
  -H "Notion-Version: 2025-09-03" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data_sources"])'
```

`<DATABASE_ID>` is the 32-character ID in the database URL. Use the `id` of the data source in the output.

### 4. Install the plugin

Copy or symlink the `plugins/session-notes/` directory into your Hermes plugins directory:

```bash
git clone https://github.com/oH-hooh/our-hermes-agent-plugins
ln -s "$PWD/our-hermes-agent-plugins/plugins/session-notes" ~/.hermes/plugins/session-notes
hermes plugins validate ~/.hermes/plugins/session-notes
```

Use `$HERMES_HOME/plugins/` instead of `~/.hermes/plugins/` if you set `HERMES_HOME` or use a profile.

### 5. Configure

Add the two values to `~/.hermes/.env` (or export them in the environment that starts Hermes):

```bash
NOTION_API_KEY=secret_xxx
SESSION_NOTES_NOTION_DATA_SOURCE_ID=<data source id from step 3>
```

Neither value is stored in the plugin.

### 6. Enable and restart

```bash
hermes plugins enable session-notes
```

Restart Hermes Desktop. The **Summary** tab appears in the right-hand pane area.

### Troubleshooting

| Symptom | Cause |
|---|---|
| `... is not set (see the plugin README)` | A variable from step 5 is missing in the environment Hermes was started from. |
| `Notion 404` | The integration was not added to the database (step 2.3), or the data source ID is wrong. |
| `Notion 400` mentioning a property | The database properties don't match the table in step 1. |
| `` `hermes` was not found on PATH `` | Start Hermes Desktop from a shell where `hermes` resolves, or add it to the app's PATH. |

## How to use

1. Open a session. The pane works on the focused session.
2. Open the **Summary** tab in the right-hand pane area. You can drag it elsewhere.
3. Click **Summarize whole session**. A draft appears in the text box. It can take up to a minute.
4. Edit the draft if you want. Keep the `- id:` line.
5. Click **Save to Notion**.

| Button | What it does |
|---|---|
| Summarize whole session | Writes a new draft from the full transcript, replacing the current one. It also suggests topic tags. |
| Summarize new | Summarizes only messages added since the last summary and appends them as `## Update <date time>`. Your edits to the existing text are kept and passed to the model as authoritative. Needs an earlier summary. |
| Suggest topics | Generates 2–5 tags for the current draft and writes them to the `- topics:` line. Use it to tag older drafts. |
| Save to Notion | Creates the Notion page, or replaces the existing page if this session was saved before. |

The summary format can be changed per session or as a global default from the pane. The built-in format is: at most 5 bullet points, then one line starting `Outcome:`.

## Draft format

```markdown
# <session title>

- id: <session id>
- topics: tag one, tag two, tag three

- bullet points ...
Outcome: ...
```

- `- id:` is required. Save refuses a draft without it.
- `- topics:` is a comma-separated list. On save it becomes the Notion `Topics` property and is removed from the page body.
- The first `#` line becomes the Notion page title.

## Topic tags

Tags are 1–3 lowercase words. The model is shown the options already in the Notion `Topics` column and told to reuse them when they fit, to keep tags consistent. If tagging fails, the summary is still written without tags.

If a saved page was deleted or trashed in Notion, the next save creates a new page.

## Files and data

| File | Role |
|---|---|
| `plugin.yaml` | Plugin metadata. |
| `__init__.py` | Python entry point. `register()` does nothing: there are no slash commands. |
| `core.py` | All logic: draft files, watermarks, summarizing, topic tags, Notion save. |
| `dashboard/manifest.json`, `dashboard/plugin_api.py` | FastAPI backend at `/api/plugins/session-notes/*`. |
| `desktop/plugin.js` | The pane UI. |
| `tests/` | Unit tests (`pytest session-notes/tests`). They never call Notion or a model. |

Data is stored under `$HERMES_HOME/session-summaries/` (default `~/.hermes/session-summaries/`):

| Path | Contents |
|---|---|
| `drafts/<session-id>.md` | Current draft per session. |
| `saved.json` | Session id → Notion page URL. |
| `watermarks.json` | Session id → last message id covered by a summary. Used by "Summarize new". |
| `format.txt`, `session-formats.json` | Global and per-session summary formats. |

The plugin reads session titles and messages read-only from `$HERMES_HOME/state.db`.

Hermes copies `desktop/` into `$HERMES_HOME/desktop-plugins/session-notes/` itself. Edit `desktop/plugin.js` in the plugin, never the copy.

## API

All routes are under `/api/plugins/session-notes`.

| Route | Body | Returns |
|---|---|---|
| `GET /draft?session_id=` | | `draft`, `saved`, `title` |
| `POST /generate` | `session_id`, `format?` | `ok`, `draft` or `error` |
| `POST /generate_new` | `session_id`, `text?`, `format?` | `ok`, `chunk` or `error` |
| `POST /suggest_topics` | `session_id`, `text?` | `ok`, `draft`, `topics` or `error` |
| `POST /save` | `session_id`, `text?` | `ok`, `message` |
| `GET /format?session_id=` | | `format`, `source`, `builtin` |
| `POST /format` | `text`, `session_id?`, `scope` (`session`, `default`, `reset`) | `ok`, `format`, `source` |

## Privacy

Session text is sent to your configured Hermes model to produce summaries, and the summary you choose to save is sent to Notion. Nothing else leaves your machine.

## Known limitations

- Watermarks and `saved.json` are written without locking. Don't run two saves at once.
- Sessions saved before topic tags existed have no tags until you re-save them.
- The `Notion-Version` is pinned to `2025-09-03`.

## License

MIT, see [`LICENSE`](./LICENSE).
