// Overview: who is studying, where to continue, track progress, how the site teaches.
import { app, el, L, t } from "../core.js";
import { prog, lessonState, summary } from "../progress.js";
import { setContext } from "../ask.js";

export default function home(root, { curriculum, builds }) {
  const sm = summary();
  const all = curriculum.tracks.flatMap((tr) => tr.lessons);
  const next = all.find((l) => l.status !== "planned" && lessonState(l.id)?.status !== "done");
  const hu = app.lang === "hu";
  const name = app.person[0].toUpperCase() + app.person.slice(1);

  const wrap = el("div.wrap.wide");
  root.append(wrap);
  wrap.append(el("div.hero",
    el("div.kicker", "REZONATING · STUDY · ", name.toUpperCase()),
    el("h1", hu ? `Szia ${name}! Rezgésből adat, alkatrészenként.` : `Hi ${name}. From vibration to data, one part at a time.`),
    el("p", hu
      ? "Két pálya: hogyan működik a mi rendszerünk, és elektronika a nulláról a saját NYÁK-ig. Minden a mi alkatrészeinkre és a pulton mért számainkra épül."
      : "Two tracks: how our system works, and electronics from zero to our own PCB. Everything is built on our parts and the numbers we measured on the bench."),
    el("div.meta-row",
      next ? el("a.btn.primary", { href: `#/lesson/${next.id}` }, `${sm.lessons_done ? t("continue") : t("start")}: ${next.code} ${L(next.title)} →`) : null,
      el("a.btn", { href: "#/parts" }, "◫ ", t("parts")),
      el("a.btn", { href: "#/cards" }, "⧉ ", t("cards"), sm.cards_due ? ` · ${sm.cards_due}` : ""))));

  wrap.append(el("div.card",
    el("div.tag", t("progress"), " · ", hu ? "Obsidian: 10 Project/Study/" + name + ".md" : "Obsidian: 10 Project/Study/" + name + ".md"),
    el("div.stat-row",
      stat(`${sm.lessons_done}/${sm.lessons_total}`, t("lessonsDone")),
      stat(sm.quiz_avg == null ? "–" : `${sm.quiz_avg} %`, t("quizAvg")),
      stat(sm.cards_known, t("cardsKnown")),
      stat(sm.cards_due, t("cardsDue")),
      stat(`${sm.parts_seen}/18`, hu ? "alkatrész" : "parts studied"),
      stat(sm.cases_solved, hu ? "megoldott eset" : "cases solved"))));

  wrap.append(el("div.label-line", hu ? "Pályák" : "Tracks"));
  wrap.append(el("div.grid2", curriculum.tracks.map((tr) => {
    const done = tr.lessons.filter((l) => lessonState(l.id)?.status === "done").length;
    const first = tr.lessons.find((l) => lessonState(l.id)?.status !== "done") || tr.lessons[0];
    return el("a.card.track-card", { href: `#/lesson/${first.id}`, style: { borderBottom: "1px solid var(--line)", color: "inherit" } },
      el("div.tag", `${tr.code} · ${tr.lessons.length} ${t("lessons").toLowerCase()}`), el("h3", L(tr.title)), el("p.empty", L(tr.blurb)),
      el("div.bar", el("i", { style: { width: `${(100 * done) / tr.lessons.length}%` } })), el("div.mono", { style: { fontSize: "11px", color: "var(--ink-3)", marginTop: "6px" } }, `${done}/${tr.lessons.length}`));
  }), el("a.card.track-card", { href: `#/build/${builds[0]?.id || ""}`, style: { borderBottom: "1px solid var(--line)", color: "inherit" } },
    el("div.tag", `3D · 18 ${hu ? "alkatrész" : "parts"} · ${builds.length} ${hu ? "összeállítás" : "builds"}`), el("h3", t("builds")),
    el("p.empty", hu ? "Forgasd, szedd szét, és rakd össze lépésről lépésre a pultot, az első évi node-ot és a HX711-es összehasonlítást." : "Rotate, explode and assemble the bench rig, the Year-1 node and the HX711 comparison step by step."))));

  wrap.append(el("div.label-line", t("howToUse")));
  const key = hu ? [
    ["◇ A pultról", "Minden lecke egy valódi hibával vagy kérdéssel kezdődik a mi pultunkról (pl. a 680 kΩ-os ellenállás)."],
    ["L1 · L2 · L3", "Három mélység: Szemlélet (kép, analógia), Mérnöki (képlet a mi számainkkal), Adatlap (pontos oldal, regiszter)."],
    ["◎ Élő ábra", "Húzd a csúszkákat: a kapcsolás és a grafikon azonnal követi."],
    ["? Előbb tippelj", "Döntsd el, mi történik, mielőtt megnézed a választ. A rossz tipp is tanít."],
    ["Σ Számold ki", "Feladatok a mi alkatrészeinkkel, ellenőrzéssel és levezetéssel."],
    ["⚑ Hibakereső eset", "Valódi hibák a pultról: te választod, mit mérsz, aztán diagnosztizálsz."],
    ["⧉ Kártyák", "Ismétlés időzítve (spaced repetition); minden megnyitott lecke kártyái bekerülnek."],
    ["⌁ Fogalmak", "Az aláhúzott szavakra vidd az egeret; kattintásra rögzül, és Claude (Haiku) bővebben is elmondja."],
  ] : [
    ["◇ From the bench", "Each lesson opens with a real problem or question from our rig (e.g. the 680 kΩ resistor)."],
    ["L1 · L2 · L3", "Three depths: Intuition (pictures, analogies), Engineer (formulas with our numbers), Datasheet (exact page, register)."],
    ["◎ Live diagram", "Drag the sliders: the circuit and the plot follow at once."],
    ["? Predict first", "Commit to what happens before you see the answer. A wrong guess teaches too."],
    ["Σ Calculate", "Problems with our parts, with checking and a worked solution."],
    ["⚑ Fault case", "Real faults from the bench: you choose what to measure, then diagnose."],
    ["⧉ Flashcards", "Spaced repetition; the cards of every lesson you open join your deck."],
    ["⌁ Terms", "Hover the underlined words; click to pin, and Claude (Haiku) can explain more."],
  ];
  wrap.append(el("div.style-key", key.map(([a, b]) => el("div", el("b", a), b))));

  if (prog.state.log.length) {
    wrap.append(el("div.label-line", t("activity")));
    wrap.append(el("div.card", el("div.case-log", prog.state.log.slice(0, 10).map((x) => el("div.e", el("b", x.d), " · ", x.t)))));
  }
  setContext({ title: t("overview"), excerpt: "Study site overview page." });
}

function stat(v, label) { return el("div.stat", el("b", String(v)), el("span", label)); }
