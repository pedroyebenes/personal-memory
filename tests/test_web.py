from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.db import connect, init_db
from app.ingest.register import ingest_vault
from app import web
from app.web import APIError, RefreshState, _error_payload, handle_api_get, handle_api_post


def test_status_reports_config_diagnostics(tmp_path: Path) -> None:
    settings = Settings(
        vault_path=tmp_path / "missing-vault",
        database_path=tmp_path / "memory.sqlite3",
        llm_provider="invalid-provider",
    )
    connection = connect(settings.database_path)
    init_db(connection)
    try:
        status, payload = handle_api_get("/api/status", settings, RefreshState(), lambda callback: callback(connection))
    finally:
        connection.close()

    assert int(status) == 200
    assert payload["ok"] is True
    diagnostics = payload["config_diagnostics"]
    assert {item["code"] for item in diagnostics} == {"unsupported_provider", "vault_not_found"}


def test_chat_rejects_invalid_provider(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    server_settings = replace(settings)
    with_connection = lambda callback: callback(connection)

    try:
        handle_api_post("/api/chat", {"query": "What is North Star?", "provider": "not-a-provider"}, server_settings, RefreshState(), with_connection)
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_provider"


def test_chat_rejects_unavailable_provider_when_llm_requested(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    server_settings = replace(settings, llm_provider="openai", openai_api_key=None)
    with_connection = lambda callback: callback(connection)

    try:
        handle_api_post(
            "/api/chat",
            {"query": "What is North Star?", "provider": "openai", "use_llm": True},
            server_settings,
            RefreshState(),
            with_connection,
        )
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "provider_unavailable"


def test_chat_rejects_invalid_boolean_flags(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    try:
        handle_api_post(
            "/api/chat",
            {"query": "What is North Star?", "use_llm": "sometimes"},
            settings,
            RefreshState(),
            with_connection,
        )
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["error"]["code"] == "invalid_boolean"


def test_refresh_rejects_concurrent_requests(settings: Settings) -> None:
    settings.vault_path = settings.database_path.parent
    refresh_state = RefreshState()
    refresh_state.begin()
    try:
        handle_api_post("/api/refresh", {}, settings, refresh_state, lambda callback: callback)
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")
    finally:
        refresh_state.finish({"status": "completed"})

    assert int(status) == 409
    assert payload["ok"] is False
    assert payload["error"]["code"] == "refresh_in_progress"


def test_refresh_returns_structured_failure_and_tracks_last_result(settings: Settings, monkeypatch) -> None:
    settings.vault_path = settings.database_path.parent
    refresh_state = RefreshState()

    monkeypatch.setattr(web, "ingest_vault", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk full")))

    connection = connect(settings.database_path)
    init_db(connection)
    try:
        with_connection = lambda callback: callback(connection)
        try:
            handle_api_post("/api/refresh", {}, settings, refresh_state, with_connection)
        except APIError as exc:
            status = exc.status
            payload = _error_payload(exc)
        else:
            raise AssertionError("Expected APIError")
    finally:
        connection.close()

    snapshot = refresh_state.snapshot()
    assert int(status) == 500
    assert payload["error"]["code"] == "refresh_failed"
    assert snapshot["in_progress"] is False
    assert snapshot["last_result"]["status"] == "failed"
    assert snapshot["last_result"]["error"] == "disk full"


def test_search_rejects_invalid_top_k(settings: Settings) -> None:
    try:
        handle_api_get("/api/search?query=test&top_k=abc", settings, RefreshState(), lambda callback: callback)
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_top_k"
