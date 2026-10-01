// Rezonating dashboard views for Dataview. Tier 2: replaceable, but keep sections stable.
// Usage in a note:  ```dataviewjs  await dv.view("90 Meta/Views/rz", {section: "dashboard"})  ```
// Sections: dashboard, header, kpis, activity, workload, pipeline, milestones, budget, upnext,
//           claude, recent, orderLines, packCard, packWork, weekReview
// Reads only note properties, so every number here can be traced back to a note.

const { DateTime } = dv.luxon;
const SECTION = (input && input.section) || "dashboard";
const root = dv.container;
root.classList.add("rz");
const NOW = DateTime.now().setLocale("en-GB");
const TODAY = NOW.startOf("day");

// ---------- helpers
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Always return a plain JS array (Dataview's DataArray is a Proxy whose methods differ).
const arr = x => {
  if (!x) return [];
  if (typeof x.array === "function") return Array.from(x.array());
  if (x.values && typeof x.values !== "function") return Array.from(x.values);
  if (typeof x[Symbol.iterator] === "function" && typeof x !== "string") return Array.from(x);
  return [];
};
const toDT = v => {
  if (!v) return null;
  if (v.isLuxonDateTime) return v.startOf("day");
  if (typeof v === "string") { const d = DateTime.fromISO(v); return d.isValid ? d.startOf("day") : null; }
  if (v instanceof Date) return DateTime.fromJSDate(v).startOf("day");
  if (typeof v.ts === "number") return DateTime.fromMillis(v.ts).startOf("day");
  return null;
};
const nameOf = l => {
  if (!l) return "";
  const p = typeof l === "string" ? l : (l.path || String(l));
  return p.replace(/^\[\[|\]\]$/g, "").split("|")[0].split("/").pop().replace(/\.md$/, "");
};
const pages = src => arr(dv.pages(src));
const num = v => (v === null || v === undefined || v === "" || isNaN(Number(v))) ? null : Number(v);
const eur = v => "€" + Math.round(v).toLocaleString("en-GB");
const link = (path, text, cls = "") => `<a class="rz-link ${cls}" data-rz-href="${esc(path)}" title="${esc(text)}">${esc(text)}</a>`;
const plink = p => link(p.file.path, p.file.name);
const rel = d => {
  if (!d) return "";
  const n = Math.round(d.diff(TODAY, "days").days);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} d` : `${-n} d late`;
};
const fmt = (d, f = "d LLL") => d ? d.setLocale("en-GB").toFormat(f) : "—";
const card = (title, body, cls = "", extra = "") =>
  `<section class="rz-card ${cls}">${title ? `<header class="rz-card-h"><span>${title}</span>${extra}</header>` : ""}${body}</section>`;
const empty = t => `<div class="rz-empty">${esc(t)}</div>`;

const PEOPLE = {
  kaszti: { n: "Kaszti", i: "K", c: "var(--color-blue)" },
  viktor: { n: "Viktor", i: "V", c: "var(--color-green)" },
  claude: { n: "Claude", i: "C", c: "var(--color-orange)" },
};
const avatar = o => {
  const p = PEOPLE[o] || { n: o || "nobody", i: "?", c: "var(--text-faint)" };
  return `<span class="rz-av" style="--c:${p.c}" title="${esc(p.n)}">${p.i}</span>`;
};
const STATUS = {
  doing: { l: "Doing", c: "var(--color-blue)" },
  review: { l: "Review", c: "var(--color-purple)" },
  todo: { l: "To do", c: "var(--color-yellow)" },
  blocked: { l: "Blocked", c: "var(--color-red)" },
  backlog: { l: "Backlog", c: "var(--text-faint)" },
  done: { l: "Done", c: "var(--color-green)" },
};
const LANES = ["doing", "review", "todo", "blocked", "backlog", "done"];
const pill = s => { const m = STATUS[s] || { l: s || "—", c: "var(--text-faint)" }; return `<span class="rz-pill" style="--c:${m.c}">${esc(m.l)}</span>`; };
const STAGES = ["idea", "design", "data", "model", "on-device", "done"];

try {
// ---------- data
const work = pages('"20 Work"').filter(p => p.type === "work");
const parts = pages('"30 Hardware/Parts"').filter(p => p.type === "part");
const orders = pages('"30 Hardware/Orders"').filter(p => p.type === "order");
const packs = pages('"40 Packs"').filter(p => p.type === "pack").sort((a, b) => (num(a.order_no) ?? 99) - (num(b.order_no) ?? 99));
const exps = pages('"50 Experiments"').filter(p => p.type === "experiment");
const decs = pages('"80 Decisions"').filter(p => p.type === "decision");
const inbox = pages('"00 Inbox"').filter(p => p.type === "inbox" && p.file.name !== "Read me");
const charter = dv.page("10 Project/Charter") || {};
const roadmap = dv.page("10 Project/Roadmap") || {};

const open = work.filter(p => p.status !== "done");
const due = p => toDT(p.due);
const doneOn = p => toDT(p.done);
const overdue = open.filter(p => due(p) && due(p) < TODAY);
const dueSoon = open.filter(p => due(p) && due(p) >= TODAY && due(p) <= TODAY.plus({ days: 7 }));
const weekStart = TODAY.startOf("week");

const orderStatus = Object.fromEntries(orders.map(o => [o.file.name, o.status]));
const lineEur = p => (num(p.price_eur) || 0) * (num(p.qty) || 1);
const isCommitted = p => ["ordered", "have"].includes(p.status) || ["ordered", "delivered"].includes(orderStatus[nameOf(p.order)]);
const plannedEur = parts.filter(p => nameOf(p.order)).reduce((s, p) => s + lineEur(p), 0);
const committedEur = parts.filter(isCommitted).reduce((s, p) => s + lineEur(p), 0);
const budgetEur = num(charter.budget_eur) || 0;
const yStart = toDT(charter.start) || DateTime.fromISO("2026-10-01");
const yEnd = toDT(charter.end) || DateTime.fromISO("2027-06-30");

// ---------- click handling: open notes inside Obsidian
if (!root.dataset.rzBound) {
  root.dataset.rzBound = "1";
  root.addEventListener("click", e => {
    const a = e.target.closest("[data-rz-href]");
    if (!a) return;
    e.preventDefault();
    app.workspace.openLinkText(a.dataset.rzHref, dv.currentFilePath || "", e.ctrlKey || e.metaKey);
  });
}

// ---------- small charts
const bar = (value, max, color = "var(--color-accent)") => {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return `<div class="rz-bar"><i style="width:${pct.toFixed(1)}%;--c:${color}"></i></div>`;
};
const spark = (values, color = "var(--color-accent)") => {
  const w = 120, h = 32, max = Math.max(1, ...values);
  const step = values.length > 1 ? w / (values.length - 1) : w;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 3 - (v / max) * (h - 6)).toFixed(1)}`);
  return `<svg class="rz-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
};
const ring = (fraction, label) => {
  const r = 26, c = 2 * Math.PI * r, f = Math.max(0, Math.min(1, fraction || 0));
  return `<svg class="rz-ring" viewBox="0 0 64 64"><circle cx="32" cy="32" r="${r}" class="rz-ring-bg"/><circle cx="32" cy="32" r="${r}" class="rz-ring-fg" stroke-dasharray="${(c * f).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 32 32)"/><text x="32" y="36" text-anchor="middle">${esc(label)}</text></svg>`;
};

// ---------- sections
const S = {};

S.header = () => {
  const h = NOW.hour;
  const hi = h < 5 ? "Late night, team" : h < 12 ? "Good morning, team" : h < 18 ? "Good afternoon, team" : "Good evening, team";
  const total = Math.max(1, yEnd.diff(yStart, "days").days);
  const gone = Math.max(0, Math.min(total, TODAY.diff(yStart, "days").days));
  const ms = arr(roadmap.milestones).map(m => ({ name: m.name, date: toDT(m.date), kind: m.kind }))
    .filter(m => m.date && m.date >= TODAY).sort((a, b) => a.date - b.date)[0];
  const next = ms ? `<div class="rz-next"><span class="rz-next-n">${Math.round(ms.date.diff(TODAY, "days").days)}</span><span class="rz-next-l">days to<br><b>${esc(ms.name)}</b></span></div>` : "";
  return `<div class="rz-hero">
    <div class="rz-hero-l">
      <div class="rz-brand">REZONATING</div>
      <h1 class="rz-hi">${hi}</h1>
      <div class="rz-sub">${NOW.toFormat("cccc, d LLLL")} · week ${NOW.toFormat("W")} · Year 1, day ${Math.round(gone) + 1} of ${Math.round(total) + 1}</div>
      <div class="rz-year">${bar(gone, total)}<span>${Math.round((gone / total) * 100)}% of Year 1</span></div>
    </div>${next}</div>`;
};

S.kpis = () => {
  const lanes = LANES.filter(l => l !== "done").map(l => [l, open.filter(p => p.status === l).length]);
  const stack = `<div class="rz-stack">${lanes.filter(([, n]) => n).map(([l, n]) => `<i style="flex:${n};--c:${STATUS[l].c}" title="${STATUS[l].l}: ${n}"></i>`).join("")}</div>`;
  const weeks = [...Array(8).keys()].reverse().map(k => {
    const s = weekStart.minus({ weeks: k }), e = s.plus({ weeks: 1 });
    return work.filter(p => doneOn(p) && doneOn(p) >= s && doneOn(p) < e).length;
  });
  const doneWeek = weeks[weeks.length - 1];
  const expDone = exps.filter(e => e.status === "done").length;
  const fp = packs.find(p => p.file.name === "footstep-id");
  const best = fp ? num(fp.best_value) : null, tgt = fp ? num(fp.target_value) : null;
  const k = [
    card("Open work", `<div class="rz-big">${open.length}</div><div class="rz-small">${open.filter(p => p.status === "doing").length} doing · ${open.filter(p => p.status === "blocked").length} blocked</div>${stack}`, "rz-kpi"),
    card("Due in 7 days", `<div class="rz-big">${dueSoon.length}</div><div class="rz-small ${overdue.length ? "rz-bad" : ""}">${overdue.length ? `${overdue.length} overdue` : "nothing overdue"}</div><div class="rz-avs">${Object.keys(PEOPLE).map(o => { const n = dueSoon.filter(p => p.owner === o).length; return n ? `<span>${avatar(o)}<b>${n}</b></span>` : ""; }).join("")}</div>`, "rz-kpi"),
    card("Done this week", `<div class="rz-big">${doneWeek}</div><div class="rz-small">last 8 weeks</div>${spark(weeks, "var(--color-green)")}`, "rz-kpi"),
    card("Budget", `<div class="rz-big">${eur(plannedEur)}</div><div class="rz-small">${eur(committedEur)} committed · ${eur(budgetEur)} total</div><div class="rz-budget">${bar(plannedEur, budgetEur, "color-mix(in srgb, var(--color-accent) 45%, transparent)")}${bar(committedEur, budgetEur)}</div>`, "rz-kpi"),
    card("Experiments", `<div class="rz-big">${expDone}<span class="rz-of">/${exps.length}</span></div><div class="rz-small">done / logged</div><div class="rz-dots">${exps.map(e => `<i class="${esc(e.result || e.status || "")}" title="${esc(e.file.name)}"></i>`).join("")}</div>`, "rz-kpi"),
    card("Footstep ID", `<div class="rz-kpi-ring">${ring(best && tgt ? best / tgt : 0, best !== null ? `${best}%` : "—")}<div class="rz-small">best vs target<br><b>${tgt ?? "—"}%</b></div></div>`, "rz-kpi"),
  ];
  return `<div class="rz-kpis">${k.join("")}</div>`;
};

S.activity = () => {
  // Whole of Year 1, one column per week, GitHub-style. Future days are dimmed.
  const start = yStart.startOf("week"), end = yEnd.endOf("week").startOf("day");
  const days = Math.round(end.diff(start, "days").days) + 1, cols = Math.ceil(days / 7);
  const score = {};
  const add = (d, w) => { if (!d || d < start || d > end) return; const k = d.toISODate(); score[k] = (score[k] || 0) + w; };
  work.forEach(p => add(doneOn(p), 3));
  pages("").filter(p => /^\d\d /.test(p.file.path) && !p.file.path.startsWith("90 Meta/Templates")).forEach(p => {
    add(toDT(p.file.mtime), 1);
    arr(p.file.tasks).forEach(t => { if (t.completed) add(toDT(t.completion), 1); });
  });
  const max = Math.max(1, ...Object.values(score));
  let cells = "";
  for (let i = 0; i < days; i++) {
    const d = start.plus({ days: i }), v = score[d.toISODate()] || 0;
    const lvl = v === 0 ? 0 : Math.min(4, Math.ceil((v / max) * 4));
    const out = d < yStart || d > yEnd;
    cells += `<i class="l${lvl}${d > TODAY ? " fut" : ""}${d.equals(TODAY) ? " now" : ""}${out ? " out" : ""}" title="${fmt(d, "ccc d LLL")}: ${v}"></i>`;
  }
  const months = [...Array(cols).keys()].map(w => {
    const d = start.plus({ weeks: w });
    return `<span>${d.day <= 7 ? fmt(d, "LLL") : ""}</span>`;
  }).join("");
  const total = Object.values(score).reduce((a, b) => a + b, 0);
  const activeDays = Object.keys(score).length;
  return card("Activity · Year 1", `<div class="rz-heat-wrap" style="--cols:${cols}"><div class="rz-heat-m">${months}</div><div class="rz-heat">${cells}</div></div>
    <div class="rz-legend"><span>${activeDays} active day${activeDays === 1 ? "" : "s"} · ${total} points · done work 3, ticked task 1, edited note 1</span><span class="rz-scale">less <i class="l0"></i><i class="l1"></i><i class="l2"></i><i class="l3"></i><i class="l4"></i> more</span></div>`, "rz-span-8");
};

S.workload = () => {
  const rows = Object.keys(PEOPLE).map(o => {
    const mine = work.filter(p => p.owner === o);
    const op = mine.filter(p => p.status !== "done");
    const segs = ["doing", "review", "todo", "blocked", "backlog"].map(l => [l, op.filter(p => p.status === l).length]).filter(([, n]) => n);
    const late = op.filter(p => due(p) && due(p) < TODAY).length;
    return `<div class="rz-wl">${avatar(o)}<div class="rz-wl-b"><div class="rz-wl-t"><b>${PEOPLE[o].n}</b><span>${op.length} open · ${mine.length - op.length} done${late ? ` · <em class="rz-bad">${late} late</em>` : ""}</span></div>
      <div class="rz-stack">${segs.map(([l, n]) => `<i style="flex:${n};--c:${STATUS[l].c}" title="${STATUS[l].l}: ${n}"></i>`).join("") || `<i style="flex:1;--c:var(--background-modifier-border)"></i>`}</div></div></div>`;
  }).join("");
  const legend = ["doing", "review", "todo", "blocked", "backlog"].map(l => `<span><i style="--c:${STATUS[l].c}"></i>${STATUS[l].l}</span>`).join("");
  return card("Workload", rows + `<div class="rz-keys">${legend}</div>`, "rz-span-4");
};

S.pipeline = () => {
  if (!packs.length) return card("Packs", empty("No pack notes yet"), "rz-span-12");
  const head = `<div class="rz-pipe rz-pipe-h"><span></span>${STAGES.map(s => `<span>${s}</span>`).join("")}<span>best / target</span></div>`;
  const rows = packs.map(p => {
    const at = Math.max(0, STAGES.indexOf(p.stage));
    const steps = STAGES.map((s, i) => `<span class="rz-step ${i < at ? "past" : i === at ? "cur" : ""}"><i></i></span>`).join("");
    const best = num(p.best_value), tgt = num(p.target_value);
    const nExp = exps.filter(e => nameOf(e.pack) === p.file.name).length;
    return `<div class="rz-pipe"><span class="rz-pipe-n">${plink(p)}<small>${esc(p.head || "")} · ${nExp} exp</small></span>${steps}<span class="rz-pipe-m"><b>${best ?? "—"}</b> / ${tgt ?? "—"}</span></div>`;
  }).join("");
  return card("Pack pipeline", head + rows, "rz-span-12");
};

S.milestones = () => {
  const ms = arr(roadmap.milestones).map(m => ({ name: m.name, date: toDT(m.date), kind: m.kind || "" })).filter(m => m.date).sort((a, b) => a.date - b.date);
  if (!ms.length) return card("Milestones", empty("Add milestones to 10 Project/Roadmap"), "rz-span-5");
  const KIND = { gate: "var(--color-purple)", hardware: "var(--color-orange)", deadline: "var(--color-red)", data: "var(--color-cyan)" };
  const rows = ms.map(m => {
    const past = m.date < TODAY;
    return `<div class="rz-ms ${past ? "past" : ""}"><i style="--c:${KIND[m.kind] || "var(--color-accent)"}"></i><span class="rz-ms-d">${fmt(m.date)}</span><span class="rz-ms-n">${esc(m.name)}</span><span class="rz-ms-r">${past ? "passed" : rel(m.date)}</span></div>`;
  }).join("");
  return card("Milestones", `<div class="rz-ms-list">${rows}</div>`, "rz-span-5", link("10 Project/Roadmap", "Roadmap →", "rz-more"));
};

S.budget = () => {
  const W = 560, H = 190, L = 44, R = 12, T = 14, B = 26;
  const x = d => L + Math.max(0, Math.min(1, d.diff(yStart, "days").days / Math.max(1, yEnd.diff(yStart, "days").days))) * (W - L - R);
  const maxY = Math.max(budgetEur, plannedEur, 1) * 1.1;
  const y = v => T + (1 - v / maxY) * (H - T - B);
  const series = (dateOf, include) => {
    const ev = orders.map(o => ({ d: dateOf(o), v: parts.filter(p => nameOf(p.order) === o.file.name && include(p, o)).reduce((s, p) => s + lineEur(p), 0) }))
      .filter(e => e.d && e.v).sort((a, b) => a.d - b.d);
    let acc = 0, pts = [[x(yStart), y(0)]];
    ev.forEach(e => { pts.push([x(e.d), y(acc)]); acc += e.v; pts.push([x(e.d), y(acc)]); });
    pts.push([x(yEnd), y(acc)]);
    return pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ");
  };
  const plan = series(o => toDT(o.ordered) || toDT(o.date), () => true);
  const comm = series(o => toDT(o.ordered), (p, o) => ["ordered", "delivered"].includes(o.status));
  const step = [50, 100, 200, 250, 500, 1000, 2000].find(st => maxY / st <= 5) || 5000;
  const ticks = [...Array(Math.floor(maxY / step) + 1).keys()].map(i => i * step);
  const months = [...Array(10).keys()].map(i => yStart.startOf("month").plus({ months: i })).filter(d => d <= yEnd);
  const svg = `<svg class="rz-chart" viewBox="0 0 ${W} ${H}">
    ${ticks.map(v => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="g"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${eur(v)}</text>`).join("")}
    ${months.map(d => `<text x="${x(d)}" y="${H - 8}" text-anchor="middle">${fmt(d, "LLL")}</text>`).join("")}
    <line x1="${L}" x2="${W - R}" y1="${y(budgetEur)}" y2="${y(budgetEur)}" class="budget"/>
    <text x="${W - R}" y="${y(budgetEur) - 5}" text-anchor="end" class="budget-t">budget ${eur(budgetEur)}</text>
    <line x1="${x(TODAY)}" x2="${x(TODAY)}" y1="${T}" y2="${H - B}" class="today"/>
    <polyline points="${plan}" class="plan"/><polyline points="${comm}" class="comm"/>
  </svg>`;
  const key = `<div class="rz-keys"><span><i class="k-comm"></i>committed</span><span><i class="k-plan"></i>planned</span><span><i class="k-budget"></i>budget</span></div>`;
  return card("Budget burn", svg + key, "rz-span-7", link("30 Hardware/Hardware", "Hardware →", "rz-more"));
};

S.upnext = () => {
  const PR = { p1: 0, p2: 1, p3: 2 };
  const list = open.filter(p => p.status !== "backlog").sort((a, b) => {
    const da = due(a), db = due(b);
    if (da && db && +da !== +db) return da - db;
    if (da && !db) return -1;
    if (!da && db) return 1;
    return (PR[a.priority] ?? 3) - (PR[b.priority] ?? 3);
  }).slice(0, 9);
  const rows = list.map(p => {
    const d = due(p), late = d && d < TODAY;
    return `<div class="rz-row">${avatar(p.owner)}<span class="rz-row-t">${plink(p)}</span>${pill(p.status)}<span class="rz-pr rz-${esc(p.priority || "p3")}">${esc(p.priority || "")}</span><span class="rz-due ${late ? "rz-bad" : ""}">${d ? `${fmt(d)} · ${rel(d)}` : "no date"}</span></div>`;
  }).join("");
  return card("Up next", rows || empty("Nothing open. Suspicious."), "rz-span-7", link("20 Work/Work board", "Board →", "rz-more"));
};

S.claude = async () => {
  const q = open.filter(p => p.owner === "claude");
  const asks = inbox.filter(p => arr(p.file.tags).some(t => String(t).toLowerCase() === "#ask-claude"));
  let last = "";
  try {
    const txt = await dv.io.load("90 Meta/Claude/Session log.md");
    const parts_ = String(txt || "").split(/^## /m).slice(1);
    if (parts_.length) {
      const sec = parts_[parts_.length - 1].split("\n");
      const bullets = sec.slice(1).filter(l => l.trim().startsWith("- ")).slice(0, 3)
        .map(l => `<li>${esc(l.replace(/^\s*- /, "").replace(/\*\*/g, ""))}</li>`).join("");
      last = `<div class="rz-cl-last"><div class="rz-small">Last session · ${esc(sec[0].trim())}</div><ul>${bullets}</ul></div>`;
    }
  } catch (e) { last = ""; }
  const items = [...q.map(p => `<div class="rz-row">${pill(p.status)}<span class="rz-row-t">${plink(p)}</span><span class="rz-due">${due(p) ? rel(due(p)) : ""}</span></div>`),
    ...asks.map(p => `<div class="rz-row"><span class="rz-pill" style="--c:var(--color-pink)">Ask</span><span class="rz-row-t">${plink(p)}</span></div>`)].join("");
  const body = `<div class="rz-cl"><div class="rz-cl-id">${avatar("claude")}<div><b>Claude</b><div class="rz-small">${q.length} in queue · ${asks.length} asks</div></div></div>
    ${items || empty("Queue empty. Tag an inbox note #ask-claude or set owner: claude.")}${last}
    <div class="rz-cl-links">${link("90 Meta/Claude/Handoff", "Handoff")}${link("90 Meta/Claude/Session log", "Session log")}${link("90 Meta/Claude/Claude", "How Claude works")}</div></div>`;
  return card("Claude", body, "rz-span-5 rz-claude");
};

S.recent = () => {
  const by = (a, b) => (toDT(b.date) || toDT(b.file.mtime)) - (toDT(a.date) || toDT(a.file.mtime));
  const list = (ps, sub) => ps.length ? ps.map(p => `<div class="rz-li">${plink(p)}<span>${sub(p)}</span></div>`).join("") : empty("None yet");
  const dec = list([...decs].sort((a, b) => String(b.id || b.file.name).localeCompare(String(a.id || a.file.name))).slice(0, 5), p => `tier ${p.tier ?? "—"}`);
  const ex = list([...exps].sort(by).slice(0, 5), p => `${esc(p.status || "")}${p.result ? " · " + esc(p.result) : ""}`);
  const edited = pages("").filter(p => /^\d\d /.test(p.file.path) && !p.file.path.startsWith("90 Meta/Templates"))
    .sort((a, b) => toDT(b.file.mtime) - toDT(a.file.mtime) || b.file.mtime - a.file.mtime).slice(0, 6);
  const ed = list(edited, p => { const m = p.file.mtime; return m && m.toRelative ? esc(m.setLocale("en-GB").toRelative()) : ""; });
  return `<div class="rz-grid rz-sub3">${card("Decisions", dec, "", link("80 Decisions/Decisions", "All →", "rz-more"))}${card("Experiments", ex, "", link("50 Experiments/Experiments", "All →", "rz-more"))}${card("Recently edited", ed)}</div>`;
};

S.dashboard = async () => {
  const blocks = [S.header(), S.kpis(), `<div class="rz-grid">${S.activity()}${S.workload()}</div>`,
    `<div class="rz-grid">${S.pipeline()}</div>`,
    `<div class="rz-grid">${S.upnext()}${await S.claude()}</div>`,
    `<div class="rz-grid">${S.budget()}${S.milestones()}</div>`, S.recent()];
  return blocks.join("");
};

// ----- sections used inside other notes
const here = dv.current ? dv.current() : null;

S.orderLines = () => {
  const mine = parts.filter(p => here && nameOf(p.order) === here.file.name);
  if (!mine.length) return empty("No parts link to this order yet. Set order: \"[[" + (here ? here.file.name : "ORD-###") + "]]\" on a part note.");
  const rows = mine.map(p => `<tr><td>${plink(p)}</td><td>${num(p.qty) ?? 1}</td><td>${num(p.price_eur) !== null ? eur(num(p.price_eur)) : "?"}</td><td>${eur(lineEur(p))}</td><td>${esc(p.supplier || "")}</td><td>${esc(p.status || "")}</td></tr>`).join("");
  const total = mine.reduce((s, p) => s + lineEur(p), 0);
  return `<div class="rz-order"><div class="rz-order-tot"><span>${mine.length} lines</span><b>${eur(total)}</b><span>before VAT and shipping</span></div>
    <table class="rz-table"><thead><tr><th>Part</th><th>Qty</th><th>Each</th><th>Line</th><th>Supplier</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`;
};

S.packCard = () => {
  if (!here) return "";
  const at = Math.max(0, STAGES.indexOf(here.stage));
  const steps = STAGES.map((s, i) => `<span class="rz-step ${i < at ? "past" : i === at ? "cur" : ""}"><i></i><em>${s}</em></span>`).join("");
  const mine = exps.filter(e => nameOf(e.pack) === here.file.name);
  const best = num(here.best_value), tgt = num(here.target_value);
  return `<div class="rz-packcard"><div class="rz-pipe rz-pipe-solo">${steps}</div>
    <div class="rz-kpis rz-kpis-3">${card("Best", `<div class="rz-big">${best ?? "—"}</div><div class="rz-small">${esc(here.metric || "")}</div>`, "rz-kpi")}${card("Target", `<div class="rz-big">${tgt ?? "—"}</div><div class="rz-small">Year 1 goal</div>`, "rz-kpi")}${card("Experiments", `<div class="rz-big">${mine.length}</div><div class="rz-small">${mine.filter(e => e.result === "pass").length} passed</div>`, "rz-kpi")}</div></div>`;
};

S.packWork = () => {
  if (!here) return "";
  const mine = work.filter(p => nameOf(p.pack) === here.file.name).sort((a, b) => LANES.indexOf(a.status) - LANES.indexOf(b.status));
  return mine.length ? mine.map(p => `<div class="rz-row">${avatar(p.owner)}<span class="rz-row-t">${plink(p)}</span>${pill(p.status)}<span class="rz-due">${due(p) ? fmt(due(p)) : ""}</span></div>`).join("") : empty("No work linked to this pack yet");
};

S.weekReview = () => {
  const ws = (here && toDT(here.date)) ? toDT(here.date).startOf("week") : weekStart;
  const we = ws.plus({ weeks: 1 });
  const inW = d => d && d >= ws && d < we;
  const done = work.filter(p => inW(doneOn(p)));
  const late = open.filter(p => due(p) && due(p) < we);
  const ex = exps.filter(e => inW(toDT(e.date)));
  const dc = decs.filter(d => inW(toDT(d.date)));
  const list = (ps, f) => ps.length ? ps.map(f).join("") : empty("—");
  return `<div class="rz-grid rz-sub2">
    ${card(`Done (${done.length})`, list(done, p => `<div class="rz-row">${avatar(p.owner)}<span class="rz-row-t">${plink(p)}</span></div>`))}
    ${card(`Due by end of week, still open (${late.length})`, list(late, p => `<div class="rz-row">${avatar(p.owner)}<span class="rz-row-t">${plink(p)}</span>${pill(p.status)}</div>`))}
    ${card(`Experiments (${ex.length})`, list(ex, p => `<div class="rz-li">${plink(p)}<span>${esc(p.result || p.status || "")}</span></div>`))}
    ${card(`Decisions (${dc.length})`, list(dc, p => `<div class="rz-li">${plink(p)}</div>`))}</div>`;
};

// ---------- render

const fn = S[SECTION];
if (!fn) throw new Error(`Unknown section "${SECTION}"`);
root.innerHTML = await fn();
} catch (e) {
  root.innerHTML = `<div class="rz-error">Dashboard section "${esc(SECTION)}" failed: ${esc(e.message)}</div>`;
  console.error("[rezonating]", e);
}
