from __future__ import annotations

from pathlib import Path

from app.chatgpt_bridge_browser import (
    ChatGPTBridgeBrowserHost,
    FakeBridgeBrowserHost,
    PROFILE_ROOT,
    CACHE_ROOT,
    STATE_ROOT,
    TARGET_CONFIG_PATH,
    TARGET_HISTORY_PATH,
    TRANSPORT_KIND,
    CHATGPT_DOM_PROBE_JS,
    decode_javascript_diagnostic_result,
    _browser_state_payload,
    _choose_start_url,
    _is_useful_browser_state_url,
)


class _DummySignal:
    def __init__(self) -> None:
        self.payloads = []

    def emit(self, payload) -> None:
        self.payloads.append(payload)


def test_bridge_paths_are_d_only() -> None:
    for path in (PROFILE_ROOT, CACHE_ROOT, STATE_ROOT, TARGET_CONFIG_PATH):
        assert str(path).startswith("D:\\")


def test_fake_host_ready_status_has_no_pages_dependency() -> None:
    host = FakeBridgeBrowserHost()
    status = host.status_snapshot()
    assert status["arena_status"] == "ARENA_ONLINE"
    assert status["arena_reason"] == "READY"
    assert status["transport"] == TRANSPORT_KIND
    assert status["visible_page_dependency"] == "NONE"


def test_fake_host_target_not_configured() -> None:
    status = FakeBridgeBrowserHost(target_configured=False).status_snapshot()
    assert status["arena_status"] == "ARENA_DEGRADED"
    assert status["arena_reason"] == "BRIDGE_TARGET_NOT_CONFIGURED"
    assert status["target"] == "NOT_CONFIGURED"


def test_fake_host_login_required() -> None:
    status = FakeBridgeBrowserHost(session_authenticated=False).status_snapshot()
    assert status["arena_status"] == "ARENA_DEGRADED"
    assert status["arena_reason"] == "BRIDGE_LOGIN_REQUIRED"
    assert status["session"] == "LOGIN_REQUIRED"


def test_fake_host_composer_absent() -> None:
    status = FakeBridgeBrowserHost(composer_detected=False).status_snapshot()
    assert status["arena_status"] == "ARENA_DEGRADED"
    assert status["arena_reason"] == "BRIDGE_COMPOSER_NOT_DETECTED"
    assert status["composer"] == "NOT_DETECTED"


def test_page_identity_survives_view_changes() -> None:
    host = FakeBridgeBrowserHost()
    first = host.page_identity
    for _view in ("Pages", "Terminal", "Arena", "ChatGPT"):
        assert host.page_identity == first


def test_transport_contract_excludes_uiautomation_and_pages_tiles() -> None:
    status = FakeBridgeBrowserHost().status_snapshot()
    assert status["transport"] == "DEDICATED_BACKGROUND_WEBVIEW"
    assert status["visible_page_dependency"] == "NONE"
    assert "UIAUTOMATION" not in status["transport"]


def test_static_validation_rejects_external_domain() -> None:
    host = FakeBridgeBrowserHost()
    result = host.apply_target_url("https://example.com/c/abc")
    assert result["status"] == "INVALID_URL"
    assert host.applied_urls == []


def test_static_validation_rejects_library_route() -> None:
    host = FakeBridgeBrowserHost()
    result = host.apply_target_url("https://chatgpt.com/library")
    assert result["status"] == "UNSUPPORTED_ROUTE"
    assert host.applied_urls == []


def test_use_current_url_does_not_apply_target() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("https://chatgpt.com/c/new-target")
    assert host.current_url() == "https://chatgpt.com/c/new-target"
    assert host.target_url() == ""
    assert host.applied_urls == []


def test_apply_valid_target_normalizes_and_applies_without_send() -> None:
    host = FakeBridgeBrowserHost()
    result = host.apply_target_url("https://chatgpt.com/c/new-target/?model=gpt-5")
    assert result["status"] == "VALID"
    assert host.target_url() == "https://chatgpt.com/c/new-target?model=gpt-5"
    assert host.sends == 0


def test_login_required_blocks_apply() -> None:
    host = FakeBridgeBrowserHost(session_authenticated=False)
    result = host.apply_target_url("https://chatgpt.com/c/new-target")
    assert result["status"] == "LOGIN_REQUIRED"
    assert host.applied_urls == []


def test_composer_absent_blocks_apply() -> None:
    host = FakeBridgeBrowserHost(composer_detected=False)
    result = host.apply_target_url("https://chatgpt.com/c/new-target")
    assert result["status"] == "COMPOSER_NOT_DETECTED"
    assert host.applied_urls == []


def test_clear_target_keeps_profile_contract() -> None:
    host = FakeBridgeBrowserHost()
    host.clear_target()
    assert host.target_url() == ""
    assert host.cleared is True
    assert str(PROFILE_ROOT).startswith("D:\\")


def test_conversation_id_observable_from_url() -> None:
    assert ChatGPTBridgeBrowserHost._conversation_id("https://chatgpt.com/c/abc-123?model=gpt-5") == "abc-123"


class _ProbeHost(ChatGPTBridgeBrowserHost):
    def __init__(self) -> None:
        pass

    def target_url(self) -> str:
        return ""

    @property
    def host_id(self) -> str:
        return "chatgpt-bridge-primary"

    def current_url(self) -> str:
        return "https://chatgpt.com/c/fixture"

    def ensure_view_bound(self) -> dict:
        return {"same_page_object": True}

    def restore_or_start(self) -> dict:
        return {"restored": False, "url": self.current_url()}

    def _write_live_diagnostic_event(self, *args, **kwargs) -> None:
        self.logged_events.append((args, kwargs))

    def _run_dom_diagnostic(self, generation, callback) -> None:
        self.run_count += 1
        callback(self.next_probe)


def _host_for_probe() -> ChatGPTBridgeBrowserHost:
    host = ChatGPTBridgeBrowserHost.__new__(_ProbeHost)
    host._target = {}
    host._last_error = ""
    host._current_cycle = "NONE"
    host._last_status = __import__("app.chatgpt_bridge_browser", fromlist=["BridgeBrowserStatus"]).BridgeBrowserStatus(browser="ONLINE")
    host._navigation_epoch = 0
    host._diagnostic_generation = 0
    host._live_diagnostic_in_progress = False
    host.status_changed = _DummySignal()
    host.logged_events = []
    host.run_count = 0
    host.next_probe = _probe("AUTHENTICATED", "DETECTED")
    return host


def _probe(session: str, composer: str, *, selector: str | None = "#prompt-textarea") -> dict:
    return {
        "url": "https://chatgpt.com/c/fixture",
        "ready_state": "complete",
        "session": {
            "state": session,
            "evidence": [{"kind": "main", "selector": "main", "visible": True}],
            "url": "https://chatgpt.com/c/fixture",
            "ready_state": "complete",
            "timestamp": "2026-07-19T00:00:00Z",
        },
        "composer": {
            "state": composer,
            "selector": selector,
            "element_kind": "textarea" if selector and "textarea" in selector else "contenteditable",
            "visible": composer == "DETECTED",
            "enabled": composer == "DETECTED",
            "editable": composer == "DETECTED",
            "ready_state": "complete",
            "candidate_count": 1 if selector else 0,
            "timestamp": "2026-07-19T00:00:00Z",
        },
        "generation": "IDLE",
    }


def test_authenticated_textarea_probe_is_detected() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "DETECTED", selector="textarea[data-testid='prompt-textarea']"),
    )
    assert status.session == "AUTHENTICATED"
    assert status.composer == "DETECTED"


def test_authenticated_contenteditable_probe_is_detected() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "DETECTED", selector="[contenteditable='true'][role='textbox']"),
    )
    assert status.session == "AUTHENTICATED"
    assert status.composer == "DETECTED"


def test_lexical_composer_selector_supported() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "DETECTED", selector="div[contenteditable='true'][data-lexical-editor='true']"),
    )
    assert status.composer == "DETECTED"


def test_login_page_is_login_required_without_composer() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("LOGIN_REQUIRED", "NOT_DETECTED", selector=None),
    )
    assert status.session == "LOGIN_REQUIRED"
    assert status.composer == "NOT_DETECTED"


def test_authenticated_without_composer_is_not_login_required() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "NOT_DETECTED", selector=None),
    )
    assert status.session == "AUTHENTICATED"
    assert status.composer == "NOT_DETECTED"


def test_loading_states_are_separate() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("SESSION_LOADING", "LOADING", selector=None),
    )
    assert status.session == "SESSION_LOADING"
    assert status.composer == "LOADING"


def test_sidebar_false_positive_not_selected_fixture() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "NOT_DETECTED", selector=None),
    )
    assert status.composer != "DETECTED"


def test_double_apply_is_blocked_while_validation_runs() -> None:
    host = FakeBridgeBrowserHost()
    host.validation_in_progress = True
    result = host.apply_target_url("https://chatgpt.com/c/new-target")
    assert result["status"] == "VALIDATION_IN_PROGRESS"
    assert host.applied_urls == []


def test_diagnostic_status_contains_no_sensitive_content() -> None:
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "DETECTED"),
    ).__dict__
    serialized = str(status).lower()
    assert "cookie" not in serialized
    assert "token" not in serialized
    assert "message text" not in serialized
    assert "composer content" not in serialized


def test_refresh_loaded_page_runs_without_new_load_finished() -> None:
    host = _host_for_probe()
    seen = []
    host.refresh_status(seen.append)
    assert host.run_count == 1
    assert seen[-1]["session"] == "AUTHENTICATED"
    assert seen[-1]["composer"] == "DETECTED"


def test_successful_refresh_clears_old_error() -> None:
    host = _host_for_probe()
    host._last_error = "TARGET_PAGE_LOADING_TIMEOUT"
    seen = []
    host.refresh_status(seen.append)
    assert seen[-1]["last_error"] == ""
    assert host.status_snapshot()["last_error"] == ""


def test_refresh_does_not_configure_target() -> None:
    host = _host_for_probe()
    seen = []
    host.refresh_status(seen.append)
    assert seen[-1]["session"] == "AUTHENTICATED"
    assert seen[-1]["composer"] == "DETECTED"
    assert seen[-1]["target"] == "NOT_CONFIGURED"
    assert seen[-1]["validation_status"] == "NOT_TESTED"


def test_refresh_javascript_failure_is_not_login_required() -> None:
    host = _host_for_probe()
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        host,
        {"ok": False, "error": "JAVASCRIPT_EVALUATION_FAILED", "url": "https://chatgpt.com/c/fixture", "ready_state": "complete"},
    )
    assert status.session != "LOGIN_REQUIRED"


def test_refresh_double_click_fake_has_single_active_call() -> None:
    host = FakeBridgeBrowserHost()
    host.refresh_status(lambda _status: None)
    host.refresh_status(lambda _status: None)
    assert host.refresh_calls == 2


def test_restore_same_page_object_identity() -> None:
    host = FakeBridgeBrowserHost()
    identity = host.ensure_view_bound()
    assert identity["same_page_object"] is True
    assert identity["host_page_object_id"] == identity["visible_view_page_object_id"]


def test_return_preserves_same_page_and_url() -> None:
    host = FakeBridgeBrowserHost()
    first = host.technical_identity()
    host.set_current_url("https://chatgpt.com/c/return-fixture")
    restored = host.restore_or_start()
    assert restored["restored"] is False
    assert host.current_url() == "https://chatgpt.com/c/return-fixture"
    assert host.technical_identity()["host_page_object_id"] == first["host_page_object_id"]


def test_tab_switch_preserves_bridge_page() -> None:
    host = FakeBridgeBrowserHost()
    host.set_current_url("https://chatgpt.com/c/tab-fixture")
    page_id = host.technical_identity()["host_page_object_id"]
    for _view in ("ChatGPT", "Terminal", "Arena", "Pages", "ChatGPT"):
        host.ensure_view_bound()
    assert host.current_url() == "https://chatgpt.com/c/tab-fixture"
    assert host.technical_identity()["host_page_object_id"] == page_id


def test_start_url_restores_browser_state_without_target() -> None:
    assert _choose_start_url("", "https://chatgpt.com/c/from-state?model=gpt-5") == "https://chatgpt.com/c/from-state"


def test_start_url_falls_back_without_state() -> None:
    assert _choose_start_url("", "") == "https://chatgpt.com/"


def test_blank_page_navigates_once_to_start_url() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("")
    host.browser_state_url = "https://chatgpt.com/c/restored"
    result = host.restore_or_start()
    assert result["restored"] is True
    assert host.current_url() == "https://chatgpt.com/c/restored"
    assert host.navigations == ["https://chatgpt.com/c/restored"]


def test_target_config_wins_over_browser_state() -> None:
    assert _choose_start_url(
        "https://chatgpt.com/c/target",
        "https://chatgpt.com/c/state",
    ) == "https://chatgpt.com/c/target"


def test_external_browser_state_url_is_rejected() -> None:
    assert _is_useful_browser_state_url("https://example.com/c/not-chatgpt") is False
    assert _choose_start_url("", "https://example.com/c/not-chatgpt") == "https://chatgpt.com/"


def test_login_browser_state_url_is_not_restored() -> None:
    assert _is_useful_browser_state_url("https://chatgpt.com/login") is False
    assert _choose_start_url("", "https://chatgpt.com/login") == "https://chatgpt.com/"


def test_browser_state_payload_has_no_secret_or_content_fields() -> None:
    payload = _browser_state_payload(
        "https://chatgpt.com/c/abc-123?temporary_token=secret#fragment",
        now="2026-07-19T00:00:00+00:00",
    )
    assert payload["last_url"] == "https://chatgpt.com/c/abc-123"
    serialized = str(payload).lower()
    assert "cookie" not in serialized
    assert "token" not in serialized
    assert "message" not in serialized


def test_restore_never_sends_or_creates_cycle() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("about:blank")
    host.restore_or_start()
    assert host.sends == 0
    assert "SEND_ATTEMPTED" not in str(host.navigations)


def test_target_test_loaded_conversation_validates_without_configuring() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("https://chatgpt.com/c/live-fixture")
    seen = []
    host.diagnostic_without_send(seen.append, "https://chatgpt.com/c/live-fixture")
    assert seen[-1]["session"] == "AUTHENTICATED"
    assert seen[-1]["composer"] == "DETECTED"
    assert seen[-1]["generation"] == "IDLE"
    assert seen[-1]["validation_status"] == "VALID"
    assert seen[-1]["target"] == "NOT_CONFIGURED"
    assert host.target_url() == ""


def test_target_test_textarea_and_contenteditable_statuses() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    seen = []
    host.diagnostic_without_send(seen.append, "https://chatgpt.com/c/textarea")
    assert seen[-1]["composer"] == "DETECTED"
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        _host_for_probe(),
        _probe("AUTHENTICATED", "DETECTED", selector="[contenteditable='true'][role='textbox']"),
    )
    assert status.composer == "DETECTED"


def test_target_test_same_url_does_not_navigate() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("https://chatgpt.com/c/same")
    host.diagnostic_without_send(lambda _status: None, "https://chatgpt.com/c/same")
    assert host.navigations == []


def test_target_test_different_url_navigates_once() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.set_current_url("https://chatgpt.com/c/old")
    host.diagnostic_without_send(lambda _status: None, "https://chatgpt.com/c/new")
    assert host.navigations == ["https://chatgpt.com/c/new"]
    assert host.current_url() == "https://chatgpt.com/c/new"


def test_javascript_probe_is_try_catch_serializable() -> None:
    assert "try {" in CHATGPT_DOM_PROBE_JS
    assert "catch (error)" in CHATGPT_DOM_PROBE_JS
    assert "JAVASCRIPT_EVALUATION_FAILED" in CHATGPT_DOM_PROBE_JS
    assert "return JSON.stringify" in CHATGPT_DOM_PROBE_JS


def test_javascript_none_result_is_invalid_not_login_required() -> None:
    host = _host_for_probe()
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        host,
        {"ok": False, "error": "JAVASCRIPT_RESULT_INVALID", "url": "https://chatgpt.com/c/fixture", "ready_state": "complete"},
    )
    assert status.session != "LOGIN_REQUIRED"


def test_javascript_exception_is_not_login_required() -> None:
    host = _host_for_probe()
    status = ChatGPTBridgeBrowserHost._diagnostic_payload_to_status(
        host,
        {"ok": False, "error": "JAVASCRIPT_EVALUATION_FAILED", "url": "https://chatgpt.com/c/fixture", "ready_state": "complete"},
    )
    assert status.session != "LOGIN_REQUIRED"


def test_target_test_double_click_has_single_active_validation() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.diagnostic_in_progress = True
    seen = []
    host.diagnostic_without_send(seen.append, "https://chatgpt.com/c/live-fixture")
    assert seen[-1]["validation_status"] == "VALIDATION_IN_PROGRESS"


def test_target_test_clears_old_error() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    seen = []
    host.diagnostic_without_send(seen.append, "https://chatgpt.com/c/live-fixture")
    assert seen[-1]["last_error"] == ""


def test_target_test_does_not_write_target_or_history() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.diagnostic_without_send(lambda _status: None, "https://chatgpt.com/c/live-fixture")
    assert host.target_json_writes == 0
    assert host.history_writes == 0
    assert str(TARGET_CONFIG_PATH).endswith("target.json")
    assert str(TARGET_HISTORY_PATH).endswith("target-history.jsonl")


def test_target_test_reads_enters_sends_no_text_and_creates_no_cycle() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    host.diagnostic_without_send(lambda _status: None, "https://chatgpt.com/c/live-fixture")
    assert host.text_read == 0
    assert host.text_entered == 0
    assert host.sends == 0
    assert host.cycles_created == 0


def test_target_test_invalid_static_url_does_not_navigate() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    seen = []
    host.diagnostic_without_send(seen.append, "https://example.com/c/nope")
    assert seen[-1]["validation_status"] == "INVALID_URL"
    assert host.navigations == []


def test_target_test_sensitive_content_absent_from_status() -> None:
    host = FakeBridgeBrowserHost(target_configured=False)
    seen = []
    host.diagnostic_without_send(seen.append, "https://chatgpt.com/c/live-fixture")
    serialized = str(seen[-1]).lower()
    assert "cookie" not in serialized
    assert "token" not in serialized
    assert "conversation text" not in serialized
    assert "composer content" not in serialized


def _canonical_js_result(**overrides) -> dict:
    payload = {
        "schema_version": 1,
        "ok": True,
        "url": "https://chatgpt.com/c/js-fixture",
        "ready_state": "complete",
        "route_kind": "CONVERSATION",
        "session_state": "AUTHENTICATED",
        "composer_state": "DETECTED",
        "generation_state": "IDLE",
        "matched_selector": "#prompt-textarea",
        "candidate_count": 1,
        "browser_host_id": "chatgpt-bridge-primary",
        "error": None,
    }
    payload.update(overrides)
    return payload


def test_decode_valid_json_string_result() -> None:
    ok, info = decode_javascript_diagnostic_result(__import__("json").dumps(_canonical_js_result()))
    assert ok is True
    assert info["session"]["state"] == "AUTHENTICATED"
    assert info["composer"]["state"] == "DETECTED"
    assert info["generation"] == "IDLE"


def test_decode_valid_dict_result() -> None:
    ok, info = decode_javascript_diagnostic_result(_canonical_js_result())
    assert ok is True
    assert info["route_kind"] == "CONVERSATION"


def test_decode_none_result() -> None:
    ok, info = decode_javascript_diagnostic_result(None)
    assert ok is False
    assert info["error"] == "JAVASCRIPT_RESULT_EMPTY"


def test_decode_malformed_json_result() -> None:
    ok, info = decode_javascript_diagnostic_result("{not-json")
    assert ok is False
    assert info["error"] == "JAVASCRIPT_RESULT_PARSE_FAILED"


def test_decode_json_array_result() -> None:
    ok, info = decode_javascript_diagnostic_result("[1,2,3]")
    assert ok is False
    assert info["error"] == "JAVASCRIPT_RESULT_INVALID_TYPE"


def test_decode_missing_key_result() -> None:
    payload = _canonical_js_result()
    payload.pop("browser_host_id")
    ok, info = decode_javascript_diagnostic_result(payload)
    assert ok is False
    assert info["error"] == "JAVASCRIPT_RESULT_SCHEMA_INVALID"


def test_decode_promise_none_simulation_not_login_required() -> None:
    ok, info = decode_javascript_diagnostic_result(None)
    assert ok is False
    assert info["error"] == "JAVASCRIPT_RESULT_EMPTY"


def test_canonical_javascript_uses_json_stringify_and_no_promise() -> None:
    assert "JSON.stringify" in CHATGPT_DOM_PROBE_JS
    assert "Promise" not in CHATGPT_DOM_PROBE_JS
    assert "async " not in CHATGPT_DOM_PROBE_JS
    assert "await " not in CHATGPT_DOM_PROBE_JS


def test_decoded_authenticated_session_composer_and_idle_generation() -> None:
    ok, info = decode_javascript_diagnostic_result(__import__("json").dumps(_canonical_js_result()))
    assert ok is True
    assert info["session"]["state"] == "AUTHENTICATED"
    assert info["composer"]["state"] == "DETECTED"
    assert info["generation"] == "IDLE"


def test_decoded_result_has_no_sensitive_content() -> None:
    ok, info = decode_javascript_diagnostic_result(__import__("json").dumps(_canonical_js_result()))
    assert ok is True
    serialized = str(info).lower()
    assert "innertext" not in serialized
    assert "innerhtml" not in serialized
    assert "cookie" not in serialized
    assert "token" not in serialized
    assert "authorization" not in serialized
