// Per-person study state, synced to 10 Project/Study/<Person>.md through the local server.
import { app, emit, today, L } from "./core.js";

const EMPTY = () => ({ v: 1, lessons: {}, cards: {}, cases: {}, parts: {}, builds: {}, terms: {}, log: [], asked: 0 });

export const prog = {
  state: EMPTY(),
  person: "",
  status: "idle", // idle | saving | saved | error | offline
  curriculum: null, // set by app.js: {tracks:[{id, lessons:[{id,title,status}]}]}
};

let timer = null;

export async function loadProgress(person) {
  prog.person = person;
  prog.state = EMPTY();
  if (!person) return;
  try {
    const r = await fetch(`/api/progress/${person}`);
    if (!r.ok) throw new Error(r.status);
    const j = await r.json();
    prog.state = Object.assign(EMPTY(), j.state || {});
    prog.status = "saved";
  } catch {
    prog.status = "offline";
  }
  emit("progress");
}

function schedule() {
  if (!prog.person) return;
  clearTimeout(timer);
  prog.status = "saving";
  emit("save");
  timer = setTimeout(save, 1500);
}

export async function save() {
  clearTimeout(timer);
  if (!prog.person) return;
  try {
    const r = await fetch(`/api/progress/${prog.person}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: prog.state, summary: summary() }),
      keepalive: true,
    });
    prog.status = r.ok ? "saved" : "error";
  } catch {
    prog.status = "error";
  }
  emit("save");
}
window.addEventListener("pagehide", () => { if (prog.status === "saving") save(); });

function log(text) {
  const s = prog.state;
  const line = { d: today(), t: text };
  if (s.log[0]?.t === text && s.log[0]?.d === line.d) return;
  s.log.unshift(line);
  s.log = s.log.slice(0, 60);
}

// ------------------------------------------------------------------ lessons
export function lessonState(id) { return prog.state.lessons[id] || null; }

export function touchLesson(lesson) {
  const s = prog.state;
  if (!s.lessons[lesson.id]) {
    s.lessons[lesson.id] = { status: "started", opened: today(), layers: {}, predict: {}, calc: {} };
    log(`opened ${lesson.code} ${L(lesson.title)}`);
  }
  // put the lesson's cards in the deck
  for (const c of lesson.cards || []) if (!s.cards[c.id]) s.cards[c.id] = { box: 0, due: today(), reps: 0, lapses: 0 };
  s.lessons[lesson.id].last = today();
  schedule();
  return s.lessons[lesson.id];
}
export function markLayer(id, layer) { const l = prog.state.lessons[id]; if (l && !l.layers[layer]) { l.layers[layer] = 1; schedule(); } }
export function recordPredict(id, n, choice) { const l = prog.state.lessons[id]; if (l) { l.predict[n] = choice; schedule(); } }
export function recordCalc(id, n, ok) { const l = prog.state.lessons[id]; if (l) { l.calc[n] = l.calc[n] || ok; schedule(); } }
export function recordQuiz(lesson, pct) {
  const l = prog.state.lessons[lesson.id];
  if (!l) return;
  l.quiz = { last: pct, best: Math.max(pct, l.quiz?.best ?? 0) };
  log(`quiz ${lesson.code}: ${pct} %`);
  schedule();
}
export function markDone(lesson) {
  const l = prog.state.lessons[lesson.id];
  if (!l) return;
  l.status = "done";
  l.done = today();
  log(`finished ${lesson.code} ${L(lesson.title)}`);
  schedule();
}

// ------------------------------------------------------------------ parts, builds, cases, terms
export function seePart(id, name) { if (!prog.state.parts[id]) { prog.state.parts[id] = today(); log(`studied part ${name}`); schedule(); } }
export function buildStep(id, n, total, name) {
  const b = prog.state.builds[id] || (prog.state.builds[id] = { steps: 0, done: false });
  if (n > b.steps) { b.steps = n; if (n >= total && !b.done) { b.done = true; log(`built ${name}`); } schedule(); }
}
export function solveCase(id, steps, right, name) {
  const c = prog.state.cases[id] || (prog.state.cases[id] = { tries: 0 });
  c.tries += 1;
  if (right && !c.solved) { c.solved = today(); c.steps = steps; log(`solved case: ${name} (${steps} steps)`); }
  schedule();
}
export function seeTerm(id) { if (!prog.state.terms[id]) { prog.state.terms[id] = today(); schedule(); } }
export function countAsk() { prog.state.asked = (prog.state.asked || 0) + 1; schedule(); }

// ------------------------------------------------------------------ flashcards (SM-2 lite, day-based)
const INTERVALS = [0, 1, 3, 7, 16, 35, 80, 180];
function addDays(n) { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
export function dueCards() {
  const now = today();
  return Object.entries(prog.state.cards).filter(([, c]) => c.due <= now).map(([id]) => id);
}
export function gradeCard(id, grade) { // grade: 0 again, 1 hard, 2 good, 3 easy
  const c = prog.state.cards[id];
  if (!c) return;
  c.reps += 1;
  if (grade === 0) { c.lapses += 1; c.box = Math.max(0, c.box - 2); c.due = today(); }
  else { c.box = Math.min(INTERVALS.length - 1, c.box + (grade === 1 ? 0 : grade === 2 ? 1 : 2)); c.due = addDays(Math.max(1, INTERVALS[c.box])); }
  c.last = today();
  schedule();
}

// ------------------------------------------------------------------ summary for the vault note
export function summary() {
  const s = prog.state;
  const all = (prog.curriculum?.tracks || []).flatMap((tr) => tr.lessons.map((l) => ({ ...l, track: tr.id })));
  const byId = Object.fromEntries(all.map((l) => [l.id, l]));
  const rows = Object.entries(s.lessons).map(([id, l]) => ({
    track: byId[id]?.track || "",
    title: byId[id] ? `${byId[id].code} ${byId[id].title?.en || id}` : id,
    status: l.status,
    quiz: l.quiz?.best ?? null,
    date: l.done || l.last || l.opened || "",
    order: all.findIndex((x) => x.id === id),
  })).sort((a, b) => a.order - b.order);
  const quizzes = Object.values(s.lessons).map((l) => l.quiz?.best).filter((x) => x != null);
  const last = Object.entries(s.lessons).sort((a, b) => (b[1].last || "").localeCompare(a[1].last || ""))[0];
  return {
    lessons_done: Object.values(s.lessons).filter((l) => l.status === "done").length,
    lessons_total: all.length,
    quiz_avg: quizzes.length ? Math.round(quizzes.reduce((a, b) => a + b, 0) / quizzes.length) : null,
    cards_known: Object.values(s.cards).filter((c) => c.box >= 3).length,
    cards_due: dueCards().length,
    cases_solved: Object.values(s.cases).filter((c) => c.solved).length,
    parts_seen: Object.keys(s.parts).length,
    last_lesson: last ? (byId[last[0]] ? `${byId[last[0]].code} ${byId[last[0]].title?.en}` : last[0]) : "",
    rows,
    recent: s.log.slice(0, 15).map((x) => `${x.d}: ${x.t}`),
  };
}
