// Hover definitions for [[terms]] and part names. Hover shows; click pins; "Ask Claude" goes to Haiku.
import { app, el, L, t, load } from "./core.js";
import { render } from "./md.js";
import { streamAsk } from "./ask.js";
import { seeTerm } from "./progress.js";

export let GLOSS = {};
export let PARTS = {};

export async function loadGlossary() {
  const [g, p] = await Promise.all([load("glossary.json").catch(() => ({})), load("parts.json").catch(() => ({ parts: [] }))]);
  GLOSS = g;
  PARTS = Object.fromEntries((p.parts || []).map((x) => [x.id, x]));
}

/** Entry for an id: a glossary term, or a part (by part id). */
export function entry(id) {
  if (GLOSS[id]) return { ...GLOSS[id], id };
  const p = PARTS[id];
  if (p) return { id, term: p.name, short: p.role, part: id, long: p.summary };
  return null;
}

/** Fill empty term labels and mark part terms. */
export function hydrateTerms(root) {
  root.querySelectorAll(".term").forEach((n) => {
    const e = entry(n.dataset.term);
    if (!n.textContent) n.textContent = e ? L(e.term) : n.dataset.term;
    if (e?.part) n.classList.add("part");
    if (!e) n.classList.add("missing");
  });
  root.querySelectorAll(".part-chip").forEach((n) => {
    const p = PARTS[n.dataset.part];
    if (p && n.textContent === n.dataset.part) n.lastChild.textContent = L(p.name);
  });
}

let tip = null, hideT = null, showT = null, pinned = false, cur = null;

function close() { tip?.remove(); tip = null; pinned = false; cur = null; }

function show(node) {
  const id = node.dataset.term || node.dataset.part;
  if (cur === node && tip) return;
  close();
  cur = node;
  const e = entry(id);
  seeTerm(id);
  const ai = el("div.ai");
  ai.hidden = true;
  const askBtn = el("button.btn", { type: "button", onclick: async () => {
    pinned = true;
    ai.hidden = false;
    ai.classList.add("blink");
    ai.textContent = "";
    askBtn.disabled = true;
    try {
      const word = e ? L(e.term) : id;
      await streamAsk({ mode: "define", question: word, excerpt: e ? `${L(e.short)} ${L(e.long)}` : "" }, (txt) => { ai.innerHTML = render(txt); });
    } catch (err) { ai.textContent = String(err.message || err); }
    ai.classList.remove("blink");
  } }, t("askMore"), el("span.mono", { style: { color: "var(--ink-3)", marginLeft: "6px" } }, "haiku"));
  const links = [];
  if (e?.part || PARTS[id]) links.push(el("a.chip", { href: `#/part/${e?.part || id}`, onclick: close }, el("i", { style: { background: "var(--sage)" } }), t("open3d")));
  for (const ls of e?.lessons || []) links.push(el("a.chip", { href: `#/lesson/${ls}`, onclick: close }, ls.toUpperCase().split("-")[0]));
  tip = el("div.tip",
    el("div.tag", e?.part ? (app.lang === "hu" ? "alkatrész" : "part") : (app.lang === "hu" ? "fogalom" : "term"), e?.abbr ? ` · ${e.abbr}` : ""),
    el("h4", e ? L(e.term) : id),
    e ? el("div.short", { html: render(L(e.short)) }) : el("div.short", app.lang === "hu" ? "Ez még nincs a fogalomtárban." : "Not in the glossary yet."),
    e?.long ? el("div.long", { html: render(L(e.long)) }) : null,
    el("div.row", askBtn, ...links),
    ai);
  tip.addEventListener("mouseenter", () => clearTimeout(hideT));
  tip.addEventListener("mouseleave", () => { if (!pinned) hideT = setTimeout(close, 250); });
  document.body.append(tip);
  const r = node.getBoundingClientRect();
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = Math.min(window.innerWidth - w - 12, Math.max(12, r.left + r.width / 2 - w / 2));
  let y = r.bottom + 8;
  if (y + h > window.innerHeight - 12) y = Math.max(12, r.top - h - 8);
  tip.style.left = `${x}px`; tip.style.top = `${y}px`;
}

export function initGlossaryHover() {
  document.addEventListener("mouseover", (ev) => {
    const n = ev.target.closest?.(".term");
    if (!n || pinned) return;
    clearTimeout(hideT); clearTimeout(showT);
    showT = setTimeout(() => show(n), 140);
  });
  document.addEventListener("mouseout", (ev) => {
    const n = ev.target.closest?.(".term");
    if (!n) return;
    clearTimeout(showT);
    if (!pinned) hideT = setTimeout(close, 250);
  });
  document.addEventListener("click", (ev) => {
    const n = ev.target.closest?.(".term");
    if (n) { clearTimeout(showT); show(n); pinned = true; return; }
    if (tip && !tip.contains(ev.target)) close();
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") close(); });
  window.addEventListener("hashchange", close);
}
