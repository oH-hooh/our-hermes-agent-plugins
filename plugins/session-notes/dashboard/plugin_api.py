"""Backend for the session-notes desktop pane: /api/plugins/session-notes/*"""
import importlib.util
import os

from fastapi import APIRouter
from pydantic import BaseModel

_spec = importlib.util.spec_from_file_location(
    "session_notes_core", os.path.join(os.path.dirname(__file__), "..", "core.py"))
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)

router = APIRouter()


class Body(BaseModel):
    session_id: str
    text: str | None = None
    format: str | None = None  # one-off format override; the saved default is used if empty


@router.get("/draft")
def draft(session_id: str):
    return {"draft": core.read_draft(session_id), "saved": core.is_saved(session_id),
            "title": core.title(session_id)}


@router.post("/generate")
def generate(body: Body):
    ok, text = core.generate(body.session_id, body.format)
    return {"ok": ok, "draft": text if ok else None, "error": None if ok else text}


@router.post("/generate_new")
def generate_new(body: Body):
    ok, out = core.generate_new(body.session_id, body.text, body.format)
    return {"ok": ok, "chunk": out if ok else None, "error": None if ok else out}


@router.post("/save")
def save(body: Body):
    ok, msg = core.save(body.session_id, body.text)
    return {"ok": ok, "message": msg}


@router.post("/suggest_topics")
def suggest_topics(body: Body):
    text = body.text if body.text is not None else core.read_draft(body.session_id)
    if not text:
        return {"ok": False, "error": "No draft to tag. Summarize first."}
    ok, out = core.suggest_topics(text)
    if not ok:
        return {"ok": False, "error": out}
    return {"ok": True, "draft": core.set_topics_line(text, out), "topics": out}


class FormatBody(BaseModel):
    text: str = ""
    session_id: str | None = None
    scope: str = "session"  # "session" | "default" | "reset"


@router.get("/format")
def get_format(session_id: str | None = None):
    return {"format": core.get_format(session_id), "source": core.format_source(session_id),
            "builtin": core.DEFAULT_FORMAT}


@router.post("/format")
def set_format(body: FormatBody):
    if body.scope == "default":
        core.set_format(body.text)
    elif body.scope == "session" and body.session_id:
        core.set_session_format(body.session_id, body.text)
    elif body.scope == "reset" and body.session_id:
        core.set_session_format(body.session_id, "")
    else:
        return {"ok": False, "error": "A session is required for this action."}
    return {"ok": True, "format": core.get_format(body.session_id),
            "source": core.format_source(body.session_id)}
