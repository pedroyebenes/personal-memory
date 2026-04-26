      const chatForm = document.getElementById("chat-form");
      const queryInput = document.getElementById("query");
      const sendButton = document.getElementById("send-button");
      const stats = document.getElementById("stats");
      const refreshForm = document.getElementById("refresh-form");
      const refreshButton = document.getElementById("refresh-button");
      const helpButton = document.getElementById("help-button");
      const helpDialog = document.getElementById("help-dialog");
      const answerTabs = document.getElementById("answer-tabs");
      const answerDetail = document.getElementById("answer-detail");
      const warnings = document.getElementById("warnings");
      const mainViewButtons = Array.from(document.querySelectorAll("[data-main-view]"));
      const mainViews = {
        answers: document.getElementById("answers-view"),
        search: document.getElementById("search-view"),
        concepts: document.getElementById("concepts-view"),
        eval: document.getElementById("eval-view"),
      };
      const sidebarSections = Array.from(document.querySelectorAll("[data-sidebar-view]"));
      const searchForm = document.getElementById("search-form");
      const searchQueryInput = document.getElementById("search-query");
      const searchButton = document.getElementById("search-button");
      const searchResults = document.getElementById("search-results");
      const recentQueries = document.getElementById("recent-queries");
      const savedSearchForm = document.getElementById("saved-search-form");
      const savedSearchNameInput = document.getElementById("saved-search-name");
      const savedSearches = document.getElementById("saved-searches");
      const conceptsForm = document.getElementById("concepts-form");
      const conceptSearchInput = document.getElementById("concept-search");
      const conceptTypeInput = document.getElementById("concept-type");
      const conceptQualityInput = document.getElementById("concept-quality");
      const conceptMethodInput = document.getElementById("concept-method");
      const conceptsButton = document.getElementById("concepts-button");
      const conceptResults = document.getElementById("concept-results");
      const evalForm = document.getElementById("eval-form");
      const evalCasesInput = document.getElementById("eval-cases");
      const evalConceptBoostInput = document.getElementById("eval-concept-boost");
      const evalRerankInput = document.getElementById("eval-rerank");
      const evalButton = document.getElementById("eval-button");
      const evalResults = document.getElementById("eval-results");
      const useLlmInput = document.getElementById("use-llm");
      const rewriteQueryInput = document.getElementById("rewrite-query");
      const rerankResultsInput = document.getElementById("rerank-results");
      const conceptBoostResultsInput = document.getElementById("concept-boost-results");
      const topKInput = document.getElementById("top-k");
      const providerSelect = document.getElementById("llm-provider");
      const synthesisModelInput = document.getElementById("synthesis-model");
      const providerStatus = document.getElementById("provider-status");
      const filterTagsInput = document.getElementById("filter-tags");
      const filterAliasesInput = document.getElementById("filter-aliases");
      const filterPathPrefixInput = document.getElementById("filter-path-prefix");
      const filterDateFromInput = document.getElementById("filter-date-from");
      const filterDateToInput = document.getElementById("filter-date-to");
      const activeFilters = document.getElementById("active-filters");
      const activeFilterSummary = document.getElementById("active-filter-summary");
      const clearFiltersButton = document.getElementById("clear-filters");
      let providerDefaults = {};
      let providerAvailability = {};
      let answerWorkspaces = [];
      let activeWorkspaceId = null;
      const RECENT_QUERIES_KEY = "personal-memory-recent-queries";
      const SAVED_SEARCHES_KEY = "personal-memory-saved-searches";
      const DEFAULT_EVAL_CASES = {
        cases: [
          {
            id: "north-star",
            query: "North Star launch",
            expected_paths: ["project-note.md"],
            expected_terms: ["launch"],
          },
        ],
      };

      function formatErrorMessage(errorPayload) {
        if (!errorPayload) return "Request failed.";
        if (typeof errorPayload === "string") return errorPayload;
        if (typeof errorPayload.message === "string" && errorPayload.message) return errorPayload.message;
        return "Request failed.";
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

      function readTopK() {
        const parsed = Number.parseInt(topKInput.value, 10);
        if (!Number.isFinite(parsed) || parsed < 1) {
          topKInput.value = "1";
          return 1;
        }
        return parsed;
      }

      function setFilters(filters = {}) {
        filterTagsInput.value = (filters.tags || []).join(", ");
        filterAliasesInput.value = (filters.aliases || []).join(", ");
        filterPathPrefixInput.value = filters.path_prefix || "";
        filterDateFromInput.value = normalizeDateInput(filters.date_from);
        filterDateToInput.value = normalizeDateInput(filters.date_to);
        renderActiveFilters();
      }

      function setTopK(value) {
        if (value === undefined || value === null || value === "") return;
        const parsed = Number.parseInt(value, 10);
        topKInput.value = Number.isFinite(parsed) && parsed >= 1 ? String(parsed) : "5";
      }

      function normalizeDateInput(value) {
        if (!value) return "";
        return String(value).slice(0, 10);
      }

      function filterLabels(filters = readFilters()) {
        const labels = [];
        if (filters.tags?.length) labels.push(`tags: ${filters.tags.join(", ")}`);
        if (filters.aliases?.length) labels.push(`aliases: ${filters.aliases.join(", ")}`);
        if (filters.path_prefix) labels.push(`vault path: ${filters.path_prefix}`);
        if (filters.date_from) labels.push(`from: ${filters.date_from}`);
        if (filters.date_to) labels.push(`to: ${filters.date_to}`);
        return labels;
      }

      function renderActiveFilters() {
        const labels = filterLabels();
        activeFilters.textContent = labels.length ? `Active filters: ${labels.join(" · ")}` : "No filters active.";
        activeFilterSummary.textContent = labels.length ? `${labels.length} active` : "None";
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

      function switchRailTab(name) {
        for (const button of mainViewButtons) {
          button.classList.toggle("active", button.dataset.mainView === name);
        }
        for (const [viewName, view] of Object.entries(mainViews)) {
          view.classList.toggle("active", viewName === name);
        }
        for (const section of sidebarSections) {
          const views = (section.dataset.sidebarView || "").split(/\s+/).filter(Boolean);
          section.hidden = !views.includes(name);
        }
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
            switchRailTab("search");
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
          const topKLabel = entry.top_k ? `sources: ${entry.top_k}` : "";
          filterSummary.textContent = [labels.length ? labels.join(" · ") : "No filters", topKLabel].filter(Boolean).join(" · ");
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
            setTopK(entry.top_k);
            switchRailTab("search");
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

      async function copyText(value, successMessage) {
        try {
          await navigator.clipboard.writeText(value);
          renderWarnings([successMessage]);
        } catch (error) {
          renderWarnings([`Copy failed: ${error}`]);
        }
      }

      function compactScoreExplanation(explanation = {}) {
        const labels = [];
        if (typeof explanation.keyword_score === "number") labels.push(`keyword ${explanation.keyword_score.toFixed(3)}`);
        if (typeof explanation.semantic_score === "number") labels.push(`semantic ${explanation.semantic_score.toFixed(3)}`);
        if (typeof explanation.metadata_score === "number") labels.push(`metadata ${explanation.metadata_score.toFixed(3)}`);
        if (typeof explanation.concept_boost === "number") labels.push(`concept +${explanation.concept_boost.toFixed(3)}`);
        if (typeof explanation.rerank_score === "number" && explanation.rerank_score > 0) labels.push(`rerank +${explanation.rerank_score.toFixed(3)}`);
        return labels.join(" · ");
      }

      function renderMatchedConcepts(container, concepts = []) {
        if (!concepts.length) return;
        const row = document.createElement("div");
        row.className = "concept-chip-row";
        for (const concept of concepts) {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.className = "concept-chip";
          chip.textContent = concept.canonical_name || `Concept ${concept.id}`;
          chip.addEventListener("click", () => {
            switchRailTab("concepts");
            showConceptDetail(concept.id);
          });
          row.appendChild(chip);
        }
        container.appendChild(row);
      }

      function createTinyMeta(label, value) {
        const item = document.createElement("span");
        item.className = "tiny-meta";
        item.textContent = `${label}: ${value}`;
        return item;
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
        const latestRun = payload.latest_run ? `${payload.latest_run.run_type}: ${payload.latest_run.status}` : "no run";
        const entries = [
          `${payload.documents} docs`,
          `${payload.chunks} chunks`,
          `${payload.embeddings} embeddings`,
          latestRun,
          `refresh: ${refreshLabel}`,
        ];
        for (const value of entries) {
          const row = document.createElement("span");
          row.className = "status-pill";
          row.textContent = value;
          stats.appendChild(row);
        }
        refreshButton.disabled = !payload.refresh_available || Boolean(refreshState.in_progress);
        rerankResultsInput.checked = Boolean(payload.enable_reranking);
        conceptBoostResultsInput.checked = Boolean(payload.enable_concept_boost);
        setTopK(payload.top_k);
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

      function createSourceCard(item, className = "source") {
        const card = document.createElement("div");
        card.className = className;
        const section = item.section_title ? ` · ${item.section_title}` : "";
        const title = document.createElement("div");
        title.className = className === "search-result" ? "search-title" : "source-title";
        title.textContent = `${item.document_title}${section}`;
        const path = document.createElement("div");
        path.className = className === "search-result" ? "search-path" : "source-path";
        path.textContent = item.source_path;
        const snippet = document.createElement("div");
        snippet.className = className === "search-result" ? "search-snippet" : "source-snippet";
        snippet.textContent = item.snippet || "";
        const meta = document.createElement("div");
        meta.className = className === "search-result" ? "search-meta" : "source-meta";
        const score = typeof item.final_score === "number" ? `Final score: ${item.final_score.toFixed(3)}` : "";
        const metadata = typeof item.metadata_score === "number" ? ` · metadata: ${item.metadata_score.toFixed(3)}` : "";
        const rerank = typeof item.rerank_score === "number" && item.rerank_score > 0 ? ` · rerank: ${item.rerank_score.toFixed(3)}` : "";
        const ref = item.source_ref || item.source_path;
        const diagnostics = compactScoreExplanation(item.score_explanation || {});
        meta.textContent = className === "search-result"
          ? [score, metadata.trim(), rerank.trim(), diagnostics].filter(Boolean).join(" ")
          : [ref, `${score}${metadata}${rerank}`, diagnostics].filter(Boolean).join("\n");
        const actions = document.createElement("div");
        actions.className = "action-row";
        const pathButton = document.createElement("button");
        pathButton.type = "button";
        pathButton.className = "ghost";
        pathButton.textContent = "Copy Path";
        pathButton.addEventListener("click", () => copyText(item.source_path, "Source path copied."));
        const refButton = document.createElement("button");
        refButton.type = "button";
        refButton.className = "ghost";
        refButton.textContent = className === "search-result" ? "Copy Section Ref" : "Copy Source Ref";
        refButton.addEventListener("click", () => copyText(ref, "Source reference copied."));
        const markdownButton = document.createElement("button");
        markdownButton.type = "button";
        markdownButton.className = "ghost";
        markdownButton.textContent = "Copy Markdown";
        markdownButton.addEventListener("click", () => copyText(item.markdown_ref || ref, "Markdown reference copied."));
        const openLink = document.createElement("a");
        openLink.className = "ghost";
        openLink.textContent = "Open Hook";
        openLink.href = `obsidian://open?path=${encodeURIComponent(item.source_path)}`;
        actions.append(pathButton, refButton, markdownButton, openLink);
        card.append(title, path, snippet, meta);
        renderMatchedConcepts(card, item.matched_concepts || []);
        card.appendChild(actions);
        return card;
      }

      function createWorkspace(question, filters) {
        const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        const workspace = {
          id,
          question,
          answer: "Retrieving evidence...",
          status: "loading",
          answer_mode: "",
          sources: [],
          retrieval_query: "",
          filters,
          provider: providerSelect.value,
          model: synthesisModelInput.value.trim(),
          warnings: [],
          rerank: rerankResultsInput.checked,
          concept_boost: conceptBoostResultsInput.checked,
          top_k: readTopK(),
          created_at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        };
        answerWorkspaces.unshift(workspace);
        activeWorkspaceId = id;
        renderAnswerWorkspaces();
        return workspace;
      }

      function activeWorkspace() {
        return answerWorkspaces.find((item) => item.id === activeWorkspaceId) || null;
      }

      function workspaceStatusLabel(workspace) {
        if (workspace.status === "loading") return "Retrieving";
        if (workspace.status === "error") return "Error";
        return workspace.answer_mode === "llm_synthesis" ? "LLM answer" : "Extractive";
      }

      function renderAnswerWorkspaces() {
        renderAnswerTabs();
        renderAnswerDetail();
      }

      function renderAnswerTabs() {
        if (!answerWorkspaces.length) {
          answerTabs.innerHTML = "";
          const empty = document.createElement("div");
          empty.className = "empty";
          empty.textContent = "No answers yet.";
          answerTabs.appendChild(empty);
          return;
        }
        answerTabs.innerHTML = "";
        for (const workspace of answerWorkspaces) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = `answer-tab${workspace.id === activeWorkspaceId ? " active" : ""}`;
          const title = document.createElement("div");
          title.className = "answer-tab-title";
          title.textContent = workspace.question;
          const meta = document.createElement("div");
          meta.className = "answer-tab-meta";
          meta.textContent = `${workspaceStatusLabel(workspace)} · ${workspace.sources.length} sources · ${workspace.created_at}`;
          button.append(title, meta);
          button.addEventListener("click", () => {
            activeWorkspaceId = workspace.id;
            renderAnswerWorkspaces();
          });
          answerTabs.appendChild(button);
        }
      }

      function appendMetaItem(container, label, value) {
        const item = document.createElement("div");
        item.className = "answer-meta-item";
        item.textContent = `${label}: ${value || "none"}`;
        container.appendChild(item);
      }

      function renderDetailSection(parent, title, items, renderer, open = false) {
        const details = document.createElement("details");
        details.className = "answer-section";
        details.open = open;
        const summary = document.createElement("summary");
        summary.textContent = title;
        const body = document.createElement("div");
        body.className = "answer-section-body";
        if (!items || !items.length) {
          const empty = document.createElement("div");
          empty.className = "empty";
          empty.textContent = "None.";
          body.appendChild(empty);
        } else {
          for (const item of items) {
            body.appendChild(renderer(item));
          }
        }
        details.append(summary, body);
        parent.appendChild(details);
      }

      function renderAnswerDetail() {
        const workspace = activeWorkspace();
        answerDetail.className = "answer-detail";
        answerDetail.innerHTML = "";
        if (!workspace) {
          answerDetail.className = "answer-detail empty-state";
          answerDetail.textContent = "Ask a question to create an answer workspace.";
          return;
        }

        const card = document.createElement("section");
        card.className = "answer-card";
        const question = document.createElement("div");
        question.className = "answer-question";
        question.textContent = workspace.question;
        const answer = document.createElement("div");
        answer.className = "answer-text";
        answer.textContent = workspace.answer;
        card.append(question, answer);
        answerDetail.appendChild(card);

        const metaGrid = document.createElement("div");
        metaGrid.className = "answer-meta-grid";
        appendMetaItem(metaGrid, "Mode", workspaceStatusLabel(workspace));
        appendMetaItem(metaGrid, "Provider", workspace.provider || "unknown");
        appendMetaItem(metaGrid, "Model", workspace.model || "default");
        appendMetaItem(metaGrid, "Rerank", workspace.rerank ? "on" : "off");
        appendMetaItem(metaGrid, "Concept boost", workspace.concept_boost ? "on" : "off");
        appendMetaItem(metaGrid, "Sources", workspace.top_k || workspace.sources.length);
        answerDetail.appendChild(metaGrid);

        renderDetailSection(answerDetail, `Sources (${workspace.sources.length})`, workspace.sources, (item) => createSourceCard(item), true);
        renderDetailSection(
          answerDetail,
          "Retrieval Details",
          [
            `Retrieval query: ${workspace.retrieval_query || workspace.question}`,
            `Filters: ${filterLabels(workspace.filters || {}).join(" · ") || "none"}`,
          ],
          (item) => {
            const row = document.createElement("div");
            row.className = "source-meta";
            row.textContent = item;
            return row;
          },
        );
        renderDetailSection(
          answerDetail,
          `Warnings (${workspace.warnings.length})`,
          workspace.warnings,
          (item) => {
            const row = document.createElement("div");
            row.className = "warning-item";
            row.textContent = item;
            return row;
          },
        );
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
          searchResults.appendChild(createSourceCard(item, "search-result"));
        }
      }

      function createConceptCard(item) {
        const card = document.createElement("div");
        card.className = "source concept-card";
        const title = document.createElement("div");
        title.className = "source-title";
        title.textContent = item.canonical_name;
        const meta = document.createElement("div");
        meta.className = "source-meta";
        meta.append(
          createTinyMeta("type", item.entity_type || "concept"),
          createTinyMeta("quality", item.quality || "unknown"),
          createTinyMeta("mentions", item.mention_count || 0),
          createTinyMeta("docs", item.document_count || 0),
        );
        const methods = document.createElement("div");
        methods.className = "mini-meta";
        methods.textContent = `Methods: ${(item.extraction_methods || []).join(", ") || "none"}`;
        const actions = document.createElement("div");
        actions.className = "action-row";
        const detailButton = document.createElement("button");
        detailButton.type = "button";
        detailButton.className = "ghost";
        detailButton.textContent = "Inspect";
        detailButton.addEventListener("click", () => showConceptDetail(item.id));
        const searchButton = document.createElement("button");
        searchButton.type = "button";
        searchButton.className = "ghost";
        searchButton.textContent = "Search";
        searchButton.addEventListener("click", () => {
          searchQueryInput.value = item.canonical_name;
          switchRailTab("search");
          searchForm.requestSubmit();
        });
        actions.append(detailButton, searchButton);
        card.append(title, meta, methods, actions);
        return card;
      }

      function renderConcepts(items) {
        if (!items.length) {
          conceptResults.className = "sources empty";
          conceptResults.textContent = "No concepts matched.";
          return;
        }
        conceptResults.className = "sources";
        conceptResults.innerHTML = "";
        for (const item of items) {
          conceptResults.appendChild(createConceptCard(item));
        }
      }

      function createConceptDetail(detail) {
        const wrapper = document.createElement("div");
        wrapper.className = "concept-detail";
        const title = document.createElement("div");
        title.className = "source-title";
        title.textContent = detail.canonical_name;
        const meta = document.createElement("div");
        meta.className = "source-meta";
        meta.append(
          createTinyMeta("type", detail.entity_type || "concept"),
          createTinyMeta("quality", detail.quality || "unknown"),
          createTinyMeta("mentions", detail.mention_count || 0),
        );
        wrapper.append(title, meta);

        const chunks = document.createElement("div");
        chunks.className = "sources";
        for (const chunk of (detail.top_chunks || []).slice(0, 5)) {
          const item = {
            document_title: chunk.document_title,
            source_path: chunk.source_path,
            section_title: chunk.section_title,
            snippet: chunk.chunk_snippet,
            source_ref: chunk.source_ref,
            markdown_ref: chunk.markdown_ref,
          };
          chunks.appendChild(createSourceCard(item));
        }
        if (chunks.children.length) {
          const label = document.createElement("div");
          label.className = "control-group-title";
          label.textContent = "Supporting chunks";
          wrapper.append(label, chunks);
        }

        const docs = document.createElement("div");
        docs.className = "mini-meta";
        docs.textContent = `Documents: ${(detail.related_documents || []).map((item) => `${item.document_title} (${item.mention_count})`).join(" · ") || "none"}`;
        wrapper.appendChild(docs);
        return wrapper;
      }

      async function loadConcepts() {
        conceptsButton.disabled = true;
        try {
          const params = new URLSearchParams();
          if (conceptSearchInput.value.trim()) params.set("search", conceptSearchInput.value.trim());
          params.set("type", conceptTypeInput.value);
          params.set("limit", "50");
          if (conceptQualityInput.value) params.set("quality", conceptQualityInput.value);
          if (conceptMethodInput.value.trim()) params.set("method", conceptMethodInput.value.trim());
          const response = await fetch(`/api/concepts?${params.toString()}`);
          const payload = await response.json();
          if (!response.ok) throw new Error(formatErrorMessage(payload.error));
          renderConcepts(payload.concepts || []);
        } catch (error) {
          conceptResults.className = "sources empty";
          conceptResults.textContent = `Concept load failed: ${error}`;
        } finally {
          conceptsButton.disabled = false;
        }
      }

      async function showConceptDetail(conceptId) {
        if (!conceptId) return;
        conceptResults.className = "sources";
        conceptResults.innerHTML = "";
        const loading = document.createElement("div");
        loading.className = "source";
        loading.textContent = "Loading concept...";
        conceptResults.appendChild(loading);
        try {
          const response = await fetch(`/api/concepts/${conceptId}`);
          const detail = await response.json();
          if (!response.ok) throw new Error(formatErrorMessage(detail.error));
          conceptResults.innerHTML = "";
          conceptResults.appendChild(createConceptDetail(detail));
        } catch (error) {
          conceptResults.className = "sources empty";
          conceptResults.textContent = `Concept detail failed: ${error}`;
        }
      }

      function renderEvalResults(payload) {
        const cases = payload.cases || [];
        if (!cases.length) {
          evalResults.className = "sources empty";
          evalResults.textContent = "No cases were evaluated.";
          return;
        }
        evalResults.className = "sources";
        evalResults.innerHTML = "";
        const summary = document.createElement("div");
        summary.className = "source eval-summary";
        summary.textContent = `${payload.status}: ${payload.passed}/${payload.total} passed`;
        evalResults.appendChild(summary);
        for (const item of cases) {
          const card = document.createElement("div");
          card.className = `source eval-case ${item.ok ? "passed" : "failed"}`;
          const title = document.createElement("div");
          title.className = "source-title";
          title.textContent = `${item.ok ? "Pass" : "Fail"} · ${item.id}`;
          const query = document.createElement("div");
          query.className = "source-snippet";
          query.textContent = item.query;
          const meta = document.createElement("div");
          meta.className = "source-meta";
          meta.textContent = [
            `Expected paths: ${(item.expected_paths || []).join(", ") || "none"}`,
            `Expected terms: ${(item.expected_terms || []).join(", ") || "none"}`,
            `Top paths: ${(item.top_paths || []).join(" · ") || "none"}`,
          ].join("\n");
          card.append(title, query, meta);
          evalResults.appendChild(card);
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

      helpButton.addEventListener("click", () => {
        if (helpDialog && typeof helpDialog.showModal === "function") {
          const helpScroll = helpDialog.querySelector(".help-dialog-scroll");
          if (helpScroll) {
            helpScroll.scrollTop = 0;
          }
          helpDialog.showModal();
        }
      });

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
        const workspace = createWorkspace(query, filters);
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
              rerank: rerankResultsInput.checked,
              concept_boost: conceptBoostResultsInput.checked,
              top_k: readTopK(),
              provider: providerSelect.value,
              model: synthesisModelInput.value.trim(),
              filters,
            }),
          });
          const payload = await response.json();
          if (!response.ok) {
            const errorMessage = formatErrorMessage(payload.error);
            workspace.status = "error";
            workspace.answer = errorMessage;
            workspace.sources = [];
            workspace.retrieval_query = payload.retrieval_query || "";
            workspace.warnings = [errorMessage];
            renderWarnings([errorMessage]);
            renderAnswerWorkspaces();
            return;
          }
          rememberQuery(query);
          workspace.status = "ready";
          workspace.answer = payload.answer;
          workspace.answer_mode = payload.answer_mode || "";
          workspace.sources = payload.sources || [];
          workspace.retrieval_query = payload.retrieval_query || query;
          workspace.provider = payload.provider || workspace.provider;
          workspace.model = payload.model || workspace.model;
          workspace.warnings = payload.warnings || [];
          workspace.rerank = Boolean(payload.rerank);
          workspace.concept_boost = Boolean(payload.concept_boost);
          workspace.top_k = readTopK();
          renderAnswerWorkspaces();
        } catch (error) {
          workspace.status = "error";
          workspace.answer = `Request failed: ${error}`;
          workspace.warnings = [`Request failed: ${error}`];
          renderWarnings([`Request failed: ${error}`]);
          renderAnswerWorkspaces();
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
          params.set("top_k", String(readTopK()));
          appendFiltersToParams(params);
          if (rerankResultsInput.checked) params.set("rerank", "true");
          if (conceptBoostResultsInput.checked) params.set("concept_boost", "true");
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
        entries.unshift({ name, query, filters: readFilters(), top_k: readTopK() });
        saveStoredList(SAVED_SEARCHES_KEY, entries.slice(0, 8));
        savedSearchNameInput.value = "";
        renderSavedSearches();
      });

      conceptsForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        await loadConcepts();
      });

      evalForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        evalButton.disabled = true;
        try {
          const raw = evalCasesInput.value.trim();
          const parsed = raw ? JSON.parse(raw) : DEFAULT_EVAL_CASES;
          const cases = Array.isArray(parsed) ? parsed : parsed.cases;
          const response = await fetch("/api/eval/retrieval", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              cases,
              top_k: readTopK(),
              rerank: evalRerankInput.checked,
              concept_boost: evalConceptBoostInput.checked,
            }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(formatErrorMessage(payload.error));
          renderEvalResults(payload);
        } catch (error) {
          evalResults.className = "sources empty";
          evalResults.textContent = `Retrieval checks failed: ${error}`;
        } finally {
          evalButton.disabled = false;
        }
      });

      clearFiltersButton.addEventListener("click", () => setFilters({}));
      for (const input of [filterTagsInput, filterAliasesInput, filterPathPrefixInput, filterDateFromInput, filterDateToInput]) {
        input.addEventListener("input", renderActiveFilters);
      }
      topKInput.addEventListener("change", () => setTopK(topKInput.value));
      for (const button of mainViewButtons) {
        button.addEventListener("click", () => switchRailTab(button.dataset.mainView));
      }

      loadStatus();
      renderRecentQueries();
      renderSavedSearches();
      evalCasesInput.value = JSON.stringify(DEFAULT_EVAL_CASES, null, 2);
      providerSelect.addEventListener("change", syncProviderState);
      renderAnswerWorkspaces();
      renderActiveFilters();
      switchRailTab("answers");
