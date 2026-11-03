// App shell: navigation rail, top bar, router, person picker.
import { app, el, L, t, on, load, setLang, setPerson } from "./core.js";
import { prog, loadProgress, lessonState, dueCards } from "./progress.js";
import { mountAsk, toggleAsk, setContext } from "./ask.js";
import { loadGlossary, initGlossaryHover, hydrateTerms, PARTS } from "./glossary.js";

const VIEWS = {
  home: () => import("./views/home.js"),
  lesson: () => import("./views/lesson.js"),
  part: () => import("./views/part.js"),
  parts: () => import("./views/part.js"),
  build: () => import("./views/build.js"),
  cases: () => import("./views/cases.js"),
  case: () => import("./views/cases.js"),
  cards: () => import("./views/cards.js"),
  glossary: () => import("./views/glossaryview.js"),
};

let curriculum = { tracks: [] };
let builds = [];
let cleanup = null;

function parseHash() {
  const [, name = "home", id = ""] = (location.hash || "#/home").match(/^#\/([\w-]*)\/?([\w.-]*)/) || [];
  return { name: VIEWS[name] ? name : "home", id };
}

function rail() {
  const r = app.route;
  const item = (href, code, label, { on: isOn, st, planned } = {}) =>
    el(`a.item${isOn ? ".on" : ""}${planned ? ".planned" : ""}`, { href }, el("span.code", code), el("span", label), st !== undefined ? el(`span.st${st ? "." + st : ""}`) : null);
  const kids = [
    el("div.brand", el("b", "REZONATING"), el("span", "STUDY · v1")),
    item("#/home", "00", t("overview"), { on: r.name === "home" }),
  ];
  for (const tr of curriculum.tracks) {
    const done = tr.lessons.filter((l) => lessonState(l.id)?.status === "done").length;
    kids.push(el("div.group", el("span", L(tr.title)), el("span", `${done}/${tr.lessons.length}`)));
    for (const l of tr.lessons) {
      kids.push(item(`#/lesson/${l.id}`, l.code, L(l.title), {
        on: r.name === "lesson" && r.id === l.id, st: lessonState(l.id)?.status || "", planned: l.status === "planned",
      }));
    }
  }
  kids.push(el("div.group", el("span", t("parts"))));
  kids.push(item("#/parts", "3D", app.lang === "hu" ? "Mind a 18 alkatrész" : "All 18 parts", { on: r.name === "parts" || r.name === "part" }));
  kids.push(el("div.group", el("span", t("builds"))));
  for (const b of builds) kids.push(item(`#/build/${b.id}`, b.code, L(b.title), { on: r.name === "build" && r.id === b.id, st: prog.state.builds[b.id]?.done ? "done" : prog.state.builds[b.id] ? "started" : "" }));
  kids.push(el("div.group", el("span", t("practice"))));
  kids.push(item("#/cases", "FX", t("cases"), { on: r.name === "cases" || r.name === "case" }));
  const due = dueCards().length;
  kids.push(item("#/cards", "SR", `${t("cards")}${due ? ` · ${due} ${t("due")}` : ""}`, { on: r.name === "cards" }));
  kids.push(item("#/glossary", "Aa", t("glossary"), { on: r.name === "glossary" }));
  document.getElementById("rail").replaceChildren(...kids);
}

function top() {
  const status = { saving: t("saving"), saved: t("saved"), error: t("saveErr"), offline: t("saveErr") }[prog.status] || "";
  document.getElementById("top").replaceChildren(
    el("span.crumb", crumb()),
    el("span.sp"),
    el("span.save-dot" + (prog.status === "error" || prog.status === "offline" ? ".err" : ""), status),
    el("div.seg", { title: t("who") }, ["kaszti", "viktor"].map((p) =>
      el(`button${app.person === p ? ".on" : ""}`, { type: "button", onclick: () => choosePerson(p) }, p[0].toUpperCase() + p.slice(1)))),
    el("div.seg", ["en", "hu"].map((lg) => el(`button${app.lang === lg ? ".on" : ""}`, { type: "button", onclick: () => setLang(lg) }, lg.toUpperCase()))),
    el("button.btn.primary", { type: "button", onclick: () => toggleAsk() }, "✦ ", t("ask")),
  );
}

function crumb() {
  const r = app.route;
  if (r.name === "lesson") {
    const l = curriculum.tracks.flatMap((x) => x.lessons).find((x) => x.id === r.id);
    return l ? `${l.code} / ${L(l.title)}` : r.id;
  }
  if (r.name === "part") return `3D / ${L(PARTS[r.id]?.name) || r.id}`;
  if (r.name === "build") return `${t("builds")} / ${L(builds.find((b) => b.id === r.id)?.title) || r.id}`;
  return { home: t("overview"), parts: t("parts"), cases: t("cases"), case: t("cases"), cards: t("cards"), glossary: t("glossary") }[r.name] || "";
}

async function choosePerson(p) {
  setPerson(p);
  await loadProgress(p);
  route();
}

function personGate() {
  const v = document.getElementById("view");
  v.replaceChildren(el("div.wrap",
    el("div.hero", el("div.kicker", "REZONATING · STUDY"), el("h1", t("who")),
      el("p", app.lang === "hu" ? "A haladásod a saját Obsidian jegyzetedbe kerül: 10 Project/Study/." : "Your progress goes into your own Obsidian note: 10 Project/Study/.")),
    el("div.grid2", ["kaszti", "viktor"].map((p) =>
      el("button.card.track-card", { type: "button", style: { textAlign: "left" }, onclick: () => choosePerson(p) },
        el("div.tag", "PERSON"), el("h3", p[0].toUpperCase() + p.slice(1)),
        el("p.empty", p === "kaszti" ? "design · management" : "programming · electronics"))))));
}

export async function route() {
  app.route = parseHash();
  cleanup?.(); cleanup = null;
  rail(); top();
  if (!app.person) { personGate(); return; }
  setContext({ title: crumb(), excerpt: "" });
  const mod = await VIEWS[app.route.name]();
  const v = document.getElementById("view");
  v.replaceChildren();
  window.scrollTo(0, 0);
  try {
    cleanup = (await mod.default(v, { ...app.route, curriculum, builds })) || null;
  } catch (e) {
    console.error(e);
    v.replaceChildren(el("div.wrap", el("div.card", el("div.tag", "ERROR"), el("p", String(e.message || e)))));
  }
  hydrateTerms(v);
}

async function boot() {
  document.documentElement.lang = app.lang;
  [curriculum, builds] = await Promise.all([load("curriculum.json"), load("builds.json").then((b) => b.builds).catch(() => [])]);
  prog.curriculum = curriculum;
  await loadGlossary();
  initGlossaryHover();
  mountAsk(document.getElementById("ask"));
  if (app.person) await loadProgress(app.person);
  window.addEventListener("hashchange", route);
  on((what) => {
    if (what === "lang") { mountAsk(document.getElementById("ask")); route(); }
    if (what === "save") top();
    if (what === "progress") rail();
  });
  route();
}

export function refreshChrome() { rail(); top(); }

boot();
