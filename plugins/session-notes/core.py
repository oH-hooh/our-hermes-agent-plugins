"""Shared logic for the session-notes plugin (desktop pane)."""
import json
import os
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser(os.environ.get("HERMES_HOME") or "~/.hermes")
DRAFTS = f"{HOME}/session-summaries/drafts"
DB = f"{HOME}/state.db"


def title(sid):
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute("select title from sessions where id=?", (sid,)).fetchone()
        con.close()
        return row[0] if row and row[0] else "(untitled)"
    except Exception:
        return "(untitled)"


def draft_path(sid):
    return f"{DRAFTS}/{sid}.md"


SAVED_JSON = f"{HOME}/session-summaries/saved.json"

# Notion settings come from the environment or $HERMES_HOME/.env (never hardcoded):
#   NOTION_API_KEY                       integration token
#   SESSION_NOTES_NOTION_DATA_SOURCE_ID  data source ID of the target database
NOTION_VERSION = "2025-09-03"


def _env(name):
    """Value of `name` from the environment, else from $HERMES_HOME/.env, else None."""
    val = os.environ.get(name)
    if val:
        return val
    try:
        with open(f"{HOME}/.env") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip().strip("\"'") or None
    except OSError:
        pass
    return None


def _data_source_id():
    val = _env("SESSION_NOTES_NOTION_DATA_SOURCE_ID")
    if not val:
        raise RuntimeError("SESSION_NOTES_NOTION_DATA_SOURCE_ID is not set (see the plugin README)")
    return val


def _llm(instruction, stdin):
    """Ask the configured Hermes model, with no tools. Always returns a CompletedProcess (errors go in stderr)."""
    exe = shutil.which("hermes")
    if not exe:
        return subprocess.CompletedProcess([], 127, "", "`hermes` was not found on PATH")
    try:
        return subprocess.run([exe, "chat", "-Q", "-t", "", "-q", f"{instruction}\n\n{stdin}"],
                              capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 124, "", "the model call timed out after 300s")


def _read_json(path):
    with open(path) as f:
        return json.load(f)


def _saved_map():
    try:
        return _read_json(SAVED_JSON)
    except Exception:
        return {}


def is_saved(sid):
    return sid in _saved_map()


def read_draft(sid):
    p = draft_path(sid)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return f.read()


WATERMARKS = f"{HOME}/session-summaries/watermarks.json"


def _wm_load():
    try:
        return _read_json(WATERMARKS)
    except Exception:
        return {}


def _wm_set(sid, last_id):
    m = _wm_load()
    m[sid] = last_id
    os.makedirs(os.path.dirname(WATERMARKS), exist_ok=True)
    with open(WATERMARKS, "w") as f:
        json.dump(m, f)


def _last_message_id(sid):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    row = con.execute("select max(id) from messages where session_id=?", (sid,)).fetchone()
    con.close()
    return row[0] or 0


FORMAT_FILE = f"{HOME}/session-summaries/format.txt"
DEFAULT_FORMAT = "Summarize the key idea in at most 5 bullet points, then one line starting 'Outcome:'."


SESSION_FORMATS = f"{HOME}/session-summaries/session-formats.json"


def _sf_load():
    try:
        return _read_json(SESSION_FORMATS)
    except Exception:
        return {}


def get_default_format():
    """Global default format; the built-in one if none is saved."""
    try:
        with open(FORMAT_FILE) as f:
            return f.read().strip() or DEFAULT_FORMAT
    except Exception:
        return DEFAULT_FORMAT


def format_source(sid=None):
    if sid and _sf_load().get(sid, "").strip():
        return "session"
    return "default" if os.path.exists(FORMAT_FILE) and get_default_format() != DEFAULT_FORMAT else "built-in"


def get_format(sid=None):
    """Effective format: this session's own, else the global default, else the built-in."""
    if sid:
        t = _sf_load().get(sid, "").strip()
        if t:
            return t
    return get_default_format()


def set_format(text):
    """Save the global default. Empty text restores the built-in. Returns the format now in effect."""
    text = (text or "").strip()
    if not text or text == DEFAULT_FORMAT:
        if os.path.exists(FORMAT_FILE):
            os.remove(FORMAT_FILE)
        return DEFAULT_FORMAT
    os.makedirs(os.path.dirname(FORMAT_FILE), exist_ok=True)
    with open(FORMAT_FILE, "w") as f:
        f.write(text + "\n")
    return text


def set_session_format(sid, text):
    """Save (or, with empty text, clear) the format for one session. Returns the effective format."""
    m = _sf_load()
    text = (text or "").strip()
    if text:
        m[sid] = text
    else:
        m.pop(sid, None)
    os.makedirs(os.path.dirname(SESSION_FORMATS), exist_ok=True)
    with open(SESSION_FORMATS, "w") as f:
        json.dump(m, f, indent=1)
    return get_format(sid)


def _transcript(sid, after_id=0):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "select role, content from messages where session_id=? and id>? and active=1 "
        "and role in ('user','assistant') and content is not null and content!='' order by id",
        (sid, after_id)).fetchall()
    con.close()
    return "\n\n".join(f"{r[0].upper()}: {r[1]}" for r in rows)


def generate_new(sid, current_text=None, fmt=None):
    """Summarize only messages after the last summary. Appends to the draft file.
    Returns (ok, chunk_or_error). Existing text is never modified."""
    wm = _wm_load().get(sid)
    if wm is None:
        return False, "No earlier summary of this session. Use 'Summarize whole session' first."
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "select id, role, content from messages where session_id=? and id>? and active=1 "
        "and role in ('user','assistant') and content is not null and content!='' order by id",
        (sid, wm)).fetchall()
    last = con.execute("select max(id) from messages where session_id=?", (sid,)).fetchone()[0] or wm
    con.close()
    if not rows:
        return False, "No new messages since the last summary."
    excerpt = "\n\n".join(f"{r[1].upper()}: {r[2]}" for r in rows)
    existing = (current_text if current_text is not None else read_draft(sid) or "").strip()
    instruction = (
        "You are extending an existing summary of a conversation. Below are the EXISTING SUMMARY "
        "(the user may have edited it; treat it as authoritative) and the NEW MESSAGES that came after it. "
        "Write ONLY what the new messages add, and keep it short. Do not repeat points already in the "
        "existing summary. Follow this user-defined format for what you write: "
        f"<format>{(fmt or '').strip() or get_format(sid)}</format> "
        "If the new messages correct or contradict the existing summary, say so explicitly with a bullet "
        "starting 'Correction:'. Do not rewrite the existing summary. Do not use any tools.")
    r = _llm(instruction, f"EXISTING SUMMARY:\n{existing or '(none)'}\n\nNEW MESSAGES:\n{excerpt}")
    body = "\n".join(l for l in (r.stdout or "").splitlines() if not l.startswith("session_id:")).strip()
    if not body:
        return False, (r.stderr or "empty summary").strip()[:300]
    chunk = f"## Update {time.strftime('%Y-%m-%d %H:%M')}\n\n{body}"
    base = current_text if current_text is not None else (read_draft(sid) or "")
    os.makedirs(DRAFTS, exist_ok=True)
    with open(draft_path(sid), "w") as f:
        f.write(base.rstrip("\n") + "\n\n" + chunk + "\n" if base.strip() else
                f"# {title(sid)}\n\n- id: {sid}\n\n{chunk}\n")
    _wm_set(sid, last)
    return True, chunk


def parse_topics(text):
    for line in text.splitlines():
        if line.lower().startswith("- topics:"):
            return [t.strip()[:100] for t in line.split(":", 1)[1].split(",") if t.strip()]
    return []


def set_topics_line(text, topics):
    """Insert or replace the '- topics:' line (placed right after the '- id:' line)."""
    lines = [l for l in text.splitlines() if not l.lower().startswith("- topics:")]
    new = "- topics: " + ", ".join(topics)
    for i, l in enumerate(lines):
        if l.startswith("- id:"):
            lines.insert(i + 1, new)
            break
    else:
        lines.insert(min(1, len(lines)), new)
    return "\n".join(lines).rstrip("\n") + "\n"


def _existing_topics():
    try:
        r = _notion_request("GET", f"data_sources/{_data_source_id()}", None)
        return [o["name"] for o in r["properties"]["Topics"]["multi_select"]["options"]]
    except Exception:
        return []


def suggest_topics(text):
    """Return (ok, topics_or_error). Asks the model for 2-5 short tags, reusing existing Notion options."""
    existing = _existing_topics()
    instruction = (
        "Choose 2 to 5 short topic tags (1-3 words each, lowercase, no commas) for the conversation summary below. "
        + (f"Reuse these existing tags whenever they fit, and only invent a new one when none does: {', '.join(existing)}. "
           if existing else "")
        + "Reply with ONLY the tags separated by commas, on a single line. Do not use any tools.")
    r = _llm(instruction, text)
    lines = [l.strip() for l in (r.stdout or "").splitlines() if l.strip() and not l.startswith("session_id:")]
    if not lines:
        return False, (r.stderr or "empty answer").strip()[:300]
    tags = []
    for t in lines[-1].split(","):
        t = t.strip().strip("#`\"'").lower()[:100]
        if t and t not in tags:
            tags.append(t)
    return (True, tags[:5]) if tags else (False, "no tags returned")


def generate(sid, fmt=None):
    """Return (ok, text_or_error). Writes the draft file."""
    last = _last_message_id(sid)
    transcript = _transcript(sid)
    if not transcript:
        return False, "This session has no messages to summarize."
    instruction = (f"Summarize the following conversation transcript. Follow this user-defined format: "
                   f"<format>{(fmt or '').strip() or get_format(sid)}</format> Do not use any tools.")
    r = _llm(instruction, transcript)
    body = "\n".join(l for l in (r.stdout or "").splitlines()
                     if not l.startswith("session_id:")).strip()
    if not body:
        return False, (r.stderr or "empty summary").strip()[:300]
    _wm_set(sid, last)
    os.makedirs(DRAFTS, exist_ok=True)
    text = f"# {title(sid)}\n\n- id: {sid}\n\n{body}\n"
    ok2, tags = suggest_topics(text)
    if ok2:
        text = set_topics_line(text, tags)
    with open(draft_path(sid), "w") as f:
        f.write(text)
    return True, text


def _notion_key():
    key = _env("NOTION_API_KEY")
    if not key:
        raise RuntimeError("NOTION_API_KEY is not set (see the plugin README)")
    return key


def session_date(sid):
    """Local date (YYYY-MM-DD) the session started; today if unknown."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute("select started_at from sessions where id=?", (sid,)).fetchone()
        con.close()
        if row and row[0]:
            return time.strftime("%Y-%m-%d", time.localtime(row[0]))
    except Exception:
        pass
    return time.strftime("%Y-%m-%d")


def _notion_create(sid, name, markdown, topics=()):
    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps({
            "parent": {"type": "data_source_id", "data_source_id": _data_source_id()},
            "properties": {
                "Name": {"title": [{"text": {"content": name[:200]}}]},
                "Date": {"date": {"start": session_date(sid)}},
                "Session ID": {"rich_text": [{"text": {"content": sid}}]},
                "Topics": {"multi_select": [{"name": t} for t in topics]},
            },
            "markdown": markdown,
        }).encode(),
        headers={"Authorization": f"Bearer {_notion_key()}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Notion {e.code}: {e.read().decode()[:300]}")


def _notion_request(method, path, payload):
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}", data=json.dumps(payload).encode() if payload is not None else None, method=method,
        headers={"Authorization": f"Bearer {_notion_key()}", "Notion-Version": NOTION_VERSION,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Notion {e.code}: {e.read().decode()[:300]}")


def _notion_update(page_url, name, markdown, topics=()):
    """Replace title and whole body of an existing page. Raises if gone/archived."""
    pid = page_url.rstrip("/").split("-")[-1]
    page = _notion_request("PATCH", f"pages/{pid}",
                           {"properties": {"Name": {"title": [{"text": {"content": name[:200]}}]},
                                           "Topics": {"multi_select": [{"name": t} for t in topics]}}})
    if page.get("in_trash") or page.get("archived"):
        raise RuntimeError("page is in the trash")
    _notion_request("PATCH", f"pages/{pid}/markdown",
                    {"type": "replace_content", "replace_content": {"new_str": markdown}})
    return page


def save(sid, text=None):
    """Create the Notion page, or replace the existing one if this session was saved before."""
    p = draft_path(sid)
    if text is None:
        if not os.path.exists(p):
            return False, "No draft for this session. Generate one first."
        text = read_draft(sid)
    text = text.strip()
    if f"- id: {sid}" not in text:
        return False, f"Entry must keep the line '- id: {sid}'."
    first, _, rest = text.partition("\n")
    name = first.lstrip("# ").strip() or title(sid)
    body = rest.strip() if first.startswith("#") else text
    topics = parse_topics(text)
    body = "\n".join(l for l in body.splitlines() if not l.lower().startswith("- topics:")).strip()
    m = _saved_map()
    verb = "Saved"
    try:
        if sid in m:
            try:
                page = _notion_update(m[sid], name, body, topics)
                verb = "Updated"
            except RuntimeError as e:
                if "404" not in str(e) and "trash" not in str(e):
                    raise
                page = _notion_create(sid, name, body, topics)  # old page deleted: make a new one
        else:
            page = _notion_create(sid, name, body, topics)
    except Exception as e:
        return False, f"Notion save failed: {e}"
    m[sid] = page.get("url", page.get("id"))
    os.makedirs(os.path.dirname(SAVED_JSON), exist_ok=True)
    with open(SAVED_JSON, "w") as f:
        json.dump(m, f, indent=1)
    os.makedirs(DRAFTS, exist_ok=True)
    with open(p, "w") as f:  # keep the saved text so later 'summarize new' appends to it
        f.write(text + "\n")
    return True, f"{verb} Notion page: {m[sid]}"
