import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "core.py"


@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for name in ("NOTION_API_KEY", "SESSION_NOTES_NOTION_DATA_SOURCE_ID"):
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location("session_notes_core", CORE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_hardcoded_notion_ids():
    import re
    uuid = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    assert not uuid.search(CORE.read_text())


def test_home_follows_hermes_home(core, tmp_path):
    assert core.HOME == str(tmp_path)
    assert core.DRAFTS.startswith(str(tmp_path))


def test_env_prefers_environment_then_dotenv(core, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text('NOTION_API_KEY="from-file"\nOTHER=1\n')
    assert core._env("NOTION_API_KEY") == "from-file"
    monkeypatch.setenv("NOTION_API_KEY", "from-env")
    assert core._env("NOTION_API_KEY") == "from-env"


def test_env_missing_file_is_none(core):
    assert core._env("NOTION_API_KEY") is None


def test_save_without_config_reports_error(core):
    ok, msg = core.save("abc", "# T\n\n- id: abc\n\n- point\n")
    assert not ok and "is not set" in msg


def test_missing_data_source_reports_error(core, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "k")
    ok, msg = core.save("abc", "# T\n\n- id: abc\n\n- point\n")
    assert not ok and "SESSION_NOTES_NOTION_DATA_SOURCE_ID" in msg


def test_save_requires_id_line(core):
    ok, msg = core.save("abc", "# T\n\n- point\n")
    assert not ok and "- id: abc" in msg


def test_save_creates_page_with_configured_data_source(core, monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "k")
    monkeypatch.setenv("SESSION_NOTES_NOTION_DATA_SOURCE_ID", "ds-123")
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"url": "https://notion.so/page-1"}).encode()

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        seen["auth"] = req.get_header("Authorization")
        return Resp()

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    ok, msg = core.save("abc", "# T\n\n- id: abc\n- topics: a, b\n\n- point\n")
    assert ok, msg
    assert seen["body"]["parent"]["data_source_id"] == "ds-123"
    assert [t["name"] for t in seen["body"]["properties"]["Topics"]["multi_select"]] == ["a", "b"]
    assert "topics:" not in seen["body"]["markdown"]
    assert seen["auth"] == "Bearer k"
    assert core.is_saved("abc")


def test_llm_without_hermes_on_path(core, monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda _: None)
    r = core._llm("do it", "text")
    assert r.returncode == 127 and "PATH" in r.stderr


def test_llm_runs_hermes_without_tools(core, monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda _: "/bin/hermes")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    core._llm("instr", "body")
    cmd = calls[0]
    assert cmd[:5] == ["/bin/hermes", "chat", "-Q", "-t", ""]
    assert cmd[-1] == "instr\n\nbody"


def test_topics_line_roundtrip(core):
    text = core.set_topics_line("# T\n\n- id: x\n\n- p\n", ["a", "b"])
    assert core.parse_topics(text) == ["a", "b"]
    assert text.splitlines()[3] == "- topics: a, b"
