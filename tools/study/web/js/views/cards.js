// Flashcards with spaced repetition. Card ids: "<lessonId>-<n>" (from a lesson) or "g:<termId>" (glossary).
import { app, el, L, t, load, today } from "../core.js";
import { render } from "../md.js";
import { prog, dueCards, gradeCard, save } from "../progress.js";
import { GLOSS } from "../glossary.js";
import { hydrateTerms } from "../glossary.js";
import { setContext } from "../ask.js";
import { refreshChrome } from "../app.js";

async function cardContent(id) {
  if (id.startsWith("g:")) {
    const g = GLOSS[id.slice(2)];
    return g ? { front: g.term, back: { en: `${g.short?.en || ""}\n\n${g.long?.en || ""}`, hu: `${g.short?.hu || ""}\n\n${g.long?.hu || ""}` }, src: "glossary" } : null;
  }
  const lid = id.replace(/-c?\d+$/, "");
  try {
    const meta = await load(`lessons/${lid}.json`);
    const c = (meta.cards || []).find((x) => x.id === id);
    return c ? { ...c, src: lid.toUpperCase() } : null;
  } catch { return null; }
}

export default async function cards(root) {
  const hu = app.lang === "hu";
  const wrap = el("div.wrap");
  root.append(wrap);
  const termsSeen = Object.keys(prog.state.terms || {}).filter((id) => GLOSS[id] && !prog.state.cards[`g:${id}`]);
  wrap.append(el("div.hero", el("div.kicker", "SPACED REPETITION"), el("h1", t("cards")),
    el("p", hu ? "Válaszolj fejben, aztán értékeld magad őszintén. A rendszer ennek alapján ütemezi a következő ismétlést (1, 3, 7, 16, 35… nap)." : "Answer in your head, then grade yourself honestly. That decides the next review (1, 3, 7, 16, 35… days)."),
    el("div.meta-row",
      el("span.chip", `${Object.keys(prog.state.cards).length} ${hu ? "kártya a pakliban" : "cards in deck"}`),
      termsSeen.length ? el("button.btn", { type: "button", onclick: () => { termsSeen.forEach((id) => { prog.state.cards[`g:${id}`] = { box: 0, due: today(), reps: 0, lapses: 0 }; }); save(); refreshChrome(); location.reload(); } },
        hu ? `+ ${termsSeen.length} megnézett fogalom hozzáadása` : `+ add ${termsSeen.length} terms you looked up`) : null)));
  const stage = el("div");
  wrap.append(stage);
  setContext({ title: t("cards"), excerpt: "" });

  const queue = dueCards();
  let i = 0;
  async function next() {
    if (i >= queue.length) { stage.replaceChildren(el("div.card.flash", el("div", el("p", "✓"), el("p.empty", t("noCards"))))); refreshChrome(); return; }
    const id = queue[i];
    const c = await cardContent(id);
    if (!c) { i++; return next(); }
    const back = el("div.back.prose", { html: render(L(c.back)) });
    back.hidden = true;
    const grades = el("div.grades", [["again", 0], ["hard", 1], ["good", 2], ["easy", 3]].map(([k, gr]) =>
      el("button.btn", { type: "button", onclick: () => { gradeCard(id, gr); i++; next(); } }, t(k))));
    grades.hidden = true;
    const showBtn = el("button.btn.primary", { type: "button", onclick: () => { back.hidden = false; grades.hidden = false; showBtn.hidden = true; hydrateTerms(back); } }, t("showBack"));
    const card = el("div.card.flash", el("div",
      el("div.tag", `${c.src} · ${i + 1}/${queue.length}`),
      el("div.prose", { html: render(L(c.front)) }), back));
    stage.replaceChildren(card, el("div.grades", showBtn), grades);
    hydrateTerms(card);
    setContext({ title: `${t("cards")}: ${L(c.front).slice(0, 80)}`, excerpt: `${L(c.front)}\n\n${L(c.back)}` });
  }
  next();
}
