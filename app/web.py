from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, replace
from datetime import date, datetime, time, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.db import connect, init_db
from app.ingest.register import ingest_vault, status_summary
from app.models import SearchFilters
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question
from app.util.timestamps import utc_now_iso

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
        --panel-strong: rgba(255, 255, 255, 0.84);
        --ink: #1e2a22;
        --muted: #5e695f;
        --accent: #0f766e;
        --accent-2: #d97706;
        --accent-3: #334155;
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

      button.ghost,
      a.ghost {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 38px;
        border: 1px solid var(--border);
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.66);
        color: var(--accent-3);
        padding: 9px 13px;
        font: inherit;
        font-size: 0.88rem;
        text-decoration: none;
        cursor: pointer;
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
        background: var(--panel-strong);
        border-radius: 16px;
        border: 1px solid var(--border);
      }

      .source-title, .search-title {
        font-weight: 700;
        margin-bottom: 6px;
      }

      .source-path, .search-path {
        display: inline-block;
        margin-bottom: 8px;
        padding: 4px 8px;
        border-radius: 999px;
        background: rgba(15, 118, 110, 0.1);
        color: #0f5c56;
        font-size: 0.8rem;
        font-family: "SFMono-Regular", "Menlo", "Consolas", monospace;
        word-break: break-all;
      }

      .source-snippet, .search-snippet {
        color: var(--ink);
        line-height: 1.5;
      }

      .source-meta, .search-meta {
        color: var(--muted);
        font-size: 0.88rem;
        line-height: 1.45;
        white-space: pre-wrap;
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

      .filter-panel {
        margin: 0 4px 16px;
        padding: 14px;
        border: 1px solid var(--border);
        border-radius: 20px;
        background:
          linear-gradient(135deg, rgba(15, 118, 110, 0.08), rgba(217, 119, 6, 0.06)),
          rgba(255, 255, 255, 0.48);
      }

      .filter-header {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: center;
        margin-bottom: 12px;
      }

      .filter-title {
        font-size: 0.85rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--accent);
        font-weight: 700;
      }

      .filter-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 10px;
      }

      .field {
        display: grid;
        gap: 5px;
      }

      .field span {
        color: var(--muted);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }

      .field input {
        width: 100%;
        border-radius: 14px;
        border: 1px solid var(--border);
        padding: 11px 12px;
        font: inherit;
        background: rgba(255, 255, 255, 0.82);
        color: inherit;
      }

      .active-filters {
        margin-top: 12px;
        color: var(--muted);
        font-size: 0.9rem;
        line-height: 1.45;
      }

      .action-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }

      .mini-meta {
        color: var(--muted);
        font-size: 0.82rem;
        line-height: 1.35;
        margin-top: 6px;
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

      .provider-row {
        display: grid;
        grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
        gap: 10px;
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

      .provider-status {
        padding: 10px 12px;
        background: rgba(30, 42, 34, 0.06);
        border-radius: 14px;
        border: 1px solid var(--border);
        color: var(--muted);
        font-size: 0.9rem;
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

        .filter-grid,
        .provider-row {
          grid-template-columns: 1fr;
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
              <div class="provider-row">
                <select id="llm-provider">
                  <option value="ollama">Ollama</option>
                  <option value="gemini">Gemini</option>
                  <option value="nvidia">NVIDIA</option>
                  <option value="openai">OpenAI</option>
                </select>
                <input id="synthesis-model" type="text" placeholder="Model name">
              </div>
              <div id="provider-status" class="provider-status">Checking provider availability…</div>
              <label>
                <input id="use-llm" type="checkbox">
                Use LLM synthesis for answers
              </label>
              <label>
                <input id="rewrite-query" type="checkbox">
                Rewrite natural-language query before retrieval
              </label>
            </div>
          </form>
          <section class="filter-panel" aria-label="Search filters">
            <div class="filter-header">
              <div class="filter-title">Filters</div>
              <button id="clear-filters" class="ghost" type="button">Clear filters</button>
            </div>
            <div class="filter-grid">
              <label class="field">
                <span>Tags</span>
                <input id="filter-tags" type="text" placeholder="project, planning">
              </label>
              <label class="field">
                <span>Aliases</span>
                <input id="filter-aliases" type="text" placeholder="North Star">
              </label>
              <label class="field">
                <span>Path prefix</span>
                <input id="filter-path-prefix" type="text" placeholder="/vault/projects">
              </label>
              <label class="field">
                <span>Modified from</span>
                <input id="filter-date-from" type="date">
              </label>
              <label class="field">
                <span>Modified to</span>
                <input id="filter-date-to" type="date">
              </label>
            </div>
            <div id="active-filters" class="active-filters">No filters active.</div>
          </section>
          <form id="chat-form" class="composer">
            <textarea id="query" placeholder="What do my notes say about retrieval, a project, or a person?"></textarea>
            <button id="send-button" type="submit">✨ Ask</button>
          </form>
        </div>

        <aside class="panel sidebar">
          <section class="card">
            <h2>📚 Index Status</h2>
            <form id="refresh-form" class="inline-form" style="margin-bottom: 12px;">
              <button class="secondary" id="refresh-button" type="submit">🔄 Refresh Index</button>
            </form>
            <div id="stats" class="stats empty">Loading status…</div>
          </section>

          <section class="card">
            <h2>🛰 Provider</h2>
            <div id="response-provider" class="sources empty">No response yet.</div>
          </section>

          <section class="card">
            <h2>🧾 Latest Sources</h2>
            <div id="sources" class="sources empty">No answer yet.</div>
          </section>

          <section class="card">
            <h2>🧠 Retrieval Query</h2>
            <div id="retrieval-query" class="sources empty">No query yet.</div>
          </section>

          <section class="card">
            <h2>⚠️ Warnings</h2>
            <div id="warnings" class="warning-box empty">No warnings.</div>
          </section>

          <section class="card">
            <h2>🔎 Search</h2>
            <form id="search-form" class="inline-form">
              <input id="search-query" type="text" placeholder="Keyword or concept">
              <button class="secondary" id="search-button" type="submit">🔎 Search</button>
            </form>
            <div id="search-results" class="search-results empty">No search results yet.</div>
          </section>

          <section class="card">
            <h2>🕘 Recent Queries</h2>
            <div id="recent-queries" class="sources empty">No recent queries yet.</div>
          </section>

          <section class="card">
            <h2>📌 Saved Searches</h2>
            <form id="saved-search-form" class="inline-form">
              <input id="saved-search-name" type="text" placeholder="Save current query as">
              <button class="secondary" id="save-search-button" type="submit">Save Search</button>
            </form>
            <div id="saved-searches" class="sources empty">No saved searches yet.</div>
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
      const refreshForm = document.getElementById("refresh-form");
      const refreshButton = document.getElementById("refresh-button");
      const responseProvider = document.getElementById("response-provider");
      const sources = document.getElementById("sources");
      const retrievalQuery = document.getElementById("retrieval-query");
      const warnings = document.getElementById("warnings");
      const searchForm = document.getElementById("search-form");
      const searchQueryInput = document.getElementById("search-query");
      const searchButton = document.getElementById("search-button");
      const searchResults = document.getElementById("search-results");
      const recentQueries = document.getElementById("recent-queries");
      const savedSearchForm = document.getElementById("saved-search-form");
      const savedSearchNameInput = document.getElementById("saved-search-name");
      const savedSearches = document.getElementById("saved-searches");
      const useLlmInput = document.getElementById("use-llm");
      const rewriteQueryInput = document.getElementById("rewrite-query");
      const providerSelect = document.getElementById("llm-provider");
      const synthesisModelInput = document.getElementById("synthesis-model");
      const providerStatus = document.getElementById("provider-status");
      const filterTagsInput = document.getElementById("filter-tags");
      const filterAliasesInput = document.getElementById("filter-aliases");
      const filterPathPrefixInput = document.getElementById("filter-path-prefix");
      const filterDateFromInput = document.getElementById("filter-date-from");
      const filterDateToInput = document.getElementById("filter-date-to");
      const activeFilters = document.getElementById("active-filters");
      const clearFiltersButton = document.getElementById("clear-filters");
      let providerDefaults = {};
      let providerAvailability = {};
      const RECENT_QUERIES_KEY = "personal-memory-recent-queries";
      const SAVED_SEARCHES_KEY = "personal-memory-saved-searches";

      function formatErrorMessage(errorPayload) {
        if (!errorPayload) return "Request failed.";
        if (typeof errorPayload === "string") return errorPayload;
        if (typeof errorPayload.message === "string" && errorPayload.message) return errorPayload.message;
        return "Request failed.";
      }

      function appendMessage(role, text) {
        const item = document.createElement("div");
        item.className = `message ${role}`;
        item.innerHTML = `<span class="role">${role === "user" ? "You" : "Assistant"}</span><div class="body"></div>`;
        item.querySelector(".body").textContent = text;
        messages.appendChild(item);
        messages.scrollTop = messages.scrollHeight;
      }

      function parseCsv(value) {
        return value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
      }

      function readFilters() {
        return {
          tags: parseCsv(filterTagsInput.value),
          aliases: parseCsv(filterAliasesInput.value),
          path_prefix: filterPathPrefixInput.value.trim() || null,
          date_from: filterDateFromInput.value || null,
          date_to: filterDateToInput.value || null,
        };
      }

      function setFilters(filters = {}) {
        filterTagsInput.value = (filters.tags || []).join(", ");
        filterAliasesInput.value = (filters.aliases || []).join(", ");
        filterPathPrefixInput.value = filters.path_prefix || "";
        filterDateFromInput.value = normalizeDateInput(filters.date_from);
        filterDateToInput.value = normalizeDateInput(filters.date_to);
        renderActiveFilters();
      }

      function normalizeDateInput(value) {
        if (!value) return "";
        return String(value).slice(0, 10);
      }

      function filterLabels(filters = readFilters()) {
        const labels = [];
        if (filters.tags?.length) labels.push(`tags: ${filters.tags.join(", ")}`);
        if (filters.aliases?.length) labels.push(`aliases: ${filters.aliases.join(", ")}`);
        if (filters.path_prefix) labels.push(`path: ${filters.path_prefix}`);
        if (filters.date_from) labels.push(`from: ${filters.date_from}`);
        if (filters.date_to) labels.push(`to: ${filters.date_to}`);
        return labels;
      }

      function renderActiveFilters() {
        const labels = filterLabels();
        activeFilters.textContent = labels.length ? `Active filters: ${labels.join(" · ")}` : "No filters active.";
      }

      function appendFiltersToParams(params, filters = readFilters()) {
        for (const tag of filters.tags || []) params.append("tags", tag);
        for (const alias of filters.aliases || []) params.append("aliases", alias);
        if (filters.path_prefix) params.set("path_prefix", filters.path_prefix);
        if (filters.date_from) params.set("date_from", filters.date_from);
        if (filters.date_to) params.set("date_to", filters.date_to);
      }

      function loadStoredList(key) {
        try {
          return JSON.parse(localStorage.getItem(key) || "[]");
        } catch {
          return [];
        }
      }

      function saveStoredList(key, value) {
        localStorage.setItem(key, JSON.stringify(value));
      }

      function rememberQuery(query) {
        const entries = loadStoredList(RECENT_QUERIES_KEY).filter((item) => item !== query);
        entries.unshift(query);
        saveStoredList(RECENT_QUERIES_KEY, entries.slice(0, 8));
        renderRecentQueries();
      }

      function renderRecentQueries() {
        const entries = loadStoredList(RECENT_QUERIES_KEY);
        if (!entries.length) {
          recentQueries.className = "sources empty";
          recentQueries.textContent = "No recent queries yet.";
          return;
        }
        recentQueries.className = "sources";
        recentQueries.innerHTML = "";
        for (const entry of entries) {
          const card = document.createElement("div");
          card.className = "source";
          const title = document.createElement("div");
          title.className = "source-title";
          title.textContent = entry;
          card.appendChild(title);
          const actions = document.createElement("div");
          actions.className = "action-row";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ghost";
          button.textContent = "Reuse";
          button.addEventListener("click", () => {
            queryInput.value = entry;
            searchQueryInput.value = entry;
          });
          actions.appendChild(button);
          card.appendChild(actions);
          recentQueries.appendChild(card);
        }
      }

      function renderSavedSearches() {
        const entries = loadStoredList(SAVED_SEARCHES_KEY);
        if (!entries.length) {
          savedSearches.className = "sources empty";
          savedSearches.textContent = "No saved searches yet.";
          return;
        }
        savedSearches.className = "sources";
        savedSearches.innerHTML = "";
        for (const entry of entries) {
          const card = document.createElement("div");
          card.className = "source";
          const title = document.createElement("div");
          title.className = "source-title";
          title.textContent = entry.name;
          const query = document.createElement("div");
          query.className = "source-meta";
          query.textContent = entry.query;
          const filterSummary = document.createElement("div");
          filterSummary.className = "mini-meta";
          const labels = filterLabels(entry.filters || {});
          filterSummary.textContent = labels.length ? labels.join(" · ") : "No filters";
          card.append(title, query, filterSummary);
          const actions = document.createElement("div");
          actions.className = "action-row";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ghost";
          button.textContent = "Run";
          button.addEventListener("click", () => {
            queryInput.value = entry.query;
            searchQueryInput.value = entry.query;
            setFilters(entry.filters || {});
          });
          const deleteButton = document.createElement("button");
          deleteButton.type = "button";
          deleteButton.className = "ghost";
          deleteButton.textContent = "Delete";
          deleteButton.addEventListener("click", () => {
            const remaining = loadStoredList(SAVED_SEARCHES_KEY).filter((item) => item.name !== entry.name);
            saveStoredList(SAVED_SEARCHES_KEY, remaining);
            renderSavedSearches();
          });
          actions.append(button, deleteButton);
          card.appendChild(actions);
          savedSearches.appendChild(card);
        }
      }

      function renderResponseProvider(provider, model) {
        if (!provider && !model) {
          responseProvider.className = "sources empty";
          responseProvider.textContent = "No response yet.";
          return;
        }
        responseProvider.className = "sources";
        responseProvider.innerHTML = "";
        const card = document.createElement("div");
        card.className = "source";
        const meta = document.createElement("div");
        meta.className = "source-meta";
        meta.textContent = `Provider: ${provider || "unknown"}\nModel: ${model || "default"}`;
        card.appendChild(meta);
        responseProvider.appendChild(card);
      }

      async function copyText(value, successMessage) {
        try {
          await navigator.clipboard.writeText(value);
          renderWarnings([successMessage]);
        } catch (error) {
          renderWarnings([`Copy failed: ${error}`]);
        }
      }

      function renderStatus(payload) {
        providerDefaults = payload.provider_defaults || {};
        providerAvailability = payload.provider_availability || {};
        stats.classList.remove("empty");
        stats.innerHTML = "";
        const refreshState = payload.refresh_state || {};
        const refreshLabel = refreshState.in_progress
          ? "running"
          : refreshState.last_result?.status || "idle";
        const entries = [
          ["Documents", payload.documents],
          ["Chunks", payload.chunks],
          ["Embeddings", payload.embeddings],
          ["Vault", payload.vault_path || "not configured"],
          ["Latest Run", payload.latest_run ? `${payload.latest_run.run_type} (${payload.latest_run.status})` : "none"],
          ["Refresh State", refreshLabel],
          ["Refresh Ready", payload.refresh_available ? "yes" : "no"],
        ];
        for (const [label, value] of entries) {
          const row = document.createElement("div");
          row.className = "stat";
          row.innerHTML = `<span>${label}</span><strong>${value}</strong>`;
          stats.appendChild(row);
        }
        refreshButton.disabled = !payload.refresh_available || Boolean(refreshState.in_progress);
        syncProviderOptions(payload.llm_provider || "ollama");
        const diagnosticWarnings = (payload.config_diagnostics || []).map((item) => item.message);
        if (refreshState.last_result?.status === "failed" && refreshState.last_result?.error) {
          diagnosticWarnings.unshift(`Last refresh failed: ${refreshState.last_result.error}`);
        }
        if (diagnosticWarnings.length) {
          renderWarnings(diagnosticWarnings);
        } else if (refreshState.in_progress) {
          renderWarnings(["Refresh is in progress."]);
        } else if (refreshState.last_result?.status === "completed") {
          renderWarnings(["Last refresh completed successfully."]);
        }
      }

      function syncModelInput() {
        synthesisModelInput.value = providerDefaults[providerSelect.value] || "";
      }

      function syncProviderOptions(preferredProvider) {
        let nextProvider = preferredProvider;
        for (const option of providerSelect.options) {
          const availability = providerAvailability[option.value] || { available: true, reason: "" };
          option.disabled = !availability.available;
          option.textContent = availability.available
            ? option.value === "ollama"
              ? "Ollama"
              : option.value === "gemini"
                ? "Gemini"
                : option.value === "nvidia"
                  ? "NVIDIA"
                  : "OpenAI"
            : `${option.value === "ollama" ? "Ollama" : option.value === "gemini" ? "Gemini" : option.value === "nvidia" ? "NVIDIA" : "OpenAI"} (key missing)`;
        }

        const preferredAvailability = providerAvailability[nextProvider] || { available: true, reason: "" };
        if (!preferredAvailability.available) {
          const firstAvailable = Array.from(providerSelect.options).find((option) => !option.disabled);
          nextProvider = firstAvailable ? firstAvailable.value : providerSelect.value;
        }
        providerSelect.value = nextProvider;
        syncProviderState();
      }

      function syncProviderState() {
        const availability = providerAvailability[providerSelect.value] || { available: true, reason: "" };
        const providerLabel = providerSelect.options[providerSelect.selectedIndex]?.textContent || providerSelect.value;
        syncModelInput();
        if (!availability.available) {
          useLlmInput.checked = false;
          useLlmInput.disabled = true;
          rewriteQueryInput.checked = false;
          rewriteQueryInput.disabled = true;
          synthesisModelInput.disabled = true;
          providerStatus.textContent = `${providerLabel} is unavailable: ${availability.reason}`;
          return;
        }
        useLlmInput.disabled = false;
        rewriteQueryInput.disabled = false;
        synthesisModelInput.disabled = false;
        providerStatus.textContent = `${providerLabel} is available.`;
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
          const title = document.createElement("div");
          title.className = "source-title";
          title.textContent = `${item.document_title}${section}`;
          const path = document.createElement("div");
          path.className = "source-path";
          path.textContent = item.source_path;
          const snippet = document.createElement("div");
          snippet.className = "source-snippet";
          snippet.textContent = item.snippet;
          const meta = document.createElement("div");
          meta.className = "source-meta";
          const score = typeof item.final_score === "number" ? `\nFinal score: ${item.final_score.toFixed(3)}` : "";
          const metadata = typeof item.metadata_score === "number" ? ` · metadata: ${item.metadata_score.toFixed(3)}` : "";
          meta.textContent = `${item.source_ref || item.source_path}${score}${metadata}`;
          const actions = document.createElement("div");
          actions.className = "action-row";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ghost";
          button.textContent = "Copy Source Ref";
          button.addEventListener("click", () => copyText(item.source_ref || item.source_path, "Source reference copied."));
          const pathButton = document.createElement("button");
          pathButton.type = "button";
          pathButton.className = "ghost";
          pathButton.textContent = "Copy Path";
          pathButton.addEventListener("click", () => copyText(item.source_path, "Source path copied."));
          const openLink = document.createElement("a");
          openLink.className = "ghost";
          openLink.textContent = "Open Hook";
          openLink.href = `obsidian://open?path=${encodeURIComponent(item.source_path)}`;
          actions.append(button, pathButton, openLink);
          card.append(title, path, snippet, meta, actions);
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
          const title = document.createElement("div");
          title.className = "search-title";
          title.textContent = `${item.document_title}${section}`;
          const path = document.createElement("div");
          path.className = "search-path";
          path.textContent = item.source_path;
          const snippet = document.createElement("div");
          snippet.className = "search-snippet";
          snippet.textContent = item.snippet;
          const meta = document.createElement("div");
          meta.className = "search-meta";
          const metadata = typeof item.metadata_score === "number" ? ` · metadata: ${item.metadata_score.toFixed(3)}` : "";
          meta.textContent = `Final score: ${item.final_score.toFixed(3)}${metadata}`;
          const actions = document.createElement("div");
          actions.className = "action-row";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ghost";
          button.textContent = "Copy Path";
          button.addEventListener("click", () => copyText(item.source_path, "Source path copied."));
          const refButton = document.createElement("button");
          refButton.type = "button";
          refButton.className = "ghost";
          refButton.textContent = "Copy Section Ref";
          const sourceRef = item.section_title ? `${item.source_path}#${item.section_title.toLowerCase().replaceAll(" ", "-")}` : item.source_path;
          refButton.addEventListener("click", () => copyText(sourceRef, "Section reference copied."));
          const openLink = document.createElement("a");
          openLink.className = "ghost";
          openLink.textContent = "Open Hook";
          openLink.href = `obsidian://open?path=${encodeURIComponent(item.source_path)}`;
          actions.append(button, refButton, openLink);
          card.append(title, path, snippet, meta, actions);
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

      function renderRetrievalQuery(value) {
        if (!value) {
          retrievalQuery.className = "sources empty";
          retrievalQuery.textContent = "No query yet.";
          return;
        }
        retrievalQuery.className = "sources";
        retrievalQuery.innerHTML = "";
        const card = document.createElement("div");
        card.className = "source";
        const meta = document.createElement("div");
        meta.className = "source-meta";
        meta.textContent = value;
        card.appendChild(meta);
        retrievalQuery.appendChild(card);
      }

      async function loadStatus() {
        try {
          const response = await fetch("/api/status");
          const payload = await response.json();
          if (!response.ok) {
            renderWarnings([formatErrorMessage(payload.error)]);
            return;
          }
          renderStatus(payload);
        } catch (error) {
          stats.className = "stats empty";
          stats.textContent = "Status unavailable.";
          renderWarnings([`Status check failed: ${error}`]);
        }
      }

      refreshForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        refreshButton.disabled = true;
        try {
          const response = await fetch("/api/refresh", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          });
          const payload = await response.json();
          if (!response.ok) {
            renderWarnings([formatErrorMessage(payload.error)]);
            return;
          }
          renderWarnings([
            `Index refresh completed: indexed ${payload.indexed}, skipped ${payload.skipped}, pruned ${payload.pruned}.`,
          ]);
          await loadStatus();
        } catch (error) {
          renderWarnings([`Refresh failed: ${error}`]);
        } finally {
          refreshButton.disabled = false;
        }
      });

      chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const query = queryInput.value.trim();
        if (!query) return;
        const filters = readFilters();
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
              rewrite_query: rewriteQueryInput.checked,
              provider: providerSelect.value,
              model: synthesisModelInput.value.trim(),
              filters,
            }),
          });
          const payload = await response.json();
          if (!response.ok) {
            const errorMessage = formatErrorMessage(payload.error);
            appendMessage("assistant", errorMessage);
            renderSources([]);
            renderRetrievalQuery(payload.retrieval_query || "");
            renderWarnings([errorMessage]);
            renderResponseProvider("", "");
            return;
          }
          rememberQuery(query);
          appendMessage("assistant", payload.answer);
          renderSources(payload.sources || []);
          renderRetrievalQuery(payload.retrieval_query || query);
          renderWarnings(payload.warnings || []);
          renderResponseProvider(payload.provider, payload.model);
        } catch (error) {
          appendMessage("assistant", `Request failed: ${error}`);
          renderRetrievalQuery("");
          renderWarnings([`Request failed: ${error}`]);
          renderResponseProvider("", "");
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
          const params = new URLSearchParams({ query });
          appendFiltersToParams(params);
          const response = await fetch(`/api/search?${params.toString()}`);
          const payload = await response.json();
          if (!response.ok) {
            throw new Error(formatErrorMessage(payload.error));
          }
          rememberQuery(query);
          renderSearchResults(payload.results || []);
        } catch (error) {
          searchResults.className = "search-results empty";
          searchResults.textContent = `Search failed: ${error}`;
        } finally {
          searchButton.disabled = false;
        }
      });

      savedSearchForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const name = savedSearchNameInput.value.trim();
        const query = (searchQueryInput.value || queryInput.value).trim();
        if (!name || !query) return;
        const entries = loadStoredList(SAVED_SEARCHES_KEY).filter((item) => item.name !== name);
        entries.unshift({ name, query, filters: readFilters() });
        saveStoredList(SAVED_SEARCHES_KEY, entries.slice(0, 8));
        savedSearchNameInput.value = "";
        renderSavedSearches();
      });

      clearFiltersButton.addEventListener("click", () => setFilters({}));
      for (const input of [filterTagsInput, filterAliasesInput, filterPathPrefixInput, filterDateFromInput, filterDateToInput]) {
        input.addEventListener("input", renderActiveFilters);
      }

      loadStatus();
      renderRecentQueries();
      renderSavedSearches();
      providerSelect.addEventListener("change", syncProviderState);
      renderRetrievalQuery("");
      renderResponseProvider("", "");
      renderActiveFilters();
    </script>
  </body>
</html>
"""


class APIError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: HTTPStatus,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


class RefreshState:
    def __init__(self) -> None:
        self._refresh_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._in_progress = False
        self._started_at: str | None = None
        self._last_completed_at: str | None = None
        self._last_result: dict[str, object] | None = None

    def begin(self) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            raise APIError(
                "refresh_in_progress",
                "A refresh is already running.",
                status=HTTPStatus.CONFLICT,
            )
        with self._state_lock:
            self._in_progress = True
            self._started_at = utc_now_iso()
            self._last_result = None

    def finish(self, result: dict[str, object]) -> None:
        with self._state_lock:
            self._in_progress = False
            self._last_completed_at = utc_now_iso()
            self._last_result = dict(result)
            self._started_at = None
        self._refresh_lock.release()

    def snapshot(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "in_progress": self._in_progress,
                "started_at": self._started_at,
                "last_completed_at": self._last_completed_at,
                "last_result": self._last_result,
            }


def _success_payload(payload: dict[str, object]) -> dict[str, object]:
    return {"ok": True, **payload}


def _error_payload(error: APIError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": error.message,
            "details": error.details,
        },
    }


def _read_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise APIError(
        "invalid_boolean",
        f"{key} must be a boolean.",
        status=HTTPStatus.BAD_REQUEST,
        details={"field": key},
    )


def _read_top_k(value: object, default: int) -> int:
    if value is None:
        return default
    try:
        top_k = int(value)
    except (TypeError, ValueError) as exc:
        raise APIError(
            "invalid_top_k",
            "top_k must be an integer.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "top_k"},
        ) from exc
    if top_k < 1:
        raise APIError(
            "invalid_top_k",
            "top_k must be greater than zero.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "top_k"},
        )
    return top_k


def _resolve_provider(settings: Settings, provider_value: object) -> str:
    provider = str(provider_value or settings.llm_provider).strip().lower() or settings.llm_provider
    if not settings.is_supported_provider(provider):
        raise APIError(
            "invalid_provider",
            f"Unsupported provider: {provider}",
            status=HTTPStatus.BAD_REQUEST,
            details={"provider": provider},
        )
    return provider


def _validate_provider_request(settings: Settings, provider: str, *, require_provider: bool) -> None:
    if not require_provider:
        return
    availability = settings.provider_availability().get(provider, {"available": False, "reason": "Provider is unavailable."})
    if not bool(availability.get("available")):
        raise APIError(
            "provider_unavailable",
            str(availability.get("reason") or f"{provider} is unavailable."),
            status=HTTPStatus.BAD_REQUEST,
            details={"provider": provider},
        )


def _parse_csv_filter(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        items = [item.strip().lower() for item in value.split(",")]
        return tuple(item for item in items if item)
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(part.strip().lower() for part in str(item).split(","))
        return tuple(item for item in items if item)
    raise APIError("invalid_filter", "Filter values must be strings or arrays.", status=HTTPStatus.BAD_REQUEST)


def _parse_optional_string_filter(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIError(
            "invalid_filter",
            f"{field} must be a string.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        )
    return value.strip() or None


def _parse_date_filter(value: object, *, field: str, end_of_day: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIError(
            "invalid_filter",
            f"{field} must be a date string.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        )
    raw = value.strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            parsed_datetime = datetime.combine(parsed_date, time.max if end_of_day else time.min, tzinfo=timezone.utc)
        else:
            parsed_datetime = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed_datetime.tzinfo is None:
                parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
            else:
                parsed_datetime = parsed_datetime.astimezone(timezone.utc)
    except ValueError as exc:
        raise APIError(
            "invalid_filter",
            f"{field} must be an ISO date or datetime.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": field},
        ) from exc
    return parsed_datetime.replace(microsecond=0).isoformat()


def _read_filters(payload: dict[str, Any]) -> SearchFilters:
    raw_filters = payload.get("filters", {})
    if raw_filters is None:
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        raise APIError("invalid_filter", "filters must be an object.", status=HTTPStatus.BAD_REQUEST)
    date_from = _parse_date_filter(raw_filters.get("date_from"), field="filters.date_from")
    date_to = _parse_date_filter(raw_filters.get("date_to"), field="filters.date_to", end_of_day=True)
    if date_from and date_to and date_from > date_to:
        raise APIError(
            "invalid_filter",
            "filters.date_from must be before filters.date_to.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "filters.date_from"},
        )
    return SearchFilters(
        tags=_parse_csv_filter(raw_filters.get("tags")),
        aliases=_parse_csv_filter(raw_filters.get("aliases")),
        path_prefix=_parse_optional_string_filter(raw_filters.get("path_prefix"), field="filters.path_prefix"),
        date_from=date_from,
        date_to=date_to,
    )


def _read_filters_from_query(path: str) -> SearchFilters:
    parsed = urlparse(path)
    query = parse_qs(parsed.query)
    date_from = _parse_date_filter(query.get("date_from", [""])[0], field="date_from")
    date_to = _parse_date_filter(query.get("date_to", [""])[0], field="date_to", end_of_day=True)
    if date_from and date_to and date_from > date_to:
        raise APIError(
            "invalid_filter",
            "date_from must be before date_to.",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "date_from"},
        )
    return SearchFilters(
        tags=_parse_csv_filter(query.get("tags", [])),
        aliases=_parse_csv_filter(query.get("aliases", [])),
        path_prefix=_parse_optional_string_filter(query.get("path_prefix", [""])[0], field="path_prefix"),
        date_from=date_from,
        date_to=date_to,
    )


def _serialize_filters(filters: SearchFilters) -> dict[str, object]:
    return {
        "tags": list(filters.tags),
        "aliases": list(filters.aliases),
        "path_prefix": filters.path_prefix,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }


def handle_api_get(
    path: str,
    settings: Settings,
    refresh_state: RefreshState,
    with_connection,
) -> tuple[HTTPStatus, dict[str, object]]:
    parsed = urlparse(path)
    if parsed.path == "/api/status":
        summary = with_connection(lambda conn: status_summary(conn))
        summary["vault_path"] = str(settings.vault_path) if settings.vault_path else None
        summary["refresh_available"] = settings.vault_path is not None
        summary["refresh_state"] = refresh_state.snapshot()
        summary["llm_provider"] = settings.llm_provider
        summary["provider_defaults"] = settings.synthesis_model_defaults()
        summary["provider_availability"] = settings.provider_availability()
        summary["config_diagnostics"] = settings.validate()
        return HTTPStatus.OK, _success_payload(summary)
    if parsed.path == "/api/search":
        query = parse_qs(parsed.query).get("query", [""])[0].strip()
        top_k = _read_top_k(parse_qs(parsed.query).get("top_k", [settings.top_k])[0], settings.top_k)
        filters = _read_filters_from_query(path)
        if not query:
            return HTTPStatus.OK, _success_payload({"results": []})
        results = with_connection(
            lambda conn: [asdict(item) for item in hybrid_search(conn, query, settings, top_k=top_k, filters=filters)]
        )
        return HTTPStatus.OK, _success_payload({"results": results, "filters": _serialize_filters(filters)})
    raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)


def handle_api_post(
    path: str,
    payload: dict[str, Any],
    settings: Settings,
    refresh_state: RefreshState,
    with_connection,
) -> tuple[HTTPStatus, dict[str, object]]:
    parsed = urlparse(path)
    if parsed.path == "/api/refresh":
        if settings.vault_path is None:
            raise APIError(
                "vault_not_configured",
                "VAULT_PATH is not configured, so the index cannot be refreshed.",
                status=HTTPStatus.BAD_REQUEST,
            )
        refresh_state.begin()
        try:
            summary = with_connection(lambda conn: ingest_vault(conn, settings.vault_path, settings))
        except Exception as exc:
            refresh_state.finish({"status": "failed", "error": str(exc)})
            raise APIError(
                "refresh_failed",
                f"Refresh failed: {exc}",
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                details={"refresh_state": refresh_state.snapshot()},
            ) from exc
        refresh_state.finish({"status": "completed", **summary})
        return HTTPStatus.OK, _success_payload(summary)
    if parsed.path != "/api/chat":
        raise APIError("not_found", "Not found", status=HTTPStatus.NOT_FOUND)

    query = str(payload.get("query", "")).strip()
    if not query:
        raise APIError(
            "missing_query",
            "query is required",
            status=HTTPStatus.BAD_REQUEST,
            details={"field": "query"},
        )

    top_k_value = _read_top_k(payload.get("top_k"), settings.top_k)
    provider = _resolve_provider(settings, payload.get("provider", settings.llm_provider))
    model = str(payload.get("model", "")).strip() or None
    use_llm = _read_bool(payload, "use_llm", settings.enable_llm_synthesis)
    use_query_rewrite = _read_bool(payload, "rewrite_query", settings.enable_query_rewrite)
    filters = _read_filters(payload)

    request_settings = replace(settings, llm_provider=provider, synthesis_model_name=model)
    _validate_provider_request(request_settings, provider, require_provider=use_llm or use_query_rewrite)

    response = with_connection(
        lambda conn: answer_question(
            conn,
            query,
            request_settings,
            top_k=top_k_value,
            use_llm=use_llm,
            use_query_rewrite=use_query_rewrite,
            filters=filters,
        )
    )
    response["filters"] = _serialize_filters(filters)
    return HTTPStatus.OK, _success_payload(response)


def build_handler(settings: Settings, refresh_state: RefreshState | None = None) -> type[BaseHTTPRequestHandler]:
    refresh_state = refresh_state or RefreshState()

    class Handler(BaseHTTPRequestHandler):
        server_version = "PersonalMemoryHTTP/0.1"

        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(HTML_PAGE)
                    return
                status, response = handle_api_get(self.path, settings, refresh_state, self._with_connection)
                self._send_json(response, status=status)
            except APIError as exc:
                self._send_json(_error_payload(exc), status=exc.status)
            except Exception as exc:
                self._send_json(
                    _error_payload(
                        APIError(
                            "internal_error",
                            str(exc),
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    ),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._read_json_body()
                status, response = handle_api_post(self.path, payload, settings, refresh_state, self._with_connection)
                self._send_json(response, status=status)
            except APIError as exc:
                self._send_json(_error_payload(exc), status=exc.status)
            except Exception as exc:
                self._send_json(
                    _error_payload(
                        APIError(
                            "internal_error",
                            str(exc),
                            status=HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    ),
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )

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
            except json.JSONDecodeError as exc:
                raise APIError("invalid_json", "Request body must be valid JSON.", status=HTTPStatus.BAD_REQUEST) from exc
            return payload if isinstance(payload, dict) else {}

        def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def serve_web(settings: Settings, host: str = "0.0.0.0", port: int = 8000) -> None:
    with ThreadingHTTPServer((host, port), build_handler(settings)) as server:
        if host == "0.0.0.0":
            print(
                "Serving Personal Memory on all interfaces "
                f"(local: http://127.0.0.1:{port}, LAN: http://<your-lan-ip>:{port})"
            )
        else:
            print(f"Serving Personal Memory on http://{host}:{port}")
        server.serve_forever()
