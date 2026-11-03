// Shared state, i18n, DOM helpers and content loading.

const store = (() => {
  try { return window.localStorage; } catch { return null; }
})();
const get = (k, d) => { try { return store?.getItem(k) ?? d; } catch { return d; } };
const set = (k, v) => { try { store?.setItem(k, v); } catch { /* private mode */ } };

export const app = {
  lang: get("rz.lang", "en") === "hu" ? "hu" : "en",
  person: ["kaszti", "viktor"].includes(get("rz.person", "")) ? get("rz.person") : "",
  route: { name: "home", id: "" },
  listeners: new Set(),
};

export function on(fn) { app.listeners.add(fn); return () => app.listeners.delete(fn); }
export function emit(what) { app.listeners.forEach((fn) => fn(what)); }

export function setLang(lang) { app.lang = lang; set("rz.lang", lang); document.documentElement.lang = lang; emit("lang"); }
export function setPerson(p) { app.person = p; set("rz.person", p); emit("person"); }

/** Pick the current language from {en, hu} (falls back to the other language, then to the value itself). */
export function L(v) {
  if (v == null) return "";
  if (typeof v === "string") return v;
  return v[app.lang] ?? v.en ?? v.hu ?? "";
}

const UI = {
  overview: ["Overview", "Áttekintés"],
  system: ["How the system works", "Hogyan működik a rendszer"],
  electronics: ["Electronics, zero to PCB", "Elektronika a nulláról a NYÁK-ig"],
  parts: ["Parts in 3D", "Alkatrészek 3D-ben"],
  builds: ["Build it", "Építsd össze"],
  practice: ["Practice", "Gyakorlás"],
  cases: ["Fault cases", "Hibakereső esetek"],
  cards: ["Flashcards", "Kártyák"],
  glossary: ["Glossary", "Fogalomtár"],
  ask: ["Ask Claude", "Kérdezd Claude-ot"],
  who: ["Who is studying?", "Ki tanul most?"],
  bench: ["From the bench", "A pultról"],
  intuition: ["Intuition", "Szemlélet"],
  engineer: ["Engineer", "Mérnöki"],
  datasheet: ["Datasheet", "Adatlap"],
  predict: ["Predict first", "Előbb tippelj"],
  calc: ["Calculate", "Számold ki"],
  quiz: ["Check yourself", "Ellenőrizd magad"],
  reveal: ["Reveal", "Mutasd"],
  check: ["Check", "Ellenőrzés"],
  showSolution: ["Show solution", "Megoldás"],
  markDone: ["Mark lesson done", "Lecke kész"],
  done: ["Done", "Kész"],
  started: ["Started", "Elkezdve"],
  planned: ["Being written", "Készül"],
  minutes: ["min", "perc"],
  usedParts: ["Parts in this lesson", "Alkatrészek ebben a leckében"],
  open3d: ["Open in 3D", "Megnyitás 3D-ben"],
  askMore: ["Ask Claude for more", "Kérj többet Claude-tól"],
  lessons: ["Lessons", "Leckék"],
  pins: ["Pins", "Lábak"],
  explode: ["Explode", "Szétszedés"],
  labels: ["Labels", "Feliratok"],
  dims: ["Dimensions", "Méretek"],
  reset: ["Reset view", "Nézet alaphelyzet"],
  step: ["Step", "Lépés"],
  play: ["Play", "Lejátszás"],
  next: ["Next", "Tovább"],
  prev: ["Back", "Vissza"],
  due: ["due", "esedékes"],
  again: ["Again", "Újra"],
  hard: ["Hard", "Nehéz"],
  good: ["Good", "Jó"],
  easy: ["Easy", "Könnyű"],
  showBack: ["Show answer", "Válasz mutatása"],
  noCards: ["No cards due. Open lessons to add their cards to your deck.", "Nincs esedékes kártya. Nyiss meg leckéket, és a kártyáik bekerülnek a paklidba."],
  saved: ["saved to Obsidian", "mentve Obsidianbe"],
  saving: ["saving…", "mentés…"],
  saveErr: ["not saved (server?)", "nincs mentve (szerver?)"],
  send: ["Ask", "Kérdezem"],
  thinking: ["thinking", "gondolkodik"],
  askPlaceholder: ["Ask anything about this page, our parts or electronics…", "Kérdezz bármit erről az oldalról, az alkatrészeinkről vagy az elektronikáról…"],
  pageContext: ["Claude sees: ", "Claude látja: "],
  quick: ["Quick · Haiku", "Gyors · Haiku"],
  tutor: ["Tutor · Sonnet", "Tanár · Sonnet"],
  deep: ["Deep · Opus", "Mély · Opus"],
  close: ["Close", "Bezár"],
  search: ["Search terms…", "Keresés…"],
  measure: ["Measure / do", "Mérés / lépés"],
  diagnose: ["Your diagnosis", "A diagnózisod"],
  solved: ["Solved", "Megoldva"],
  restart: ["Start again", "Újrakezdés"],
  status: ["Status", "Állapot"],
  have: ["in the lab", "a laborban"],
  needed: ["still needed", "még kell"],
  later: ["later (own PCB)", "később (saját NYÁK)"],
  ordered: ["ordered", "megrendelve"],
  fromNote: ["From the vault note", "A vault jegyzetből"],
  progress: ["Progress", "Haladás"],
  cardsKnown: ["cards known", "ismert kártya"],
  cardsDue: ["cards due", "esedékes kártya"],
  quizAvg: ["quiz average", "kvíz átlag"],
  lessonsDone: ["lessons done", "kész lecke"],
  howToUse: ["How this site teaches", "Hogyan tanít ez az oldal"],
  continue: ["Continue", "Folytatás"],
  start: ["Start", "Kezdés"],
  activity: ["Recent", "Legutóbb"],
  correct: ["Correct", "Helyes"],
  notQuite: ["Not quite", "Nem egészen"],
  tolerance: ["within", "tűrés"],
  tryAgain: ["Try again", "Próbáld újra"],
  yourAnswer: ["your answer", "a válaszod"],
  hint: ["Hint", "Tipp"],
  noClaude: ["The tutor needs the local server: run python tools/study/serve.py", "A tanárhoz a helyi szerver kell: python tools/study/serve.py"],
  explodeHint: ["drag to rotate · scroll to zoom · hover a pin", "húzd a forgatáshoz · görgess a nagyításhoz · vidd az egeret egy lábra"],
};
export function t(key) { const v = UI[key]; return v ? v[app.lang === "hu" ? 1 : 0] : key; }

/** Tiny hyperscript: el("div.card#x", {onclick}, child, "text"). */
export function el(sel, attrs, ...kids) {
  const m = sel.match(/^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i);
  const node = document.createElement(m?.[1] || "div");
  (m?.[2]?.match(/[.#][\w-]+/g) || []).forEach((p) => (p[0] === "." ? node.classList.add(p.slice(1)) : (node.id = p.slice(1))));
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "html") node.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return node;
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const cache = new Map();
/** Fetch a JSON or text file under /content (cached). */
export function load(path, kind = "json") {
  if (!cache.has(path)) {
    cache.set(path, fetch(`/content/${path}`, { cache: "no-cache" }).then((r) => {
      if (!r.ok) throw new Error(`${path}: ${r.status}`);
      return kind === "json" ? r.json() : r.text();
    }).catch((e) => { cache.delete(path); throw e; }));
  }
  return cache.get(path);
}

export function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function toast(msg, ms = 2200) {
  const n = el("div.toast", msg);
  document.body.append(n);
  setTimeout(() => n.remove(), ms);
}

/** Number formatting with SI prefixes: si(0.00048, "V") -> "480 µV". */
export function si(x, unit = "", digits = 3) {
  if (!isFinite(x)) return "–";
  if (x === 0) return `0 ${unit}`.trim();
  const pre = [[1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]];
  const a = Math.abs(x);
  const [f, p] = pre.find(([f]) => a >= f * 0.9995) || pre[pre.length - 1];
  const v = x / f;
  const s = Math.abs(v) >= 100 ? v.toFixed(Math.max(0, digits - 3)) : Math.abs(v) >= 10 ? v.toFixed(Math.max(0, digits - 2)) : v.toFixed(Math.max(0, digits - 1));
  return `${s.replace(/\.0+$|(\.\d*?)0+$/, "$1")} ${p}${unit}`.trim();
}
