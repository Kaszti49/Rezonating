// Parts in 3D: an index of all 18 parts, and one part on a 3D stage with its pins, facts and lessons.
import { app, el, L, t, load } from "../core.js";
import { render } from "../md.js";
import { setContext } from "../ask.js";
import { hydrateTerms } from "../glossary.js";
import { seePart } from "../progress.js";
import { prog } from "../progress.js";
import { refreshChrome } from "../app.js";

const STATUS = { have: ["have", "var(--sage)"], needed: ["needed", "var(--clay)"], later: ["later", "var(--ink-3)"], ordered: ["ordered", "var(--ochre)"] };
const ICON = { mcu: "▣", adc: "∿", clock: "◷", sensor: "◉", storage: "▤", prototyping: "⊞", passive: "⏚", cable: "≋", consumable: "✎" };

export function pinText(data, part, info) {
  if (!info) return { title: "", body: "" };
  if (info.feature) {
    const f = part.features?.[info.key];
    return f ? { title: f[0], body: app.lang === "hu" ? f[2] || f[1] : f[1], kind: "feature" } : { title: info.key, body: "" };
  }
  const k = data.kinds[info.kind] || data.kinds.gpio;
  const fn = info.fn ? L(info.fn) : k[app.lang === "hu" ? 1 : 0];
  return { title: `${info.header ? info.header + " · " : ""}${info.num ? "#" + info.num + " " : ""}${info.name}`, body: fn, kind: info.kind, color: k[2], kindName: k[app.lang === "hu" ? 1 : 0] };
}

export default async function partView(root, { name, id }) {
  const data = await load("parts.json");
  const byId = Object.fromEntries(data.parts.map((p) => [p.id, p]));
  const hu = app.lang === "hu";
  if (name === "parts" || !id || !byId[id]) return index(root, data);
  const part = byId[id];
  seePart(part.id, part.name.en);
  refreshChrome();

  const wrap = el("div.wrap.wide");
  root.append(wrap);
  const idx = data.parts.indexOf(part);
  const prev = data.parts[(idx - 1 + data.parts.length) % data.parts.length], next = data.parts[(idx + 1) % data.parts.length];
  wrap.append(el("div.hero",
    el("div.kicker", `3D · ${String(idx + 1).padStart(2, "0")}/18 · ${part.category.toUpperCase()}`),
    el("h1", L(part.name)),
    el("p", L(part.role)),
    el("div.meta-row",
      el("span.chip", el("i", { style: { background: STATUS[part.status]?.[1] } }), t(part.status)),
      el("span.chip", { title: part.dims_ok ? "" : "typical / estimated" }, part.dims, part.dims_ok ? "" : " ·  ≈"),
      el("span.chip", "◫ ", t("fromNote"), ": ", part.note),
      el("span", { style: { flex: 1 } }),
      el("a.btn", { href: `#/part/${prev.id}` }, "← ", L(prev.name)), el("a.btn", { href: `#/part/${next.id}` }, L(next.name), " →"))));

  const stage = el("div.stage");
  const hud = el("div.hud", t("explodeHint"));
  const tip = el("div.pin-tip");
  const side = el("div");
  wrap.append(el("div.part-layout", el("div", stage), side));
  stage.append(hud, tip);

  // tools
  const exp = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: 0 });
  const labelsBtn = el("button.btn.on", { type: "button" }, t("labels"));
  const dimsBtn = el("button.btn", { type: "button" }, t("dims"));
  const resetBtn = el("button.btn", { type: "button" }, t("reset"));
  stage.append(el("div.tools", labelsBtn, dimsBtn, resetBtn), el("div.slider", t("explode"), exp));

  // info side
  const facts = el("table.pin-table", el("tbody", (part.facts || []).map(([k, v]) => el("tr", el("td", k), el("td", v)))));
  const pinRows = new Map();
  const pinTables = Object.entries(part.headers || {}).map(([h, list]) => el("div",
    el("div.label-line", { style: { margin: "18px 0 6px" } }, `${t("pins")} · ${h}`),
    el("table.pin-table", el("tbody", list.map((s, i) => {
      const [nm, kind = "gpio", en = "", huTxt = ""] = s.split("|");
      const k = data.kinds[kind] || data.kinds.gpio;
      const tr = el("tr", { "data-h": h, "data-n": String(i + 1) },
        el("td", el("span.swatch", { style: { background: k[2] } }), `${i + 1} ${nm}`),
        el("td", en ? (hu ? huTxt || en : en) : k[hu ? 1 : 0]));
      pinRows.set(`${h}#${i + 1}`, tr);
      return tr;
    })))));
  side.append(
    el("div.card", el("div.tag", hu ? "Mi ez" : "What it is"), el("div.prose", { style: { fontSize: "14.5px" }, html: render(L(part.summary)) })),
    part.facts?.length ? el("div.card", el("div.tag", hu ? "Tények" : "Facts"), facts) : null,
    ...pinTables,
    part.lessons?.length ? el("div.meta-row", { style: { marginTop: "16px" } }, el("span.tag", { style: { margin: 0 } }, t("lessons")), part.lessons.map((l) => el("a.chip", { href: `#/lesson/${l}` }, l.toUpperCase()))) : null,
    el("div.legend", Object.entries(data.kinds).filter(([k]) => Object.values(part.headers || {}).flat().some((s) => (s.split("|")[1] || "gpio") === k)).map(([, v]) => el("span", el("span.swatch", { style: { background: v[2] } }), v[hu ? 1 : 0]))));
  hydrateTerms(side);

  setContext({ title: `3D: ${L(part.name)}`, excerpt: `${L(part.role)}\n\n${L(part.summary)}\n\nFacts: ${(part.facts || []).map((f) => f.join(": ")).join("; ")}\n\nPins: ${Object.entries(part.headers || {}).map(([h, l]) => `${h}: ${l.map((s) => s.split("|")[0]).join(", ")}`).join(" | ")}` });

  // 3D (loaded lazily so the rest of the site works without WebGL / offline)
  let viewer;
  try {
    const [{ createViewer }, { buildPart }] = await Promise.all([import("../three/viewer.js"), import("../three/parts3d.js")]);
    let lastRow = null;
    viewer = createViewer(stage, {
      onHover(info, at) {
        lastRow?.classList.remove("hl");
        if (!info) { tip.style.display = "none"; return; }
        const { title, body, color, kindName } = pinText(data, part, info);
        tip.replaceChildren(el("b", title), kindName ? el("span", { style: { color: "var(--ink-3)", fontSize: "11px" } }, ` · ${kindName}`) : null, el("div", body));
        if (color) tip.style.borderLeft = `3px solid ${color}`; else tip.style.borderLeft = "";
        tip.style.display = "block";
        tip.style.left = `${Math.min(at.x + 14, stage.clientWidth - 290)}px`;
        tip.style.top = `${Math.min(at.y + 14, stage.clientHeight - 80)}px`;
        const row = pinRows.get(`${info.header}#${info.num}`);
        if (row) { row.classList.add("hl"); lastRow = row; }
      },
    });
    const obj = buildPart(part, byId);
    viewer.setObject(obj);
    exp.addEventListener("input", () => viewer.setExplode(+exp.value));
    labelsBtn.addEventListener("click", () => { labelsBtn.classList.toggle("on"); viewer.setLabels(labelsBtn.classList.contains("on")); });
    dimsBtn.addEventListener("click", () => { dimsBtn.classList.toggle("on"); viewer.setDims(dimsBtn.classList.contains("on")); });
    resetBtn.addEventListener("click", () => viewer.reset());
    pinRows.forEach((row, key) => {
      const [h, n] = key.split("#");
      row.addEventListener("mouseenter", () => viewer.highlight((p) => p && p.header === h && String(p.num) === n));
      row.addEventListener("mouseleave", () => viewer.highlight(null));
    });
  } catch (e) {
    console.error(e);
    stage.append(el("div.hud", { style: { top: "40px" } }, `3D unavailable: ${e.message}`));
  }
  return () => viewer?.dispose();
}

function index(root, data) {
  const hu = app.lang === "hu";
  const wrap = el("div.wrap.wide");
  root.append(wrap);
  wrap.append(el("div.hero", el("div.kicker", "3D · 18"), el("h1", t("parts")),
    el("p", hu ? "Minden alkatrész a 30 Hardware/Parts mappából. Forgasd, szedd szét, vidd az egeret a lábakra. A ≈ jel becsült méretet jelent (nem mértük le)." : "Every part from 30 Hardware/Parts. Rotate, explode, hover the pins. ≈ marks a typical or estimated size (not measured yet).")));
  const groups = ["have", "needed", "later"];
  for (const st of groups) {
    const ps = data.parts.filter((p) => p.status === st);
    if (!ps.length) continue;
    wrap.append(el("div.label-line", t(st)));
    wrap.append(el("div.grid2", ps.map((p) => el("a.card.track-card", { href: `#/part/${p.id}`, style: { color: "inherit", borderBottom: "1px solid var(--line)" } },
      el("div.tag", `${ICON[p.category] || "·"} ${p.category}${prog.state.parts[p.id] ? " · ✓" : ""}`),
      el("h3", L(p.name)), el("p.empty", L(p.role)), el("div.mono", { style: { fontSize: "11px", color: "var(--ink-3)" } }, p.dims_ok ? p.dims : `≈ ${p.dims}`)))));
  }
  setContext({ title: t("parts"), excerpt: data.parts.map((p) => `${p.name.en}: ${p.role.en}`).join("\n") });
}
