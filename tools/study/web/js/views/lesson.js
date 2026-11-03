// A lesson: bench opener, three depth layers with live diagrams / predict / calc blocks, quiz, cards.
import { app, el, L, t, load } from "../core.js";
import { render, sections, plain } from "../md.js";
import { setContext } from "../ask.js";
import { hydrateTerms } from "../glossary.js";
import { touchLesson, lessonState, markLayer, recordPredict, recordCalc, recordQuiz, markDone } from "../progress.js";
import { mountWidget } from "../widgets/index.js";
import { refreshChrome } from "../app.js";

const LAYERS = ["intuition", "engineer", "datasheet"];
const layerKey = "rz.layer";

export default async function lessonView(root, { id, curriculum }) {
  const all = curriculum.tracks.flatMap((tr) => tr.lessons.map((l) => ({ ...l, track: tr })));
  const idx = all.findIndex((l) => l.id === id);
  const entry = all[idx];
  if (!entry) { root.append(el("div.wrap", el("p", `Unknown lesson ${id}`))); return; }

  let meta, md;
  try {
    meta = await load(`lessons/${id}.json`);
    md = await load(`lessons/${id}.${app.lang}.md`, "text").catch(() => load(`lessons/${id}.${app.lang === "hu" ? "en" : "hu"}.md`, "text"));
  } catch {
    return planned(root, entry, all[idx + 1]);
  }
  const lesson = { ...meta, code: entry.code, title: meta.title || entry.title };
  const sec = sections(md);
  const st = touchLesson(lesson);
  refreshChrome();

  let layer = (() => { try { return localStorage.getItem(layerKey); } catch { return null; } })();
  if (!LAYERS.includes(layer) || !sec[layer]) layer = LAYERS.find((x) => sec[x]) || "intuition";

  const wrap = el("div.wrap");
  root.append(wrap);

  wrap.append(el("div.hero",
    el("div.kicker", `${entry.code} · ${L(entry.track.title)}`),
    el("h1", L(lesson.title)),
    lesson.goal ? el("p", L(lesson.goal)) : null,
    el("div.meta-row",
      el("span.chip", `${lesson.minutes || entry.minutes || 20} ${t("minutes")}`),
      ...(lesson.parts || []).map((p) => el("a.chip.part-chip", { "data-part": p, href: `#/part/${p}` }, el("i", { style: { background: "var(--sage)" } }), p)))));

  if (sec.bench?.trim()) {
    wrap.append(el("div.card.bench", el("div.tag", "◇ ", t("bench")), el("div.prose", { html: render(sec.bench) })));
  }

  const tabs = el("div.layers");
  const body = el("div.prose");
  const hint = el("div.layer-hint");
  wrap.append(tabs, hint, body);

  function paintTabs() {
    tabs.replaceChildren(...LAYERS.filter((x) => sec[x]?.trim()).map((x, i) =>
      el(`button${x === layer ? ".on" : ""}${lessonState(id)?.layers?.[x] ? ".seen" : ""}`, { type: "button", onclick: () => { layer = x; try { localStorage.setItem(layerKey, x); } catch {} paint(); } },
        el("span.n", `L${i + 1}`), t(x))));
    hint.textContent = {
      intuition: app.lang === "hu" ? "Kép és analógia, képlet nélkül." : "Pictures and analogies, no formulas.",
      engineer: app.lang === "hu" ? "Képletek a mi számainkkal." : "Formulas with our numbers.",
      datasheet: app.lang === "hu" ? "Pontos oldal, regiszter, táblázat." : "The exact page, register or table.",
    }[layer];
  }

  function paint() {
    paintTabs();
    markLayer(id, layer);
    body.innerHTML = render(sec[layer] || "");
    hydrateSlots(body, lesson);
    hydrateTerms(body);
    setContext({ id, title: `${entry.code} ${L(lesson.title)} (${t(layer)})`, excerpt: plain(render(sec.bench || "")) + "\n\n" + plain(body.innerHTML) });
    setTimeout(paintTabs, 0);
  }
  paint();

  // quiz
  if (lesson.quiz?.length) wrap.append(el("div.label-line", t("quiz")), quiz(lesson));

  // done bar
  const next = all[idx + 1];
  const doneBtn = el("button.btn.primary", { type: "button", onclick: () => { markDone(lesson); doneBtn.disabled = true; doneBtn.textContent = "✓ " + t("done"); refreshChrome(); } },
    st.status === "done" ? "✓ " + t("done") : t("markDone"));
  if (st.status === "done") doneBtn.disabled = true;
  wrap.append(el("hr"), el("div.done-bar", doneBtn,
    lesson.cards?.length ? el("span.empty", app.lang === "hu" ? `${lesson.cards.length} kártya került a paklidba` : `${lesson.cards.length} cards are in your deck`) : null,
    el("span", { style: { flex: 1 } }),
    next ? el("a.btn", { href: `#/lesson/${next.id}` }, `${t("next")}: ${next.code} ${L(next.title)} →`) : null));
}

function planned(root, entry, next) {
  root.append(el("div.wrap",
    el("div.hero", el("div.kicker", `${entry.code} · ${L(entry.track.title)}`), el("h1", L(entry.title)),
      el("p", t("planned") + (app.lang === "hu" ? ". Addig kérdezd Claude-ot a témáról." : ". Until then, ask Claude about the topic."))),
    entry.outline ? el("div.card", el("div.tag", "OUTLINE"), el("div.prose", { html: render(L(entry.outline)) })) : null,
    next ? el("a.btn", { href: `#/lesson/${next.id}` }, `${t("next")}: ${next.code} →`) : null));
  setContext({ id: entry.id, title: `${entry.code} ${L(entry.title)}`, excerpt: L(entry.outline) });
}

// ------------------------------------------------------------------------------------------- slots
function hydrateSlots(body, lesson) {
  body.querySelectorAll(".slot").forEach((slot) => {
    const kind = slot.dataset.kind, sid = slot.dataset.id;
    let args = {};
    try { args = JSON.parse(slot.dataset.args || "{}"); } catch {}
    const box = el("div.block");
    slot.replaceWith(box);
    if (kind === "w") mountWidget(sid, box, args);
    else if (kind === "predict") box.append(predict(lesson, +sid));
    else if (kind === "calc") box.append(calc(lesson, +sid));
    else if (kind === "case") {
      const a = el("a.btn", { href: `#/case/${sid}` }, "⚑ ", t("cases"), ": ", sid);
      box.append(a);
      load("cases.json").then((d) => { const c = d.cases.find((x) => x.id === sid); if (c) a.lastChild.textContent = L(c.title); }).catch(() => {});
    }
  });
}

function predict(lesson, n) {
  const p = lesson.predict?.[n];
  if (!p) return el("div.empty", `predict ${n}?`);
  const prev = lessonState(lesson.id)?.predict?.[n];
  const card = el("div.card.predict", el("div.tag", "? ", t("predict")), el("div.prose", { html: render(L(p.q)) }));
  const opts = el("div.opts");
  const why = el("div.why", { html: render(L(p.why)) });
  why.hidden = true;
  const reveal = (choice) => {
    opts.querySelectorAll(".opt").forEach((b, i) => {
      b.disabled = true;
      if (i === p.answer) b.classList.add("right");
      else if (i === choice) b.classList.add("wrong");
      if (i === choice) b.classList.add("pick");
    });
    why.hidden = false;
    hydrateTerms(why);
  };
  (p.options || []).forEach((o, i) => opts.append(el("button.opt", { type: "button", html: render(L(o)).replace(/^<p>|<\/p>$/g, ""),
    onclick: () => { recordPredict(lesson.id, n, i); reveal(i); } })));
  card.append(opts, why);
  if (prev !== undefined) reveal(prev);
  hydrateTerms(card);
  return card;
}

function parseNum(s) {
  const m = String(s).trim().replace(",", ".").match(/^([-+]?\d*\.?\d+(?:e[-+]?\d+)?)\s*([pnuµmkMG]?)/i);
  if (!m) return NaN;
  const f = { p: 1e-12, n: 1e-9, u: 1e-6, "µ": 1e-6, m: 1e-3, k: 1e3, M: 1e6, G: 1e9 }[m[2]] ?? 1;
  return parseFloat(m[1]) * (m[2] ? f : 1);
}

function calc(lesson, n) {
  const c = lesson.calc?.[n];
  if (!c) return el("div.empty", `calc ${n}?`);
  const solved = lessonState(lesson.id)?.calc?.[n];
  const input = el("input", { type: "text", inputmode: "decimal", placeholder: t("yourAnswer") });
  const verdict = el("span.verdict");
  const sol = el("div.why", { html: render(L(c.solution)) });
  sol.hidden = true;
  const hintEl = el("div.why", { html: render(L(c.hint)) });
  hintEl.hidden = true;
  const tol = c.tol ?? 0.03;
  const check = () => {
    // the answer is typed in c.unit (shown next to the box), so only the number counts
    const v = parseNum(input.value.replace(/[a-zµΩ°%/\s]+$/i, ""));
    const ok = isFinite(v) && Math.abs(v - c.answer) <= Math.abs(c.answer) * tol + (c.abs ?? 0);
    verdict.className = "verdict " + (ok ? "ok" : "no");
    verdict.textContent = ok ? `✓ ${t("correct")}` : `✗ ${t("notQuite")} (${t("tolerance")} ±${Math.round(tol * 100)} %)`;
    recordCalc(lesson.id, n, ok);
    if (ok) sol.hidden = false;
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") check(); });
  const card = el("div.card.calc", el("div.tag", "Σ ", t("calc")), el("div.prose", { html: render(L(c.q)) }),
    el("div.in", input, el("span.mono", c.unit || ""), el("button.btn", { type: "button", onclick: check }, t("check")), verdict,
      el("span", { style: { flex: 1 } }),
      c.hint ? el("button.btn.ghost", { type: "button", onclick: () => { hintEl.hidden = !hintEl.hidden; } }, t("hint")) : null,
      el("button.btn.ghost", { type: "button", onclick: () => { sol.hidden = !sol.hidden; hydrateTerms(sol); } }, t("showSolution"))),
    hintEl, sol);
  if (solved) { verdict.className = "verdict ok"; verdict.textContent = `✓ ${t("correct")}`; }
  hydrateTerms(card);
  return card;
}

function quiz(lesson) {
  const qs = lesson.quiz;
  const picks = new Array(qs.length).fill(null);
  const card = el("div.card");
  const score = el("span.score");
  const submit = el("button.btn.primary", { type: "button", disabled: true, onclick: () => {
    const right = qs.reduce((a, q, i) => a + (picks[i] === q.answer ? 1 : 0), 0);
    const pct = Math.round((100 * right) / qs.length);
    recordQuiz(lesson, pct);
    score.textContent = `${right}/${qs.length} · ${pct} %`;
    card.querySelectorAll(".q-block").forEach((b, i) => {
      b.querySelectorAll(".opt").forEach((o, j) => { o.disabled = true; if (j === qs[i].answer) o.classList.add("right"); else if (j === picks[i]) o.classList.add("wrong"); });
      const w = b.querySelector(".why"); if (w) { w.hidden = false; hydrateTerms(w); }
    });
    submit.disabled = true;
    again.hidden = false;
  } }, t("check"));
  const again = el("button.btn", { type: "button", onclick: () => { card.replaceWith(quiz(lesson)); } }, t("tryAgain"));
  again.hidden = true;
  qs.forEach((q, i) => {
    const opts = el("div.opts");
    (q.options || []).forEach((o, j) => opts.append(el("button.opt", { type: "button", html: render(L(o)).replace(/^<p>|<\/p>$/g, ""), onclick: () => {
      picks[i] = j;
      opts.querySelectorAll(".opt").forEach((b, k) => b.classList.toggle("pick", k === j));
      submit.disabled = picks.some((p) => p === null);
    } })));
    const why = q.why ? el("div.why", { html: render(L(q.why)) }) : null;
    if (why) why.hidden = true;
    card.append(el("div.q-block", { style: { margin: i ? "18px 0 0" : 0 } }, el("div.tag", `Q${i + 1}`), el("div.prose", { html: render(L(q.q)) }), opts, why));
  });
  const best = lessonState(lesson.id)?.quiz?.best;
  card.append(el("div.done-bar", { style: { marginTop: "14px" } }, submit, again, score, best != null ? el("span.empty", `best ${best} %`) : null));
  hydrateTerms(card);
  return card;
}
