// Helpers shared by the live diagrams: SVG building, plots, sliders, readouts.
import { el, app } from "../core.js";

const NS = "http://www.w3.org/2000/svg";
export function s(tag, attrs = {}, ...kids) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "text") n.textContent = v;
    else if (k === "style" && typeof v === "object") n.setAttribute("style", Object.entries(v).map(([a, b]) => `${a}:${b}`).join(";"));
    else n.setAttribute(k, v);
  }
  kids.flat().forEach((c) => c && n.append(c));
  return n;
}
export const svg = (w, h) => s("svg", { viewBox: `0 0 ${w} ${h}`, role: "img" });
export const line = (x1, y1, x2, y2, cls = "wire", style) => s("line", { x1, y1, x2, y2, class: cls, style });
export const text = (x, y, str, { cls = "lbl", anchor = "start", style } = {}) => s("text", { x, y, class: cls, "text-anchor": anchor, style, text: str });
export const path = (pts, style, cls = "wire") => s("path", { d: pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(""), class: cls, style });
export const color = (c) => `var(--${c})`;

/** A plot area with axes and dotted grid. Returns {g, X, Y} mapping data to px. */
export function plot(parent, { x, y, w, h, x0, x1, y0, y1, logx = false, xticks = [], yticks = [], xlab = "", ylab = "", fmtx = String, fmty = String }) {
  const g = s("g");
  const lx0 = logx ? Math.log10(x0) : x0, lx1 = logx ? Math.log10(x1) : x1;
  const X = (v) => x + ((logx ? Math.log10(Math.max(v, 1e-30)) : v) - lx0) / (lx1 - lx0) * w;
  const Y = (v) => y + h - (v - y0) / (y1 - y0) * h;
  xticks.forEach((v) => { g.append(line(X(v), y, X(v), y + h, "grid"), text(X(v), y + h + 13, fmtx(v), { anchor: "middle" })); });
  yticks.forEach((v) => { g.append(line(x, Y(v), x + w, Y(v), "grid"), text(x - 5, Y(v) + 3, fmty(v), { anchor: "end" })); });
  g.append(s("rect", { x, y, width: w, height: h, class: "ax" }));
  if (xlab) g.append(text(x + w, y + h + 26, xlab, { anchor: "end" }));
  if (ylab) g.append(text(x, y - 6, ylab));
  parent.append(g);
  return { g, X, Y };
}

/** Zig-zag resistor between two points (horizontal or vertical). */
export function resistor(x1, y1, x2, y2, label, sub) {
  const g = s("g");
  const horiz = Math.abs(x2 - x1) > Math.abs(y2 - y1);
  const L = horiz ? x2 - x1 : y2 - y1, body = Math.min(46, Math.abs(L) * 0.6), a = (Math.abs(L) - body) / 2 * Math.sign(L);
  const pts = [];
  const n = 6;
  for (let i = 0; i <= n; i++) {
    const t = a + (body * Math.sign(L) * i) / n, off = i === 0 || i === n ? 0 : (i % 2 ? 6 : -6);
    pts.push(horiz ? [x1 + t, y1 + off] : [x1 + off, y1 + t]);
  }
  g.append(horiz ? line(x1, y1, x1 + a, y1) : line(x1, y1, x1, y1 + a), path(pts, null, "wire comp-z"),
    horiz ? line(x1 + a + body * Math.sign(L), y1, x2, y2) : line(x1, y1 + a + body * Math.sign(L), x2, y2));
  if (label) g.append(horiz ? text((x1 + x2) / 2, y1 - 11, label, { anchor: "middle", cls: "lbl ink" }) : text(x1 + 12, (y1 + y2) / 2 + 3, label, { cls: "lbl ink" }));
  if (sub) g.append(horiz ? text((x1 + x2) / 2, y1 + 20, sub, { anchor: "middle" }) : text(x1 + 12, (y1 + y2) / 2 + 16, sub));
  return g;
}
export function dot(x, y, r = 3, style) { return s("circle", { cx: x, cy: y, r, style: style || "fill:var(--ink)" }); }
export function source(x, y, r, label) {
  return s("g", {}, s("circle", { cx: x, cy: y, r, class: "comp" }), text(x, y - 3, "+", { anchor: "middle", cls: "lbl ink" }), text(x, y + 10, "−", { anchor: "middle", cls: "lbl ink" }),
    label ? text(x - r - 6, y + 3, label, { anchor: "end", cls: "lbl ink" }) : null);
}
export function ground(x, y) { return s("g", {}, line(x, y, x, y + 8), line(x - 9, y + 8, x + 9, y + 8), line(x - 6, y + 12, x + 6, y + 12), line(x - 3, y + 16, x + 3, y + 16)); }

/** Slider control. opts: {label, min, max, step, value, fmt, log, onInput}. log: slider 0..1000 mapped exponentially. */
export function slider({ label, min, max, step = "any", value, fmt = (v) => v, log = false, onInput }) {
  const toS = (v) => (log ? (Math.log(v / min) / Math.log(max / min)) * 1000 : v);
  const fromS = (sv) => (log ? min * Math.pow(max / min, sv / 1000) : +sv);
  const vEl = el("span.v");
  const inp = el("input", { type: "range", min: log ? 0 : min, max: log ? 1000 : max, step: log ? 1 : step, value: toS(value) });
  const ctl = el("label", el("span", label, " = ", vEl), inp);
  ctl.get = () => fromS(+inp.value);
  ctl.set = (v) => { inp.value = toS(v); vEl.textContent = fmt(v); };
  inp.addEventListener("input", () => { vEl.textContent = fmt(ctl.get()); onInput?.(ctl.get()); });
  vEl.textContent = fmt(value);
  return ctl;
}
export function select(label, options, value, onChange) {
  const sel = el("select", options.map(([v, l]) => el("option", { value: v, selected: v === value }, l)));
  sel.addEventListener("change", () => onChange(sel.value));
  const ctl = el("label", el("span", label), sel);
  ctl.get = () => sel.value;
  return ctl;
}
export function readout() {
  const r = el("div.readout");
  r.put = (items) => r.replaceChildren(...items.filter(Boolean).map(([k, v, style]) => el("div", el("span", k, " "), el("b", { style }, v))));
  return r;
}
export const hu = () => app.lang === "hu";
export const tr = (en, huS) => (app.lang === "hu" ? huS : en);

/** The frame every widget sits in. */
export function frame(box, title, fig) {
  const card = el("div.card.widget", el("div.tag", "◎ ", tr("Live diagram", "Élő ábra"), fig ? ` · ${fig}` : "", " — ", el("b", title)));
  box.append(card);
  return card;
}
