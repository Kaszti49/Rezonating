// Fault-finding cases: read the symptom, choose measurements, then diagnose.
import { app, el, L, t, load } from "../core.js";
import { render } from "../md.js";
import { prog, solveCase } from "../progress.js";
import { hydrateTerms } from "../glossary.js";
import { setContext } from "../ask.js";
import { refreshChrome } from "../app.js";

export default async function cases(root, { name, id }) {
  const data = await load("cases.json");
  const wrap = el("div.wrap");
  root.append(wrap);
  const hu = app.lang === "hu";
  if (name === "cases" || !id) {
    wrap.append(el("div.hero", el("div.kicker", "FAULT CASES"), el("h1", t("cases")),
      el("p", hu ? "Valódi hibák a mi pultunkról és olyanok, amik a következő lépéseknél várnak ránk. Minden mérés egy lépés: próbáld minél kevesebből." : "Real faults from our bench, and ones waiting for us in the next steps. Every measurement is a step: try to use as few as you can.")));
    wrap.append(el("div.grid2", data.cases.map((c) => {
      const s = prog.state.cases[c.id];
      return el("a.card.track-card", { href: `#/case/${c.id}`, style: { color: "inherit", borderBottom: "1px solid var(--line)" } },
        el("div.tag", `${"●".repeat(c.level || 1)}${"○".repeat(3 - (c.level || 1))} · ${c.real ? (hu ? "megtörtént" : "happened") : (hu ? "várható" : "likely")}`),
        el("h3", L(c.title)), el("p.empty", L(c.teaser)),
        s?.solved ? el("span.chip", { style: { borderColor: "var(--ok)" } }, `✓ ${t("solved")} · ${s.steps} ${hu ? "lépés" : "steps"}`) : null);
    })));
    setContext({ title: t("cases"), excerpt: data.cases.map((c) => L(c.title)).join("; ") });
    return;
  }
  const c = data.cases.find((x) => x.id === id);
  if (!c) { wrap.append(el("p", `Unknown case ${id}`)); return; }
  let steps = 0;
  const done = new Set();
  const logEl = el("div.case-log");
  const acts = el("div.actions");
  const diag = el("div.opts");
  const res = el("div");
  wrap.append(el("div.hero", el("div.kicker", `FAULT CASE · ${c.id}`), el("h1", L(c.title)),
    el("div.meta-row", ...(c.parts || []).map((p) => el("a.chip.part-chip", { "data-part": p, href: `#/part/${p}` }, el("i", { style: { background: "var(--sage)" } }), p)))));
  wrap.append(el("div.card.bench", el("div.tag", "◇ ", hu ? "A helyzet" : "The situation"), el("div.prose", { html: render(L(c.story)) })));
  wrap.append(el("div.label-line", t("measure")), acts, el("div.label-line", hu ? "Napló" : "Log"), el("div.card", logEl), el("div.label-line", t("diagnose")), diag, res);
  logEl.append(el("div.e.empty", hu ? "Még nem mértél semmit." : "Nothing measured yet."));

  c.actions.forEach((a, i) => acts.append(el("button.opt", { type: "button", onclick: (ev) => {
    if (done.has(i)) return;
    done.add(i); steps++;
    ev.currentTarget.disabled = true;
    logEl.querySelector(".empty")?.remove();
    const e = el("div.e", el("b", `${String(steps).padStart(2, "0")} · ${L(a.label)}`), el("div", { html: render(L(a.result)) }));
    logEl.append(e);
    hydrateTerms(e);
  } }, L(a.label))));

  c.diagnoses.forEach((d, i) => diag.append(el("button.opt", { type: "button", onclick: (ev) => {
    const right = !!d.correct;
    ev.currentTarget.classList.add(right ? "right" : "wrong");
    solveCase(c.id, steps, right, L(c.title));
    res.replaceChildren(el("div.card", { style: { borderLeft: `3px solid ${right ? "var(--ok)" : "var(--bad)"}` } },
      el("div.tag", right ? `✓ ${t("correct")} · ${steps} ${hu ? "lépés" : "steps"}` : `✗ ${t("notQuite")}`),
      el("div.prose", { html: render(L(d.why)) }),
      right && c.debrief ? el("div.prose", { html: render(L(c.debrief)) }) : null,
      right && c.lessons?.length ? el("div.meta-row", c.lessons.map((l) => el("a.chip", { href: `#/lesson/${l}` }, l.toUpperCase()))) : null,
      el("div.meta-row", el("a.btn", { href: `#/case/${c.id}`, onclick: () => setTimeout(() => location.reload(), 0) }, t("restart")), el("a.btn", { href: "#/cases" }, t("cases")))));
    hydrateTerms(res);
    if (right) diag.querySelectorAll(".opt").forEach((b) => (b.disabled = true));
    refreshChrome();
  } }, L(d.label))));
  hydrateTerms(wrap);
  setContext({ title: `${t("cases")}: ${L(c.title)}`, excerpt: `${L(c.story)}\n\n(The learner is solving this case; don't give the diagnosis away unless asked directly. Measurements available: ${c.actions.map((a) => L(a.label)).join("; ")})` });
}
