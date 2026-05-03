import { h } from "../lib/h.js";
import { stripMarkdown } from "../lib/strip-markdown.js";

const ORP_THRESHOLDS = [
  { max: 1, pos: 0 }, { max: 5, pos: 1 }, { max: 8, pos: 2 },
  { max: 12, pos: 3 }, { max: Infinity, pos: 4 },
];
const PAUSE_SENTENCE = 220, PAUSE_COMMA = 120, BONUS_VERY_LONG = 120, BONUS_LONG = 70;
const FONT_STEP = 0.3, FONT_MIN = 2.2, FONT_MAX = 8.0;

function injectStyles() {
  if (document.getElementById("rsvp-reader-styles")) return;
  const s = document.createElement("style");
  s.id = "rsvp-reader-styles";
  s.textContent = `
.rsvp-reader { display: flex; flex-direction: column; gap: var(--pm-sp-3); }

.rsvp-stage {
  position: relative;
  background: var(--pm-bg-inset);
  border-radius: var(--pm-radius-lg);
  border: 1px solid var(--pm-border);
  height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  transition: border-color var(--pm-dur-fast) var(--pm-ease);
}
.rsvp-stage.rsvp-playing { border-color: var(--pm-accent-line); }

.rsvp-anchor {
  position: absolute;
  top: 0; bottom: 0;
  width: 1px;
  background: var(--pm-accent-line);
  left: 50%;
  pointer-events: none;
}

.rsvp-word-wrap {
  position: absolute;
  left: 50%;
  top: 50%;
  display: inline-block;
  white-space: nowrap;
  pointer-events: none;
}

.rsvp-word {
  font-family: var(--pm-font-serif);
  color: var(--pm-fg);
  line-height: 1.1;
  pointer-events: none;
}
.rsvp-word .rsvp-orp { color: var(--pm-accent); }

.rsvp-prompt {
  color: var(--pm-fg-muted);
  font-size: var(--pm-text-sm);
  text-align: center;
  pointer-events: none;
  padding: var(--pm-sp-4);
}

.rsvp-stage-footer {
  position: absolute;
  bottom: var(--pm-sp-2);
  left: 0; right: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--pm-sp-3);
  pointer-events: none;
}
.rsvp-stage-footer > * { pointer-events: auto; }

.rsvp-progress {
  font-size: var(--pm-text-xs);
  color: var(--pm-fg-muted);
  font-variant-numeric: tabular-nums;
  min-width: 7ch;
  text-align: right;
}

.rsvp-play-btn {
  background: var(--pm-accent-soft);
  border: 1px solid var(--pm-accent-line);
  color: var(--pm-accent);
  border-radius: var(--pm-radius-pill);
  padding: 2px var(--pm-sp-3);
  font-size: var(--pm-text-xs);
  cursor: pointer;
  line-height: 1.8;
  min-width: 6ch;
  text-align: center;
}
.rsvp-play-btn:hover { background: var(--pm-accent-line); }

.rsvp-controls { display: flex; flex-direction: column; gap: var(--pm-sp-2); }

.rsvp-ctrl-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--pm-sp-2);
}

.rsvp-ctrl-btn {
  background: transparent;
  border: 1px solid var(--pm-border);
  border-radius: var(--pm-radius-md);
  color: var(--pm-fg-muted);
  padding: 2px var(--pm-sp-2);
  font-size: var(--pm-text-xs);
  cursor: pointer;
  line-height: 1.6;
}
.rsvp-ctrl-btn:hover { background: var(--pm-bg-hover); color: var(--pm-fg); }

.rsvp-wpm-input {
  width: 52px;
  background: var(--pm-bg-inset);
  border: 1px solid var(--pm-border);
  border-radius: var(--pm-radius-md);
  color: var(--pm-fg);
  font-size: var(--pm-text-xs);
  padding: 2px var(--pm-sp-1);
  text-align: center;
}

.rsvp-sep {
  width: 1px; height: 1em;
  background: var(--pm-border);
  flex-shrink: 0;
}

.rsvp-label {
  font-size: var(--pm-text-xs);
  color: var(--pm-fg-muted);
  display: flex;
  align-items: center;
  gap: var(--pm-sp-1);
  cursor: pointer;
}
.rsvp-label input[type=checkbox] { accent-color: var(--pm-accent); }
`;
  document.head.appendChild(s);
}

function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

function orpIndex(word) {
  const len = (word.replace(/[^a-zA-Z]/g, "") || word).length;
  for (const t of ORP_THRESHOLDS) if (len <= t.max) return t.pos;
  return 4;
}

export function buildRsvpReader(rawText, documentId, { onClose, onPrev, onNext } = {}) {
  injectStyles();

  const text = stripMarkdown(rawText || "");
  const posKey = `rsvp-pos-${documentId}`;

  let tokens = [], idx = 0;
  let wpm = 350, smartPause = true, pairShort = true, fontSize = 4.2;
  let displayHeld = false, spaceHeld = false, btnPlaying = false;
  let timer = null, _mc = null;

  // DOM refs built imperatively so we have direct handles
  const wordDisplayEl = document.createElement("div");
  wordDisplayEl.className = "rsvp-word";
  wordDisplayEl.style.fontSize = `clamp(${Math.max(2.2, fontSize - 1.1)}rem, 6vw, ${fontSize}rem)`;

  const wordWrapEl = document.createElement("div");
  wordWrapEl.className = "rsvp-word-wrap";
  wordWrapEl.appendChild(wordDisplayEl);

  const anchorEl = h("div", { class: "rsvp-anchor" });
  const promptEl = h("p", { class: "rsvp-prompt" }, "Hold the stage or press Space to read");
  const progressEl = h("span", { class: "rsvp-progress" }, "—");
  const playBtn = h("button", { class: "rsvp-play-btn", type: "button" }, "▶ Play");
  const stageFooter = h("div", { class: "rsvp-stage-footer" }, [progressEl, playBtn]);
  const stageEl = h("div", { class: "rsvp-stage" }, [anchorEl, wordWrapEl, promptEl, stageFooter]);

  const wpmDownBtn = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "WPM −25" }, "−");
  const wpmInput = h("input", { class: "rsvp-wpm-input", type: "number", min: "100", max: "900", value: String(wpm) });
  const wpmUpBtn   = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "WPM +25" }, "+");
  const backBtn    = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Back 1 word" }, "⏮");
  const rewindBtn  = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Back 10 words" }, "⏪ 10");
  const fwdBtn     = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Forward 1 word" }, "⏭");

  const chkSmart = document.createElement("input");
  chkSmart.type = "checkbox"; chkSmart.checked = true;
  const chkPair = document.createElement("input");
  chkPair.type = "checkbox"; chkPair.checked = true;

  const fontDownBtn = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Smaller text" }, "A−");
  const fontUpBtn   = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Larger text" }, "A+");
  const saveBtn     = h("button", { class: "rsvp-ctrl-btn", type: "button" }, "Save position");

  const gotoInput = h("input", { class: "rsvp-wpm-input", type: "number", min: "1", placeholder: "#", title: "Jump to word number" });
  gotoInput.style.width = "52px";

  const smartLabel = h("label", { class: "rsvp-label" }, [chkSmart, "Smart pauses"]);
  const pairLabel  = h("label", { class: "rsvp-label" }, [chkPair, "Pair short"]);

  const row2Children = [
    smartLabel, pairLabel,
    h("span", { class: "rsvp-sep" }),
    fontDownBtn, fontUpBtn,
    h("span", { class: "rsvp-sep" }),
    saveBtn,
  ];
  if (onPrev || onNext) {
    row2Children.push(h("span", { class: "rsvp-sep" }));
    if (onPrev) {
      const prevBtn = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Previous document" }, "← doc");
      prevBtn.addEventListener("click", onPrev);
      row2Children.push(prevBtn);
    }
    if (onNext) {
      const nextBtn = h("button", { class: "rsvp-ctrl-btn", type: "button", title: "Next document" }, "doc →");
      nextBtn.addEventListener("click", onNext);
      row2Children.push(nextBtn);
    }
  }
  if (onClose) {
    const closeBtn = h("button", { class: "rsvp-ctrl-btn", type: "button" }, "✕ Close");
    closeBtn.addEventListener("click", onClose);
    row2Children.push(closeBtn);
  }

  const controlsEl = h("div", { class: "rsvp-controls" }, [
    h("div", { class: "rsvp-ctrl-row" }, [
      wpmDownBtn, wpmInput, wpmUpBtn,
      h("span", { class: "rsvp-sep" }),
      backBtn, rewindBtn, fwdBtn,
      h("span", { class: "rsvp-sep" }),
      gotoInput,
    ]),
    h("div", { class: "rsvp-ctrl-row" }, row2Children),
  ]);

  const root = h("div", { class: "rsvp-reader" }, [stageEl, controlsEl]);

  // Core logic
  function tokenize(txt) {
    const raw = txt.match(/\S+/g) || [];
    if (!pairShort) return raw;
    const isShort = w => w.replace(/[^a-zA-Z0-9]/g, "").length <= 2;
    const hasTail = w => /[.!?,;:—]$/.test(w);
    const out = []; let i = 0;
    while (i < raw.length) {
      if (i + 1 < raw.length && isShort(raw[i]) && isShort(raw[i + 1]) && !hasTail(raw[i])) {
        out.push(raw[i] + " " + raw[i + 1]); i += 2;
      } else { out.push(raw[i]); i++; }
    }
    return out;
  }

  function measureW(str) {
    if (!_mc) _mc = document.createElement("canvas");
    const ctx = _mc.getContext("2d");
    ctx.font = getComputedStyle(wordDisplayEl).font;
    return ctx.measureText(str).width;
  }

  function showWord(word) {
    if (!word) { wordDisplayEl.innerHTML = ""; return; }
    const oi = orpIndex(word), b = word.slice(0, oi), o = word[oi] || "", a = word.slice(oi + 1);
    wordDisplayEl.innerHTML =
      (b ? `<span>${esc(b)}</span>` : "") +
      (o ? `<span class="rsvp-orp">${esc(o)}</span>` : "") +
      (a ? `<span>${esc(a)}</span>` : "");
    wordWrapEl.style.transform = `translate(-${measureW(b) + (o ? measureW(o) / 2 : 0)}px, -50%)`;
  }

  function baseMsPerWord() { return 60000 / wpm; }
  function extraPauseMs(w) {
    if (!smartPause) return 0;
    const ms = /[.!?]$/.test(w) ? PAUSE_SENTENCE : /[,;:—]$/.test(w) ? PAUSE_COMMA : 0;
    const l = w.replace(/[^a-zA-Z]/g, "").length;
    return ms + (l >= 12 ? BONUS_VERY_LONG : l >= 9 ? BONUS_LONG : 0);
  }

  function isPlaying() { return displayHeld || spaceHeld || btnPlaying; }
  function clearTimer() { if (timer) { clearTimeout(timer); timer = null; } }

  function updateUI() {
    const playing = isPlaying();
    playBtn.textContent = playing ? "⏸ Pause" : "▶ Play";
    progressEl.textContent = tokens.length ? `${idx + 1} / ${tokens.length}` : "—";
    stageEl.classList.toggle("rsvp-playing", playing);
  }

  function scheduleNext() {
    clearTimer();
    if (!isPlaying() || !tokens.length) return;
    timer = setTimeout(() => {
      if (!isPlaying()) return;
      if (idx < tokens.length - 1) {
        idx++;
        showWord(tokens[idx]);
        updateUI();
        if (idx % 10 === 0) savePos();
        scheduleNext();
      } else {
        btnPlaying = false; displayHeld = false; spaceHeld = false; updateUI();
      }
    }, baseMsPerWord() + extraPauseMs(tokens[idx]));
  }

  function startPlayback() { if (!tokens.length) return; updateUI(); scheduleNext(); }
  function pausePlayback() { clearTimer(); updateUI(); }

  function stepBack()  { if (!tokens.length) return; if (idx > 0) idx--; showWord(tokens[idx]); updateUI(); if (isPlaying()) scheduleNext(); }
  function stepFwd()   { if (!tokens.length) return; if (idx < tokens.length - 1) idx++; showWord(tokens[idx]); updateUI(); if (isPlaying()) scheduleNext(); }
  function rewindTen() { if (!tokens.length) return; idx = Math.max(0, idx - 10); showWord(tokens[idx]); updateUI(); if (isPlaying()) scheduleNext(); }

  function setWpm(v) {
    wpm = Math.max(100, Math.min(900, v));
    wpmInput.value = String(wpm);
  }

  function adjustFont(delta) {
    fontSize = Math.max(FONT_MIN, Math.min(FONT_MAX, fontSize + delta));
    wordDisplayEl.style.fontSize = `clamp(${Math.max(2.2, fontSize - 1.1)}rem, 6vw, ${fontSize}rem)`;
    _mc = null;
    if (tokens.length) showWord(tokens[idx]);
  }

  function savePos() {
    if (tokens.length && documentId != null) localStorage.setItem(posKey, String(idx));
  }

  function retokenize() {
    if (!tokens.length) return;
    const old = tokens[idx];
    tokens = tokenize(text);
    const ni = tokens.findIndex(t => t.includes(old));
    idx = Math.max(0, Math.min(ni >= 0 ? ni : idx, tokens.length - 1));
    showWord(tokens[idx]);
    updateUI();
    if (isPlaying()) scheduleNext();
  }

  // Initialize
  tokens = tokenize(text);
  if (tokens.length) {
    const saved = parseInt(localStorage.getItem(posKey) || "0", 10);
    idx = (saved > 0 && saved < tokens.length) ? saved : 0;
    promptEl.style.display = "none";
    requestAnimationFrame(() => { showWord(tokens[idx]); updateUI(); });
  } else {
    wordWrapEl.style.display = "none";
    promptEl.textContent = "No readable text in this document.";
  }

  // Hold-to-play on stage
  stageEl.addEventListener("pointerdown", e => {
    if (e.target.closest(".rsvp-stage-footer")) return;
    if (!tokens.length) return;
    e.preventDefault();
    stageEl.setPointerCapture(e.pointerId);
    const was = isPlaying(); displayHeld = true;
    if (!was) startPlayback(); else updateUI();
  });
  function releaseHold() {
    if (!displayHeld) return; displayHeld = false;
    if (!btnPlaying && !spaceHeld) pausePlayback(); else updateUI();
  }
  stageEl.addEventListener("pointerup", releaseHold);
  stageEl.addEventListener("pointercancel", releaseHold);

  // Play button toggle
  playBtn.addEventListener("pointerdown", e => e.stopPropagation());
  playBtn.addEventListener("click", e => {
    e.stopPropagation();
    if (!tokens.length) return;
    btnPlaying = !btnPlaying;
    if (btnPlaying) startPlayback();
    else if (!displayHeld && !spaceHeld) pausePlayback();
    else updateUI();
  });

  // WPM controls
  wpmDownBtn.addEventListener("click", e => { e.stopPropagation(); setWpm(wpm - 25); });
  wpmUpBtn.addEventListener("click",   e => { e.stopPropagation(); setWpm(wpm + 25); });
  wpmInput.addEventListener("change", () => setWpm(parseInt(wpmInput.value) || 350));
  wpmInput.addEventListener("keydown", e => e.stopPropagation());
  wpmInput.addEventListener("click", e => e.stopPropagation());

  gotoInput.addEventListener("keydown", e => {
    e.stopPropagation();
    if (e.key === "Enter") {
      const n = parseInt(gotoInput.value);
      if (!isNaN(n) && n >= 1 && n <= tokens.length) {
        idx = n - 1; showWord(tokens[idx]); updateUI();
        if (isPlaying()) scheduleNext();
      }
      gotoInput.value = ""; gotoInput.blur();
    }
  });
  gotoInput.addEventListener("click", e => e.stopPropagation());

  // Navigation
  backBtn.addEventListener("click",   e => { e.stopPropagation(); stepBack(); });
  rewindBtn.addEventListener("click", e => { e.stopPropagation(); rewindTen(); });
  fwdBtn.addEventListener("click",    e => { e.stopPropagation(); stepFwd(); });

  // Options
  chkSmart.addEventListener("change", () => { smartPause = chkSmart.checked; });
  chkPair.addEventListener("change",  () => { pairShort = chkPair.checked; retokenize(); });
  fontDownBtn.addEventListener("click", e => { e.stopPropagation(); adjustFont(-FONT_STEP); });
  fontUpBtn.addEventListener("click",   e => { e.stopPropagation(); adjustFont(FONT_STEP); });
  saveBtn.addEventListener("click", e => {
    e.stopPropagation(); savePos();
    const orig = saveBtn.textContent;
    saveBtn.textContent = "Saved ✓";
    setTimeout(() => { saveBtn.textContent = orig; }, 1500);
  });

  // Document-level keyboard (Space, arrows) — removed on destroy
  function onKeyDown(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    switch (e.key) {
      case " ":
        e.preventDefault();
        if (e.repeat) return;
        if (!spaceHeld) { const was = isPlaying(); spaceHeld = true; if (!was) startPlayback(); else updateUI(); }
        break;
      case "ArrowLeft":  e.preventDefault(); stepBack();         break;
      case "ArrowRight": e.preventDefault(); stepFwd();          break;
      case "ArrowUp":    e.preventDefault(); setWpm(wpm + 25);   break;
      case "ArrowDown":  e.preventDefault(); setWpm(wpm - 25);   break;
    }
  }
  function onKeyUp(e) {
    if (e.key === " " && spaceHeld) {
      spaceHeld = false;
      if (!btnPlaying && !displayHeld) pausePlayback(); else updateUI();
    }
  }
  function onResize() { _mc = null; if (tokens.length) showWord(tokens[idx]); }

  document.addEventListener("keydown", onKeyDown);
  document.addEventListener("keyup",   onKeyUp);
  window.addEventListener("resize",   onResize);

  function destroy() {
    savePos();
    clearTimer();
    displayHeld = false; spaceHeld = false; btnPlaying = false;
    document.removeEventListener("keydown", onKeyDown);
    document.removeEventListener("keyup",   onKeyUp);
    window.removeEventListener("resize",   onResize);
  }

  return { el: root, destroy };
}
