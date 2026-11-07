import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "telegram_skill_review",
    PLUGIN_ROOT / "__init__.py",
    submodule_search_locations=[str(PLUGIN_ROOT)],
)
assert SPEC is not None and SPEC.loader is not None
plugin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plugin
SPEC.loader.exec_module(plugin)


def pending_record(content: str = "# Demo\n\nBody\n") -> dict:
    return {
        "id": "abcd1234",
        "subsystem": "skills",
        "action": "create",
        "summary": "create 'demo'",
        "origin": "background_review",
        "created_at": 1.0,
        "payload": {"action": "create", "name": "demo", "content": content},
    }


def test_split_markdown_preserves_exact_content_and_limit():
    content = "---\nname: demo\n---\n\n# Heading\n\n" + ("paragraph text\n\n" * 80)

    parts = plugin.split_markdown(content, max_chars=240)

    assert "".join(parts) == content
    assert all(len(part) <= 240 for part in parts)
    assert len(parts) > 1


def test_split_markdown_divides_an_oversized_line_without_data_loss():
    content = "x" * 601

    parts = plugin.split_markdown(content, max_chars=200)

    assert [len(part) for part in parts] == [200, 200, 200, 1]
    assert "".join(parts) == content


def test_render_rejects_a_message_limit_that_cannot_hold_the_header():
    try:
        plugin.render_proposal_messages(pending_record("body"), max_chars=60)
    except ValueError as exc:
        assert "max_message_chars" in str(exc)
    else:
        raise AssertionError("expected an invalid message budget to fail")


def test_store_claims_each_pending_record_once(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    path = pending_dir / "abcd1234.json"
    path.write_text(json.dumps(pending_record()), encoding="utf-8")
    store = plugin.ReviewStore(tmp_path)

    first = store.claim_for_delivery("abcd1234")
    second = store.claim_for_delivery("abcd1234")

    assert first["review"]["delivery_status"] == "delivering"
    assert second is None


def test_store_records_partial_delivery_for_restart_resume(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    path = pending_dir / "abcd1234.json"
    path.write_text(json.dumps(pending_record()), encoding="utf-8")
    store = plugin.ReviewStore(tmp_path)

    store.claim_for_delivery("abcd1234")
    store.record_topic("abcd1234", chat_id="17", thread_id="29")
    store.record_content_message("abcd1234", message_id="41")

    record = store.get_pending("abcd1234")
    assert record["review"]["thread_id"] == "29"
    assert record["review"]["content_message_ids"] == ["41"]


def test_delivery_failure_sets_a_future_retry_time(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    (pending_dir / "abcd1234.json").write_text(json.dumps(pending_record()), encoding="utf-8")
    store = plugin.ReviewStore(tmp_path)
    store.record_delivery_failure("abcd1234", "network")

    record = store.get_pending("abcd1234")
    assert record["review"]["next_attempt_at"] > record["review"]["failed_at"]
    assert store.claim_for_delivery("abcd1234") is None


def test_pending_listing_ignores_invalid_record_names(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    (pending_dir / "bad name.json").write_text("{}", encoding="utf-8")
    (pending_dir / "abcd1234.json").write_text(json.dumps(pending_record()), encoding="utf-8")

    assert plugin.ReviewStore(tmp_path).list_pending_ids() == ["abcd1234"]


def test_render_messages_keeps_skill_content_after_status_updates():
    record = pending_record("# Demo\n\n" + ("body\n" * 100))
    record["profile"] = "primary-profile"

    messages = plugin.render_proposal_messages(record, max_chars=180)

    assert "".join(message.source for message in messages) == record["payload"]["content"]
    assert all(len(message.markdown) <= 180 for message in messages)
    assert all("Part" in message.markdown for message in messages)
    assert all("**Profile:** `primary-profile`" in message.markdown for message in messages)


class FakeBot:
    def __init__(self):
        self.calls = []

    async def create_forum_topic(self, **kwargs):
        self.calls.append(("create_forum_topic", kwargs))
        return SimpleNamespace(message_thread_id=29)

    async def do_api_request(self, method, api_kwargs):
        self.calls.append((method, api_kwargs))
        return {"message_id": 40 + len([c for c in self.calls if c[0] == method])}

    async def edit_message_reply_markup(self, **kwargs):
        self.calls.append(("edit_message_reply_markup", kwargs))

    async def edit_forum_topic(self, **kwargs):
        self.calls.append(("edit_forum_topic", kwargs))


class FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.from_user = SimpleNamespace(id=88, first_name="Reviewer")
        self.message = SimpleNamespace(
            chat_id=17,
            message_thread_id=29,
            message_id=44,
            chat=SimpleNamespace(type="private"),
        )
        self.answers = []

    async def answer(self, text=None):
        self.answers.append(text)


class FakeAdapter:
    def __init__(self):
        self.chat_types = []

    def _is_callback_user_authorized(self, user_id, **kwargs):
        self.chat_types.append(kwargs.get("chat_type"))
        return user_id == "88"


def test_delivery_creates_one_topic_and_keeps_all_skill_parts(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    path = pending_dir / "abcd1234.json"
    path.write_text(json.dumps(pending_record("# Demo\n\n" + "body\n" * 100)), encoding="utf-8")
    bot = FakeBot()
    store = plugin.ReviewStore(tmp_path)
    service = plugin.TelegramSkillReviewService(
        bot=bot,
        adapter=FakeAdapter(),
        store=store,
        chat_id="17",
        max_message_chars=180,
        profile_name="primary-profile",
    )

    asyncio.run(service.deliver_pending("abcd1234"))

    record = store.get_pending("abcd1234")
    assert record["review"]["delivery_status"] == "sent"
    assert len(record["review"]["content_message_ids"]) > 1
    assert record["review"]["control_message_id"]
    rich_calls = [call for call in bot.calls if call[0] == "sendRichMessage"]
    assert all(call[1]["message_thread_id"] == 29 for call in rich_calls)
    assert "primary-profile" in bot.calls[0][1]["name"]
    assert "**Profile:** `primary-profile`" in rich_calls[0][1]["rich_message"]["markdown"]
    assert store.get_pending("abcd1234")["profile"] == "primary-profile"
    callbacks = [
        button["callback_data"]
        for button in rich_calls[-1][1]["reply_markup"]["inline_keyboard"][0]
    ]
    assert callbacks == ["skillreview:a:primary-profile:abcd1234", "skillreview:r:primary-profile:abcd1234"]


def test_delivery_leaves_foreground_records_available_for_manual_review(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["origin"] = "foreground"
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
    )

    asyncio.run(service.deliver_pending("abcd1234"))

    saved = service.store.get_pending("abcd1234")
    assert saved.get("review") is None


def test_approve_callback_applies_without_llm_and_preserves_telegram_messages(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41", "42"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    bot = FakeBot()
    applied = []
    service = plugin.TelegramSkillReviewService(
        bot=bot,
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        apply_pending=lambda payload: applied.append(payload) or {"success": True},
    )
    query = FakeQuery("skillreview:a:default:abcd1234")

    asyncio.run(service.handle_callback(query))

    assert applied == [record["payload"]]
    assert not (pending_dir / "abcd1234.json").exists()
    assert any(call[0] == "edit_message_reply_markup" for call in bot.calls)
    assert not any(call[0] == "delete_message" for call in bot.calls)
    ledger = [json.loads(line) for line in (tmp_path / "plugin-data" / "telegram-skill-review" / "review-ledger.jsonl").read_text().splitlines()]
    assert ledger[-1]["decision"] == "approved"
    assert ledger[-1]["content_message_ids"] == ["41", "42"]


def test_approve_is_durable_before_telegram_status_failure(tmp_path):
    class StatusFailureBot(FakeBot):
        async def edit_message_reply_markup(self, **kwargs):
            raise RuntimeError("Telegram unavailable")

    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    applied = []
    service = plugin.TelegramSkillReviewService(
        bot=StatusFailureBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        apply_pending=lambda payload: applied.append(payload) or {"success": True},
    )

    try:
        asyncio.run(service.handle_callback(FakeQuery("skillreview:a:default:abcd1234")))
    except RuntimeError:
        pass

    assert len(applied) == 1
    saved = json.loads((pending_dir / "abcd1234.json").read_text(encoding="utf-8"))
    assert saved["review"]["decision_status"] == "approved"


def test_callback_uses_the_actual_telegram_chat_type(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    adapter = FakeAdapter()
    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(), adapter=adapter, store=plugin.ReviewStore(tmp_path), chat_id="17"
    )
    query = FakeQuery("skillreview:r:default:abcd1234")
    query.message.chat.type = "supergroup"

    asyncio.run(service.handle_callback(query))

    assert adapter.chat_types == ["supergroup"]


def test_reject_callback_removes_pending_and_reports_status(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    bot = FakeBot()
    service = plugin.TelegramSkillReviewService(
        bot=bot,
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
    )
    query = FakeQuery("skillreview:r:default:abcd1234")

    asyncio.run(service.handle_callback(query))

    assert not (pending_dir / "abcd1234.json").exists()
    assert query.answers[0] == "Rejecting proposal…"
    status_calls = [call for call in bot.calls if call[0] == "sendRichMessage"]
    assert "Rejected" in status_calls[-1][1]["rich_message"]["markdown"]


def test_callback_refuses_a_different_source_profile(tmp_path):
    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="secondary-profile",
    )
    query = FakeQuery("skillreview:a:primary-profile:abcd1234")

    asyncio.run(service.handle_callback(query))

    assert query.answers == []


def test_source_profile_names_default_to_plugin_profile():
    class Context:
        profile_name = "primary-profile"

        @staticmethod
        def get_config(key, default=None):
            return default

    assert plugin.source_profile_names(Context()) == ["primary-profile"]


def test_source_profile_names_accept_multiple_profiles():
    class Context:
        profile_name = "primary-profile"

        @staticmethod
        def get_config(key, default=None):
            return (
                ["primary-profile", "secondary-profile", "primary-profile"]
                if key == "source_profiles"
                else default
            )

    assert plugin.source_profile_names(Context()) == ["primary-profile", "secondary-profile"]


def test_source_profile_home_resolves_from_default_home(tmp_path):
    default_home = tmp_path / ".hermes"
    (default_home / "profiles" / "secondary-profile").mkdir(parents=True)

    assert plugin.source_profile_home(default_home, "default", "secondary-profile") == (
        default_home / "profiles" / "secondary-profile"
    )


def test_source_profile_home_resolves_named_profile_sibling(tmp_path):
    primary_home = tmp_path / ".hermes" / "profiles" / "primary-profile"
    primary_home.mkdir(parents=True)
    (primary_home.parent / "secondary-profile").mkdir()

    assert plugin.source_profile_home(
        primary_home, "primary-profile", "secondary-profile"
    ) == primary_home.parent / "secondary-profile"


def test_source_profile_home_rejects_an_unknown_profile(tmp_path):
    primary_home = tmp_path / ".hermes" / "profiles" / "primary-profile"
    primary_home.mkdir(parents=True)

    try:
        plugin.source_profile_home(primary_home, "primary-profile", "missing")
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("expected an unknown source profile to fail")


def test_delivery_rejects_a_record_bound_to_another_profile(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["profile"] = "secondary-profile"
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="primary-profile",
    )

    asyncio.run(service.deliver_pending("abcd1234"))

    saved = service.store.get_pending("abcd1234")
    assert saved["profile"] == "secondary-profile"
    assert saved["review"]["delivery_status"] == "retry"
    assert "profile" in saved["review"]["last_error"].lower()


def test_approved_decision_survives_telegram_failure_without_reapplying(tmp_path):
    class OneFailureBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.fail_markup_once = True

        async def edit_message_reply_markup(self, **kwargs):
            if self.fail_markup_once:
                self.fail_markup_once = False
                raise RuntimeError("Telegram unavailable")
            await super().edit_message_reply_markup(**kwargs)

    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["profile"] = "secondary-profile"
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    applied = []
    bot = OneFailureBot()
    service = plugin.TelegramSkillReviewService(
        bot=bot,
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="secondary-profile",
        apply_pending=lambda payload: applied.append(payload) or {"success": True},
    )

    asyncio.run(service.handle_callback(FakeQuery("skillreview:a:secondary-profile:abcd1234")))
    saved = service.store.get_pending("abcd1234")
    assert saved["review"]["decision_status"] == "approved"
    assert len(applied) == 1

    asyncio.run(service.scan_once())

    assert len(applied) == 1
    assert not (pending_dir / "abcd1234.json").exists()


def test_duplicate_approval_does_not_apply_an_approved_record_again(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["profile"] = "secondary-profile"
    record["review"] = {
        "delivery_status": "sent",
        "decision_status": "approved",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    applied = []
    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="secondary-profile",
        apply_pending=lambda payload: applied.append(payload) or {"success": True},
    )

    asyncio.run(service.handle_callback(FakeQuery("skillreview:a:secondary-profile:abcd1234")))

    assert applied == []


def test_apply_exception_releases_the_decision_for_retry(tmp_path):
    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["profile"] = "secondary-profile"
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")

    def fail(_payload):
        raise RuntimeError("apply failed")

    service = plugin.TelegramSkillReviewService(
        bot=FakeBot(),
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="secondary-profile",
        apply_pending=fail,
    )

    try:
        asyncio.run(service.handle_callback(FakeQuery("skillreview:a:secondary-profile:abcd1234")))
    except RuntimeError as exc:
        assert str(exc) == "apply failed"
    else:
        raise AssertionError("expected the apply failure to propagate")

    saved = service.store.get_pending("abcd1234")
    assert "decision_status" not in saved["review"]


def test_concurrent_presentation_writes_one_status_and_one_ledger_entry(tmp_path):
    class YieldingBot(FakeBot):
        async def edit_message_reply_markup(self, **kwargs):
            await asyncio.sleep(0)
            await super().edit_message_reply_markup(**kwargs)

        async def do_api_request(self, method, api_kwargs):
            await asyncio.sleep(0)
            return await super().do_api_request(method, api_kwargs)

    pending_dir = tmp_path / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["profile"] = "secondary-profile"
    record["review"] = {
        "delivery_status": "sent",
        "decision_status": "approved",
        "telegram_user_id": "88",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    bot = YieldingBot()
    service = plugin.TelegramSkillReviewService(
        bot=bot,
        adapter=FakeAdapter(),
        store=plugin.ReviewStore(tmp_path),
        chat_id="17",
        profile_name="secondary-profile",
    )

    async def present_twice():
        await asyncio.gather(service._finish_presentation(record), service._finish_presentation(record))

    asyncio.run(present_twice())

    status_calls = [call for call in bot.calls if call[0] == "sendRichMessage"]
    ledger = (tmp_path / "plugin-data" / "telegram-skill-review" / "review-ledger.jsonl")
    assert len(status_calls) == 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_review_ledger_is_private(tmp_path):
    store = plugin.ReviewStore(tmp_path)
    record = pending_record()
    record["review"] = {"content_message_ids": []}
    store.finalize(record, decision="rejected", telegram_user_id="88", status_message_id="")

    assert store.data_dir.stat().st_mode & 0o777 == 0o700
    assert store.ledger_path.stat().st_mode & 0o777 == 0o600


class FakeContext:
    def __init__(self, config: dict, profile_name: str = "default"):
        self.config = config
        self.profile_name = profile_name
        self.platform_handlers = []
        self.spawned = []

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_platform_handler(self, platform, factory):
        self.platform_handlers.append((platform, factory))

    def spawn_task(self, coro, *, name=None):
        coro.close()
        self.spawned.append(name)


class FakeCallbackQueryHandler:
    def __init__(self, callback, pattern):
        self.callback = callback
        self.pattern = pattern


class FakeApplication:
    def __init__(self):
        self.bot = FakeBot()
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)


def install_host_stubs(monkeypatch, home: Path, env: dict | None = None):
    from types import ModuleType

    constants = ModuleType("hermes_constants")
    constants.get_hermes_home = lambda: home
    secret_scope = ModuleType("agent.secret_scope")

    class UnscopedSecretError(RuntimeError):
        pass

    secret_scope.UnscopedSecretError = UnscopedSecretError
    secret_scope.get_secret_str = lambda name, default="": (env or {}).get(name, default)
    telegram_ext = ModuleType("telegram.ext")
    telegram_ext.CallbackQueryHandler = FakeCallbackQueryHandler
    for name, module in {
        "hermes_constants": constants,
        "agent": ModuleType("agent"),
        "agent.secret_scope": secret_scope,
        "telegram": ModuleType("telegram"),
        "telegram.ext": telegram_ext,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_register_wires_one_telegram_handler_and_one_scanner_per_profile(tmp_path, monkeypatch):
    install_host_stubs(monkeypatch, tmp_path)
    (tmp_path / "profiles" / "worker").mkdir(parents=True)
    ctx = FakeContext({"chat_id": "17", "source_profiles": ["default", "worker"]})

    plugin.register(ctx)
    [(platform, factory)] = ctx.platform_handlers
    application = FakeApplication()
    factory(application, FakeAdapter())

    assert platform == "telegram"
    [handler] = application.handlers
    assert re.fullmatch(handler.pattern, "skillreview:a:worker:abcd1234")
    assert re.fullmatch(handler.pattern, "skillreview:r:default:abcd1234")
    assert not re.fullmatch(handler.pattern, "skillreview:a:stranger:abcd1234")
    assert ctx.spawned == [
        "telegram-skill-review-scanner:default",
        "telegram-skill-review-scanner:worker",
    ]


def test_register_routes_a_button_press_to_the_source_profile(tmp_path, monkeypatch):
    install_host_stubs(monkeypatch, tmp_path)
    worker_home = tmp_path / "profiles" / "worker"
    pending_dir = worker_home / "pending" / "skills"
    pending_dir.mkdir(parents=True)
    record = pending_record()
    record["review"] = {
        "delivery_status": "sent",
        "chat_id": "17",
        "thread_id": "29",
        "content_message_ids": ["41"],
        "control_message_id": "44",
    }
    (pending_dir / "abcd1234.json").write_text(json.dumps(record), encoding="utf-8")
    ctx = FakeContext({"chat_id": "17", "source_profiles": ["worker"]})
    plugin.register(ctx)
    application = FakeApplication()
    ctx.platform_handlers[0][1](application, FakeAdapter())
    query = FakeQuery("skillreview:r:worker:abcd1234")

    asyncio.run(application.handlers[0].callback(SimpleNamespace(callback_query=query), None))

    assert not (pending_dir / "abcd1234.json").exists()
    assert query.answers[0] == "Rejecting proposal…"


def test_register_without_chat_id_wires_nothing(tmp_path, monkeypatch):
    install_host_stubs(monkeypatch, tmp_path)
    ctx = FakeContext({})

    plugin.register(ctx)
    application = FakeApplication()
    ctx.platform_handlers[0][1](application, FakeAdapter())

    assert application.handlers == []
    assert ctx.spawned == []


def test_chat_id_falls_back_to_the_profile_scoped_home_channel(tmp_path, monkeypatch):
    install_host_stubs(monkeypatch, tmp_path, env={"TELEGRAM_HOME_CHANNEL": " 99 "})

    assert plugin._resolve_chat_id(FakeContext({})) == "99"
    assert plugin._resolve_chat_id(FakeContext({"chat_id": "17"})) == "17"


def test_chat_id_is_empty_when_the_profile_scope_is_unavailable(tmp_path, monkeypatch):
    install_host_stubs(monkeypatch, tmp_path)
    secret_scope = sys.modules["agent.secret_scope"]

    def unscoped(name, default=""):
        raise secret_scope.UnscopedSecretError(name)

    monkeypatch.setattr(secret_scope, "get_secret_str", unscoped)

    assert plugin._resolve_chat_id(FakeContext({})) == ""
