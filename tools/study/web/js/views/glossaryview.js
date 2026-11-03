// The glossary as a searchable list. Every entry is also a hover term in the lessons.
import { app, el, L, t } from "../core.js";
import { render } from "../md.js";
import { GLOSS, hydrateTerms } from "../glossary.js";
import { setContext } from "../ask.js";

export default function glossary(root) {
  const wrap = el("div.wrap");
  root.append(wrap);
  const q = el("input", { type: "search", placeholder: t("search"), style: { font: "14px var(--sans)", padding: "8px 12px", width: "100%", border: "1px solid var(--line)", borderRadius: "3px", background: "var(--card)" } });
  const list = el("div");
  wrap.append(el("div.hero", el("div.kicker", `${Object.keys(GLOSS).length} TERMS`), el("h1", t("glossary"))), q, list);
  const entries = Object.entries(GLOSS).sort((a, b) => L(a[1].term).localeCompare(L(b[1].term), app.lang));
  function paint() {
    const s = q.value.trim().toLowerCase();
    list.replaceChildren(...entries.filter(([id, g]) => !s || `${id} ${g.term?.en} ${g.term?.hu} ${g.abbr || ""}`.toLowerCase().includes(s)).map(([id, g]) =>
      el("div.card", { style: { margin: "10px 0" } },
        el("div.tag", el("b", L(g.term)), g.abbr ? ` · ${g.abbr}` : "", app.lang === "hu" && g.term?.en ? ` · ${g.term.en}` : ""),
        el("div.prose", { html: render(L(g.short)) }),
        g.long ? el("div.prose", { style: { color: "var(--ink-2)", fontSize: "14px" }, html: render(L(g.long)) }) : null,
        g.lessons?.length || g.part ? el("div.meta-row", g.part ? el("a.chip", { href: `#/part/${g.part}` }, "3D") : null, (g.lessons || []).map((l) => el("a.chip", { href: `#/lesson/${l}` }, l.toUpperCase()))) : null)));
    hydrateTerms(list);
  }
  q.addEventListener("input", paint);
  paint();
  setContext({ title: t("glossary"), excerpt: "" });
}
