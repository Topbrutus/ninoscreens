from __future__ import annotations

from pathlib import Path

from app.chatgpt_bridge_browser import (
    ChatGPTBridgeBrowserHost,
    FakeBridgeBrowserHost,
    PROFILE_ROOT,
    CACHE_ROOT,
    STATE_ROOT,
    TARGET_CONFIG_PATH,
    TRANSPORT_KIND,
)


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
