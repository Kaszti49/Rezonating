// The Claude tutor: a side panel and a streaming helper over POST /api/ask (server-sent events).
import { app, el, t, on, toast } from "./core.js";
import { render } from "./md.js";
import { countAsk } from "./progress.js";

const ctx = { title: "", excerpt: "", id: "" };
const history = [];
let mode = "ask";
let busy = false;

export function setContext(c) { Object.assign(ctx, { title: "", excerpt: "", id: "" }, c); paintCtx(); }

/** Stream an answer. onText(fullTextSoFar), resolves with the full text. */
export async function streamAsk({ mode: m = "ask", question, excerpt, title, withHistory = false }, onText = () => {}) {
  const body = {
    mode: m, question, lang: app.lang, person: app.person,
    lesson: { title: title ?? ctx.title, id: ctx.id },
    excerpt: excerpt ?? ctx.excerpt,
    history: withHistory ? history.slice(-4) : [],
  };
  const r = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) throw new Error(r.status === 404 ? t("noClaude") : `HTTP ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "", text = "", model = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let k;
    while ((k = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, k); buf = buf.slice(k + 2);
      if (!chunk.startsWith("data: ")) continue;
      const ev = JSON.parse(chunk.slice(6));
      if (ev.model) model = ev.model;
      if (ev.t) { text += ev.t; onText(text, model); }
      if (ev.error) throw new Error(ev.error);
    }
  }
  countAsk();
  return { text, model };
}

let logEl, ctxEl, ta;

export function mountAsk(root) {
  logEl = el("div.log", el("p.empty", app.lang === "hu"
    ? "Kérdezz bármit. Claude látja az aktuális oldalt, ismeri az alkatrészeinket és a projekt számait."
    : "Ask anything. Claude sees the current page and knows our parts and project numbers."));
  ctxEl = el("div.ctx");
  ta = el("textarea", { placeholder: t("askPlaceholder"), rows: 3 });
  ta.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  const seg = el("div.seg", ["define", "ask", "deep"].map((m) =>
    el(`button${m === mode ? ".on" : ""}`, { type: "button", "data-m": m, title: m === "define" ? "claude-haiku" : m === "ask" ? "claude-sonnet · medium effort" : "claude-opus · high effort",
      onclick: (e) => { mode = m; seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.m === m)); } },
      t(m === "define" ? "quick" : m === "ask" ? "tutor" : "deep"))));
  const form = el("form", { onsubmit: (e) => { e.preventDefault(); submit(); } },
    ctxEl, ta, el("div.row", seg, el("span", { style: { flex: 1 } }), el("button.btn.primary", { type: "submit" }, t("send"))));
  root.replaceChildren(
    el("div.head", el("span.tag", el("b", "Claude"), " · ", app.lang === "hu" ? "tanár" : "tutor"), el("span", { style: { flex: 1 } }),
      el("button.btn.ghost", { type: "button", onclick: () => toggleAsk(false) }, "×")),
    logEl, form);
  paintCtx();
}

function paintCtx() { if (ctxEl) ctxEl.textContent = ctx.title ? t("pageContext") + ctx.title : ""; }

export function toggleAsk(open, prefill) {
  const shell = document.getElementById("shell");
  const want = open ?? !shell.classList.contains("ask-open");
  shell.classList.toggle("ask-open", want);
  if (want) { if (prefill) ta.value = prefill; setTimeout(() => ta.focus(), 30); }
}

async function submit() {
  const q = ta.value.trim();
  if (!q || busy) return;
  busy = true;
  ta.value = "";
  logEl.querySelector(".empty")?.remove();
  const a = el("div.a.blink");
  const meta = el("div.model", t("thinking"));
  logEl.append(el("div.q", q), meta, a);
  logEl.scrollTop = logEl.scrollHeight;
  try {
    const { text, model } = await streamAsk({ mode, question: q, withHistory: true }, (txt, model) => {
      meta.textContent = model;
      a.innerHTML = render(txt);
      logEl.scrollTop = logEl.scrollHeight;
    });
    meta.textContent = model;
    history.push({ q, a: text });
  } catch (e) {
    a.innerHTML = "";
    a.append(el("p.err", String(e.message || e)));
  } finally {
    a.classList.remove("blink");
    busy = false;
  }
}

on((what) => { if (what === "lang" && logEl) { ta.placeholder = t("askPlaceholder"); paintCtx(); } });
export { toast };
