from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.db import connect, init_db
from app.ingest.register import status_summary
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question

HTML_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Personal Memory Chat</title>
    <style>
      :root {
        --bg: #f2efe8;
        --panel: rgba(255, 252, 246, 0.92);
        --ink: #1e2a22;
        --muted: #5e695f;
        --accent: #0f766e;
        --accent-2: #d97706;
        --border: rgba(30, 42, 34, 0.12);
        --shadow: 0 24px 60px rgba(27, 39, 31, 0.12);
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(217, 119, 6, 0.18), transparent 28%),
          radial-gradient(circle at top right, rgba(15, 118, 110, 0.22), transparent 30%),
          linear-gradient(180deg, #f6f3ed 0%, var(--bg) 100%);
        min-height: 100vh;
      }

      .shell {
        max-width: 1120px;
        margin: 0 auto;
        padding: 32px 20px 48px;
      }

      .header {
        display: grid;
        gap: 10px;
        margin-bottom: 24px;
      }

      .eyebrow {
        font-size: 12px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent);
      }

      h1 {
        margin: 0;
        font-size: clamp(2.2rem, 5vw, 4.2rem);
        line-height: 0.94;
        font-weight: 700;
      }

      .subhead {
        max-width: 720px;
        color: var(--muted);
        font-size: 1.05rem;
        line-height: 1.6;
      }

      .layout {
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.9fr);
        gap: 20px;
      }

      .panel {
        background: var(--panel);
        backdrop-filter: blur(14px);
        border: 1px solid var(--border);
        border-radius: 24px;
        box-shadow: var(--shadow);
      }

      .chat-panel {
        padding: 18px;
      }

      .sidebar {
        padding: 18px;
        display: grid;
        gap: 16px;
        align-content: start;
      }

      .messages {
        display: grid;
        gap: 14px;
        min-height: 420px;
        max-height: 68vh;
        overflow-y: auto;
        padding: 8px 4px 18px;
      }

      .message {
        border-radius: 18px;
        padding: 14px 16px;
        border: 1px solid var(--border);
      }

      .message.user {
        background: rgba(15, 118, 110, 0.08);
      }

      .message.assistant {
        background: rgba(255, 255, 255, 0.72);
      }

      .role {
        display: block;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--muted);
        margin-bottom: 8px;
      }

      .body {
        white-space: pre-wrap;
        line-height: 1.55;
      }

      .composer {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 12px;
        border-top: 1px solid var(--border);
        padding-top: 16px;
      }

      textarea {
        width: 100%;
        min-height: 84px;
        resize: vertical;
        border-radius: 16px;
        border: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.82);
        padding: 14px 16px;
        font: inherit;
        color: inherit;
      }

      button {
        appearance: none;
        border: 0;
        border-radius: 999px;
        background: linear-gradient(135deg, var(--accent) 0%, #155e75 100%);
        color: white;
        padding: 14px 22px;
        font: inherit;
        cursor: pointer;
        align-self: end;
      }

      button.secondary {
        background: linear-gradient(135deg, var(--accent-2) 0%, #b45309 100%);
      }

      button:disabled {
        opacity: 0.6;
        cursor: wait;
      }

      .card h2 {
        font-size: 0.95rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
        margin: 0 0 12px;
      }

      .stats, .sources, .search-results {
        display: grid;
        gap: 10px;
      }

      .stat {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        border-bottom: 1px solid var(--border);
        padding-bottom: 8px;
      }

      .source, .search-result {
        padding: 12px;
        background: rgba(255, 255, 255, 0.68);
        border-radius: 16px;
        border: 1px solid var(--border);
      }

      .source-title, .search-title {
        font-weight: 700;
        margin-bottom: 6px;
      }

      .source-meta, .search-meta {
        color: var(--muted);
        font-size: 0.88rem;
        line-height: 1.45;
        word-break: break-word;
      }

      .tool-row {
        display: grid;
        gap: 10px;
      }

      .inline-form {
        display: grid;
        gap: 10px;
      }

      .inline-form input {
        width: 100%;
        border-radius: 14px;
        border: 1px solid var(--border);
        padding: 12px 14px;
        font: inherit;
        background: rgba(255, 255, 255, 0.82);
      }

      .inline-form select,
      .inline-form label {
        width: 100%;
        border-radius: 14px;
        border: 1px solid var(--border);
        padding: 12px 14px;
        font: inherit;
        background: rgba(255, 255, 255, 0.82);
        color: inherit;
      }

      .inline-form label {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .inline-form input[type="checkbox"] {
        width: auto;
        margin: 0;
      }

      .warning-box {
        display: grid;
        gap: 8px;
      }

      .warning-item {
        padding: 10px 12px;
        background: rgba(217, 119, 6, 0.12);
        border-radius: 14px;
        border: 1px solid rgba(180, 83, 9, 0.18);
        color: #7c3b07;
        font-size: 0.92rem;
        line-height: 1.45;
      }

      .empty {
        color: var(--muted);
        font-style: italic;
      }

      @media (max-width: 900px) {
        .layout {
          grid-template-columns: 1fr;
        }

        .messages {
          max-height: none;
        }
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <header class="header">
        <div class="eyebrow">Local-first Memory</div>
        <h1>Chat With Your Vault</h1>
        <div class="subhead">
          This interface uses the same retrieval pipeline as the CLI. Questions are answered with evidence-backed snippets and explicit source provenance from your local SQLite index.
        </div>
      </header>

      <section class="layout">
        <div class="panel chat-panel">
          <div id="messages" class="messages">
            <div class="message assistant">
              <span class="role">Assistant</span>
              <div class="body">Ask about your indexed notes. Results stay local and each answer includes sources.</div>
            </div>
          </div>
          <form id="llm-form" class="tool-row" style="padding: 0 4px 16px;">
            <div class="inline-form">
              <select id="llm-provider">
                <option value="ollama">Ollama</option>
                <option value="gemini">Gemini</option>
                <option value="openai">OpenAI</option>
              </select>
              <label>
                <input id="use-llm" type="checkbox">
                Use LLM synthesis for answers
              </label>
            </div>
          </form>
          <form id="chat-form" class="composer">
            <textarea id="query" placeholder="What do my notes say about retrieval, a project, or a person?"></textarea>
            <button id="send-button" type="submit">Ask</button>
          </form>
        </div>

        <aside class="panel sidebar">
          <section class="card">
            <h2>Index Status</h2>
            <div id="stats" class="stats empty">Loading status…</div>
          </section>

          <section class="card">
            <h2>Latest Sources</h2>
            <div id="sources" class="sources empty">No answer yet.</div>
          </section>

          <section class="card">
            <h2>Warnings</h2>
            <div id="warnings" class="warning-box empty">No warnings.</div>
          </section>

          <section class="card">
            <h2>Search</h2>
            <form id="search-form" class="inline-form">
              <input id="search-query" type="text" placeholder="Keyword or concept">
              <button class="secondary" id="search-button" type="submit">Search</button>
            </form>
            <div id="search-results" class="search-results empty">No search results yet.</div>
          </section>
        </aside>
      </section>
    </main>

    <script>
      const messages = document.getElementById("messages");
      const chatForm = document.getElementById("chat-form");
      const queryInput = document.getElementById("query");
      const sendButton = document.getElementById("send-button");
      const stats = document.getElementById("stats");
      const sources = document.getElementById("sources");
      const warnings = document.getElementById("warnings");
      const searchForm = document.getElementById("search-form");
      const searchQueryInput = document.getElementById("search-query");
      const searchButton = document.getElementById("search-button");
      const searchResults = document.getElementById("search-results");
      const useLlmInput = document.getElementById("use-llm");
      const providerSelect = document.getElementById("llm-provider");

      function appendMessage(role, text) {
        const item = document.createElement("div");
        item.className = `message ${role}`;
        item.innerHTML = `<span class="role">${role === "user" ? "You" : "Assistant"}</span><div class="body"></div>`;
        item.querySelector(".body").textContent = text;
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;
      }

      function renderStatus(payload) {
        stats.classList.remove("empty");
        stats.innerHTML = "";
        const entries = [
          ["Documents", payload.documents],
          ["Chunks", payload.chunks],
          ["Embeddings", payload.embeddings],
          ["Latest Run", payload.latest_run ? `${payload.latest_run.run_type} (${payload.latest_run.status})` : "none"],
        ];
        for (const [label, value] of entries) {
          const row = document.createElement("div");
          row.className = "stat";
          row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
          stats.appendChild(row);
        }
      }

      function renderSources(items) {
        if (!items.length) {
          sources.className = "sources empty";
          sources.textContent = "No sources for this answer.";
          return;
        }
        sources.className = "sources";
        sources.innerHTML = "";
        for (const item of items) {
          const card = document.createElement("div");
          card.className = "source";
          const section = item.section_title ? ` · ${item.section_title}` : "";
          card.innerHTML = `
            <div class="source-title">${item.document_title}${section}</div>
            <div class="source-meta">${item.source_path}</div>
            <div class="source-meta">${item.snippet}</div>
          `;
          sources.appendChild(card);
        }
      }

      function renderSearchResults(items) {
        if (!items.length) {
          searchResults.className = "search-results empty";
          searchResults.textContent = "No results.";
          return;
        }
        searchResults.className = "search-results";
        searchResults.innerHTML = "";
        for (const item of items) {
          const card = document.createElement("div");
          card.className = "search-result";
          const section = item.section_title ? ` · ${item.section_title}` : "";
          card.innerHTML = `
            <div class="search-title">${item.document_title}${section}</div>
            <div class="search-meta">${item.source_path}</div>
            <div class="search-meta">${item.snippet}</div>
            <div class="search-meta">Final score: ${item.final_score.toFixed(3)}</div>
          `;
          searchResults.appendChild(card);
        }
      }

      function renderWarnings(items) {
        if (!items || !items.length) {
          warnings.className = "warning-box empty";
          warnings.textContent = "No warnings.";
          return;
        }
        warnings.className = "warning-box";
        warnings.innerHTML = "";
        for (const item of items) {
          const row = document.createElement("div");
          row.className = "warning-item";
          row.textContent = item;
          warnings.appendChild(row);
        }
      }

      async function loadStatus() {
        const response = await fetch("/api/status");
        const payload = await response.json();
        renderStatus(payload);
      }

      chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = queryInput.value.trim();
        if (!query) return;
        appendMessage("user", query);
        queryInput.value = "";
        sendButton.disabled = true;

        try {
          const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              query,
              use_llm: useLlmInput.checked,
              provider: providerSelect.value,
            }),
          });
          const payload = await response.json();
          appendMessage("assistant", payload.answer);
          renderSources(payload.sources || []);
          renderWarnings(payload.warnings || []);
        } catch (error) {
          appendMessage("assistant", `Request failed: ${error}`);
          renderWarnings([`Request failed: ${error}`]);
        } finally {
          sendButton.disabled = false;
        }
      });

      searchForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = searchQueryInput.value.trim();
        if (!query) return;
        searchButton.disabled = true;
        try {
          const response = await fetch(`/api/search?query=${encodeURIComponent(query)}`);
          const payload = await response.json();
          renderSearchResults(payload.results || []);
        } catch (error) {
          searchResults.className = "search-results empty";
          searchResults.textContent = `Search failed: ${error}`;
        } finally {
          searchButton.disabled = false;
        }
      });

      loadStatus();
      providerSelect.value = "ollama";
    </script>
  </body>
</html>
"""


def serve_web(settings: Settings, host: str = "127.0.0.1", port: int = 8000) -> None:
    class Handler(BaseHTTPRequestHandler):
        server_version = "PersonalMemoryHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(HTML_PAGE)
                return
            if parsed.path == "/api/status":
                self._send_json(self._with_connection(lambda conn: status_summary(conn)))
                return
            if parsed.path == "/api/search":
                query = parse_qs(parsed.query).get("query", [""])[0].strip()
                top_k_raw = parse_qs(parsed.query).get("top_k", [str(settings.top_k)])[0]
                try:
                    top_k = max(1, int(top_k_raw))
                except ValueError:
                    top_k = settings.top_k
                if not query:
                    self._send_json({"results": []})
                    return
                results = self._with_connection(
                    lambda conn: [asdict(item) for item in hybrid_search(conn, query, settings, top_k=top_k)]
                )
                self._send_json({"results": results})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            payload = self._read_json_body()
            query = str(payload.get("query", "")).strip()
            if not query:
                self._send_json({"error": "query is required"}, status=HTTPStatus.BAD_REQUEST)
                return

            top_k = payload.get("top_k", settings.top_k)
            provider = str(payload.get("provider", settings.llm_provider)).strip().lower() or settings.llm_provider
            use_llm_raw = payload.get("use_llm", settings.enable_llm_synthesis)
            try:
                top_k_value = max(1, int(top_k))
            except (TypeError, ValueError):
                top_k_value = settings.top_k
            use_llm = bool(use_llm_raw)

            request_settings = replace(settings, llm_provider=provider)

            response = self._with_connection(
                lambda conn: answer_question(conn, query, request_settings, top_k=top_k_value, use_llm=use_llm)
            )
            self._send_json(response)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _with_connection(self, callback):
            connection = connect(settings.database_path)
            try:
                init_db(connection)
                return callback(connection)
            finally:
                connection.close()

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Serving Personal Memory on http://{host}:{port}")
        server.serve_forever()
