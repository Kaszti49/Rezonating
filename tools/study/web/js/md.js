// A small Markdown renderer for lesson prose, plus the study-site extensions:
//   [[term-id]] or [[term-id|label]]   glossary hover term
//   {{part:id}}                         inline chip linking to a 3D part
//   {{w:widget-id key=value …}}         live diagram (block, on its own line)
//   {{predict:N}} {{calc:N}}            interactive blocks from the lesson JSON (block)
//   $$ formula $$                       formula block (one line, or $$ on its own lines around several)
//   > text  /  > [!warn] text  /  > [!ok] text     callouts
import { esc } from "./core.js";

function inline(src) {
  const codes = [];
  let s = src.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s);
  s = s.replace(/\[\[([a-z0-9][\w-]*)(?:\|([^\]]+))?\]\]/gi, (_, id, label) =>
    `<span class="term" data-term="${id.toLowerCase()}">${label || ""}</span>`);
  s = s.replace(/\{\{part:([\w-]+)(?:\|([^}]+))?\}\}/g, (_, id, label) =>
    `<a class="chip part-chip" data-part="${id}" href="#/part/${id}"><i></i>${label || id}</a>`);
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<em>$2</em>");
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, txt, url) => {
    const safe = /^(https?:|#|\/)/.test(url) ? url : "#";
    const ext = /^https?:/.test(safe) ? ' target="_blank" rel="noopener"' : "";
    return `<a href="${safe}"${ext}>${txt}</a>`;
  });
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
  return s;
}

function parseArgs(str) {
  const args = {};
  for (const m of (str || "").matchAll(/([\w-]+)=("[^"]*"|\S+)/g)) args[m[1]] = m[2].replace(/^"|"$/g, "");
  return args;
}

export function render(md) {
  const lines = String(md || "").replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  const para = [];
  const flush = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para.length = 0; } };

  while (i < lines.length) {
    const line = lines[i];
    const tr = line.trim();

    if (!tr) { flush(); i++; continue; }

    // slots
    let m = tr.match(/^\{\{(w|predict|calc|case):([\w-]+)\s*(.*?)\}\}$/);
    if (m) {
      flush();
      out.push(`<div class="slot" data-kind="${m[1]}" data-id="${esc(m[2])}" data-args='${esc(JSON.stringify(parseArgs(m[3])))}'></div>`);
      i++; continue;
    }
    // code fence
    if (tr.startsWith("```")) {
      flush();
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    // formula
    if (tr.startsWith("$$")) {
      flush();
      if (tr.length > 4 && tr.endsWith("$$")) { out.push(`<div class="formula">${inline(tr.slice(2, -2).trim())}</div>`); i++; continue; }
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("$$")) buf.push(inline(lines[i++].trim()));
      i++;
      out.push(`<div class="formula">${buf.join("<br>")}</div>`);
      continue;
    }
    // heading
    m = tr.match(/^(#{2,4})\s+(.*)$/);
    if (m) { flush(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); i++; continue; }
    // hr
    if (/^(-{3,}|\*{3,})$/.test(tr)) { flush(); out.push("<hr>"); i++; continue; }
    // callout
    if (tr.startsWith(">")) {
      flush();
      const buf = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) buf.push(lines[i++].trim().replace(/^>\s?/, ""));
      let cls = "";
      const k = buf[0]?.match(/^\[!(\w+)\]\s*/);
      if (k) { cls = ` class="${k[1].toLowerCase()}"`; buf[0] = buf[0].slice(k[0].length); }
      out.push(`<blockquote${cls}>${render(buf.join("\n"))}</blockquote>`);
      continue;
    }
    // table
    if (tr.startsWith("|") && lines[i + 1]?.trim().match(/^\|[\s:|-]+\|$/)) {
      flush();
      const row = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = row(tr);
      i += 2;
      const body = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) body.push(row(lines[i++]));
      out.push(`<table><thead><tr>${head.map((h) => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${
        body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    // lists
    if (/^([-*]|\d+[.)])\s+/.test(tr)) {
      flush();
      const ordered = /^\d/.test(tr);
      const items = [];
      while (i < lines.length) {
        const l = lines[i];
        const lt = l.trim();
        if (/^([-*]|\d+[.)])\s+/.test(lt) && !/^\s{2,}/.test(l)) { items.push(lt.replace(/^([-*]|\d+[.)])\s+/, "")); i++; }
        else if (lt && /^\s{2,}/.test(l) && items.length) { items[items.length - 1] += "\n" + l.replace(/^\s{2,4}/, ""); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.map((it) => {
        const [first, ...rest] = it.split("\n");
        return `<li>${inline(first)}${rest.length ? render(rest.join("\n")) : ""}</li>`;
      }).join("")}</${tag}>`);
      continue;
    }
    para.push(tr);
    i++;
  }
  flush();
  return out.join("\n");
}

/** Split a lesson Markdown file into sections by "## @name" markers: {bench, intuition, engineer, datasheet}. */
export function sections(md) {
  const res = {};
  let cur = "_";
  for (const line of String(md || "").replace(/\r/g, "").split("\n")) {
    const m = line.match(/^##\s*@(\w+)\s*$/);
    if (m) { cur = m[1].toLowerCase(); res[cur] = ""; continue; }
    res[cur] = (res[cur] || "") + line + "\n";
  }
  return res;
}

/** Plain text of rendered HTML, for Claude's page context. */
export function plain(html) {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d.textContent.replace(/\n{3,}/g, "\n\n").trim();
}
