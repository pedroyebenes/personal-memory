import { h } from "./h.js";

const SAFE_PROTOCOLS = new Set(["http:", "https:", "mailto:", "obsidian:"]);

export function renderMarkdown(text) {
  const root = h("div", { class: "pm-md" });
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (i === 0 && line.trim() === "---" && hasClosingFrontmatter(lines)) {
      const block = [];
      i += 1;
      while (i < lines.length && lines[i].trim() !== "---") {
        block.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      root.appendChild(h("pre", { class: "pm-md-frontmatter" }, block.join("\n")));
      continue;
    }

    const fence = line.match(/^(```|~~~)\s*(.*)$/);
    if (fence) {
      const marker = fence[1];
      const lang = fence[2].trim();
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith(marker)) {
        code.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;
      const codeEl = h("code", lang ? { class: `language-${cssSafeName(lang)}` } : null, code.join("\n"));
      root.appendChild(h("pre", { class: "pm-md-code" }, codeEl));
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const level = Math.min(heading[1].length, 6);
      const el = h(`h${level}`);
      appendInline(el, heading[2]);
      root.appendChild(el);
      i += 1;
      continue;
    }

    if (/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)) {
      root.appendChild(h("hr"));
      i += 1;
      continue;
    }

    if (/^\s{0,3}>\s?/.test(line)) {
      const quoted = [];
      while (i < lines.length && (/^\s{0,3}>\s?/.test(lines[i]) || !lines[i].trim())) {
        quoted.push(lines[i].replace(/^\s{0,3}>\s?/, ""));
        i += 1;
      }
      root.appendChild(h("blockquote", null, renderMarkdown(quoted.join("\n"))));
      continue;
    }

    const listStart = parseListItem(line);
    if (listStart) {
      const tag = listStart.ordered ? "ol" : "ul";
      const list = h(tag);
      while (i < lines.length) {
        const item = parseListItem(lines[i]);
        if (!item || item.ordered !== listStart.ordered) break;
        const li = h("li");
        appendInline(li, item.text);
        list.appendChild(li);
        i += 1;
      }
      root.appendChild(list);
      continue;
    }

    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i], i)) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    const p = h("p");
    appendInline(p, paragraph.join(" "));
    root.appendChild(p);
  }

  return root;
}

function startsBlock(line, index) {
  if (index === 0 && line.trim() === "---") return true;
  return /^(```|~~~)/.test(line)
    || /^(#{1,6})\s+/.test(line)
    || /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line)
    || /^\s{0,3}>\s?/.test(line)
    || Boolean(parseListItem(line));
}

function hasClosingFrontmatter(lines) {
  let looksYaml = false;
  for (let j = 1; j < Math.min(lines.length, 80); j++) {
    const line = lines[j].trim();
    if (line === "---") return looksYaml;
    if (/^[A-Za-z0-9_-]+:\s*/.test(line) || /^-\s+/.test(line)) looksYaml = true;
  }
  return false;
}

function parseListItem(line) {
  const unordered = line.match(/^\s{0,3}[-*+]\s+(.+)$/);
  if (unordered) return { ordered: false, text: unordered[1] };
  const ordered = line.match(/^\s{0,3}\d+[.)]\s+(.+)$/);
  if (ordered) return { ordered: true, text: ordered[1] };
  return null;
}

function appendInline(parent, text) {
  const pattern = /(`[^`]+`|\[\[[^\]]+\]\]|\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    appendInlineToken(parent, match[0]);
    last = match.index + match[0].length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function appendInlineToken(parent, token) {
  if (token.startsWith("`")) {
    parent.appendChild(h("code", null, token.slice(1, -1)));
    return;
  }

  if (token.startsWith("[[")) {
    const raw = token.slice(2, -2);
    const [target, label = target] = raw.split("|");
    parent.appendChild(h("a", {
      class: "pm-md-wikilink",
      href: `obsidian://open?path=${encodeURIComponent(target.trim())}`,
    }, label.trim()));
    return;
  }

  const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
  if (link) {
    const href = safeHref(link[2].trim());
    const attrs = href ? { href } : { role: "link", "aria-disabled": "true" };
    const anchor = h("a", attrs);
    appendInline(anchor, link[1]);
    parent.appendChild(anchor);
    return;
  }

  if (token.startsWith("**") || token.startsWith("__")) {
    const strong = h("strong");
    appendInline(strong, token.slice(2, -2));
    parent.appendChild(strong);
    return;
  }

  const em = h("em");
  appendInline(em, token.slice(1, -1));
  parent.appendChild(em);
}

function safeHref(raw) {
  if (!raw) return null;
  if (raw.startsWith("#") || raw.startsWith("/")) return raw;
  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin === window.location.origin && !/^[a-z][a-z0-9+.-]*:/i.test(raw)) return raw;
    return SAFE_PROTOCOLS.has(url.protocol) ? url.href : null;
  } catch (_) {
    return null;
  }
}

function cssSafeName(value) {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
}
