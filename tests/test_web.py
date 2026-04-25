from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.config import Settings
from app.db import connect, init_db
from app.ingest.register import ingest_vault
from app import web
from app.web import APIError, RefreshState, _error_payload, _read_web_asset, handle_api_get, handle_api_post


def test_web_assets_are_split_and_linked() -> None:
    html = _read_web_asset("index.html")
    viz_html = _read_web_asset("viz.html")
    css = _read_web_asset("styles.css")
    js = _read_web_asset("app.js")

    assert '<link rel="stylesheet" href="/static/styles.css">' in html
    assert '<script src="/static/app.js"></script>' in html
    assert "HTML_PAGE" not in html
    assert 'id="top-k"' in html
    assert ".layout" in css
    assert "function renderAnswerWorkspaces" in js
    assert "top_k: readTopK()" in js
    assert 'id="viz-search"' in viz_html
    assert 'id="label-lines"' in viz_html


def test_viz_api_returns_named_clusters(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get("/api/viz", settings, RefreshState(), with_connection)

    assert int(status) == 200
    assert payload["points"]
    assert payload["clusters"]
    assert payload["clusters"][0]["name"]
    assert payload["clusters"][0]["size"] > 0


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
    assert payload["top_k"] == 5
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


def test_refresh_rebuilds_concepts_for_skipped_documents(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()
    settings.vault_path = fixture_vault
    refresh_state = RefreshState()
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_post("/api/refresh", {}, settings, refresh_state, with_connection)

    assert int(status) == 200
    assert payload["skipped"] == 3
    assert payload["concepts"]["entities"] > 0
    assert payload["concepts"]["mentions"] > 0


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


def test_search_accepts_metadata_filters(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get(
        "/api/search?query=launch%20plan&tags=project&aliases=north%20star",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["filters"]["tags"] == ["project"]
    assert payload["filters"]["aliases"] == ["north star"]
    assert payload["results"]
    assert all("project-note.md" in item["source_path"] for item in payload["results"])


def test_search_accepts_rerank_flag(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get(
        "/api/search?query=North%20Star&rerank=true",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["rerank"] is True
    assert payload["results"]
    assert any(item["rerank_score"] > 0 for item in payload["results"])


def test_search_accepts_concept_boost_flag(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get(
        "/api/search?query=North%20Star&concept_boost=true",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["concept_boost"] is True
    assert payload["results"]
    assert any("concept_boost" in item["score_explanation"] for item in payload["results"])


def test_search_filters_by_modified_date_range(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    connection.execute(
        """
        UPDATE documents
        SET last_modified = CASE
            WHEN source_path LIKE '%project-note.md' THEN '2024-02-15T12:00:00+00:00'
            ELSE '2022-01-01T00:00:00+00:00'
        END
        """
    )
    connection.commit()
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get(
        "/api/search?query=launch%20plan&date_from=2024-01-01&date_to=2024-12-31",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["filters"]["date_from"] == "2024-01-01T00:00:00+00:00"
    assert payload["filters"]["date_to"] == "2024-12-31T23:59:59+00:00"
    assert payload["results"]
    assert all("project-note.md" in item["source_path"] for item in payload["results"])


def test_search_rejects_invalid_date_range(settings: Settings) -> None:
    try:
        handle_api_get("/api/search?query=test&date_from=2025-01-01&date_to=2024-01-01", settings, RefreshState(), lambda callback: callback)
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["error"]["code"] == "invalid_filter"


def test_chat_response_includes_provider_model_and_filters(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_post(
        "/api/chat",
        {
            "query": "What is North Star?",
            "filters": {"tags": ["project"], "date_from": "2000-01-01"},
            "provider": "ollama",
        },
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["provider"] == "ollama"
    assert "model" in payload
    assert payload["filters"]["tags"] == ["project"]
    assert payload["filters"]["date_from"] == "2000-01-01T00:00:00+00:00"
    assert payload["sources"]
    assert "source_ref" in payload["sources"][0]


def test_chat_accepts_rerank_flag(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_post(
        "/api/chat",
        {
            "query": "What is North Star?",
            "rerank": True,
        },
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["rerank"] is True
    assert payload["sources"]
    assert any(source["rerank_score"] > 0 for source in payload["sources"])


def test_concepts_api_lists_details_and_refreshes(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_get(
        "/api/concepts?search=north&limit=10",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["concepts"]
    project = next(item for item in payload["concepts"] if item["normalized_key"] == "project north star")

    status, detail = handle_api_get(
        f"/api/concepts/{project['id']}",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert detail["mentions"]
    assert detail["documents"]

    connection.execute("DELETE FROM entity_mentions")
    connection.execute("DELETE FROM entities")
    connection.commit()

    status, refreshed = handle_api_post(
        "/api/concepts/refresh",
        {},
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert refreshed["entities"] > 0
    assert refreshed["mentions"] > 0


def test_concepts_api_filters_by_entity_type(connection, tmp_path: Path, settings: Settings) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "chapter.md").write_text(
        "# CAPÍTULO XL\n\nBody mentions [[Project North Star]].\n\n## Research Agenda\n\nNotes.",
        encoding="utf-8",
    )
    ingest_vault(connection, vault, settings)
    with_connection = lambda callback: callback(connection)

    status, concepts = handle_api_get(
        "/api/concepts?type=concept&limit=50",
        settings,
        RefreshState(),
        with_connection,
    )
    status_structures, structures = handle_api_get(
        "/api/concepts?type=structure&limit=50",
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert concepts["type"] == "concept"
    assert "capítulo xl" not in {item["normalized_key"] for item in concepts["concepts"]}
    assert int(status_structures) == 200
    assert structures["type"] == "structure"
    assert "capítulo xl" in {item["normalized_key"] for item in structures["concepts"]}


def test_concepts_api_rejects_invalid_entity_type(settings: Settings) -> None:
    try:
        handle_api_get(
            "/api/concepts?type=invalid",
            settings,
            RefreshState(),
            lambda callback: callback,
        )
    except APIError as exc:
        status = exc.status
        payload = _error_payload(exc)
    else:
        raise AssertionError("Expected APIError")

    assert int(status) == 400
    assert payload["error"]["code"] == "invalid_concept_type"


def test_chat_treats_null_path_prefix_as_no_filter(connection, fixture_vault: Path, settings: Settings) -> None:
    ingest_vault(connection, fixture_vault, settings)
    with_connection = lambda callback: callback(connection)

    status, payload = handle_api_post(
        "/api/chat",
        {
            "query": "What is North Star?",
            "filters": {"tags": [], "aliases": [], "path_prefix": None, "date_from": None, "date_to": None},
        },
        settings,
        RefreshState(),
        with_connection,
    )

    assert int(status) == 200
    assert payload["filters"]["path_prefix"] is None
    assert payload["sources"]
    assert "retrieval returned no evidence" not in payload["warnings"]
