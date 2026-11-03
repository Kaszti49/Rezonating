// Analog live diagrams: ohm, divider, bridge, rc, opamp, clamp, power.
import { el, si } from "../core.js";
import { s, svg, line, text, path, plot, resistor, dot, source, ground, slider, select, readout, frame, tr, color } from "./kit.js";

const ohmFmt = (v) => si(v, "Ω");

// ---------------------------------------------------------------------------------------------- ohm
export function ohm(box, a) {
  const card = frame(box, tr("Ohm's law and power", "Ohm törvénye és a teljesítmény"), a.fig);
  const W = 560, H = 220;
  const g = svg(W, H);
  card.append(g);
  const flow = s("g");
  const st = { V: +(a.v ?? 3.3), R: +(a.r ?? 690) };
  const out = readout();
  const vS = slider({ label: "V", min: 0, max: 5, step: 0.05, value: st.V, fmt: (v) => si(v, "V"), onInput: (v) => { st.V = v; draw(); } });
  const rS = slider({ label: "R", min: 10, max: 1e6, log: true, value: st.R, fmt: ohmFmt, onInput: (v) => { st.R = v; draw(); } });
  const pre = select(tr("Preset", "Előbeállítás"), [["", "—"], ["690", "690 Ω (470 + 220, our fix)"], ["680000", "680 kΩ (the wrong resistor)"], ["1100", "1.1 kΩ (load cell E+/E−)"], ["10", "10 Ω"]], "", (v) => { if (v) { st.R = +v; rS.set(st.R); draw(); } });
  card.append(el("div.ctrls", vS, rS, pre), out);
  let anim = 0, phase = 0, last = performance.now();
  function draw() {
    const I = st.V / st.R, P = st.V * I;
    g.replaceChildren(
      line(90, 50, 420, 50), line(420, 50, 420, 70), resistor(420, 70, 420, 150, si(st.R, "Ω"), si(P, "W")), line(420, 150, 420, 170), line(420, 170, 90, 170),
      line(90, 50, 90, 85), source(90, 110, 24, si(st.V, "V")), line(90, 135, 90, 170), flow,
      text(255, 40, `I = V / R = ${si(I, "A")}`, { anchor: "middle", cls: "lbl ink" }),
      text(255, 196, tr("dots move at a speed proportional to the current (log scale)", "a pöttyök sebessége az árammal arányos (log skála)"), { anchor: "middle" }));
    out.put([["I", si(I, "A")], ["P", si(P, "W")], [tr("heat in R per hour", "hő R-ben óránként"), si(P * 3600, "J")],
      st.R >= 1e5 && st.V > 1 ? [tr("note", "megjegyzés"), tr("µA-level current: a bridge behind this sees almost no voltage", "µA-es áram: egy mögötte lévő híd szinte nem kap feszültséget"), "color:var(--bad)"] : null]);
    anim = Math.max(0.02, Math.min(3, Math.log10(I * 1e6 + 1) / 1.5));
  }
  const loopPts = [[90, 85], [90, 50], [420, 50], [420, 170], [90, 170], [90, 135]];
  const segs = loopPts.slice(1).map((p, i) => [loopPts[i], p, Math.hypot(p[0] - loopPts[i][0], p[1] - loopPts[i][1])]);
  const total = segs.reduce((t, x) => t + x[2], 0);
  let raf;
  const tick = (now) => {
    phase = (phase + (now - last) * 0.06 * anim) % 40; last = now;
    flow.replaceChildren();
    for (let d = phase; d < total; d += 40) {
      let rem = d;
      for (const [p0, p1, len] of segs) { if (rem <= len) { const f = rem / len; flow.append(dot(p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f, 2.6, "fill:var(--clay)")); break; } rem -= len; }
    }
    if (g.isConnected) raf = requestAnimationFrame(tick);
  };
  draw();
  raf = requestAnimationFrame(tick);
}

// ------------------------------------------------------------------------------------------ divider
export function divider(box, a) {
  const card = frame(box, tr("Voltage divider and loading", "Feszültségosztó és terhelés"), a.fig);
  const W = 560, H = 250;
  const g = svg(W, H);
  card.append(g);
  const st = { vin: +(a.vin ?? 3.3), r1: +(a.r1 ?? 690), r2: +(a.r2 ?? 1e9), rl: +(a.rl ?? 1100), topo: a.topo || "series" };
  const out = readout();
  const r1S = slider({ label: "R1 (top)", min: 10, max: 1e6, log: true, value: st.r1, fmt: ohmFmt, onInput: (v) => { st.r1 = v; draw(); } });
  const r2S = slider({ label: tr("R2 (bottom, to GND)", "R2 (alsó, GND felé)"), min: 10, max: 1e6, log: true, value: Math.min(st.r2, 1e6), fmt: ohmFmt, onInput: (v) => { st.r2 = v; draw(); } });
  const rlS = slider({ label: tr("Load (bridge)", "Terhelés (híd)"), min: 100, max: 1e6, log: true, value: st.rl, fmt: ohmFmt, onInput: (v) => { st.rl = v; draw(); } });
  const topo = select(tr("Wiring", "Bekötés"), [["series", tr("our rig: R1 in series, no R2", "a mi pultunk: R1 sorosan, nincs R2")], ["boss", tr("boss's: 220 Ω top, 470 Ω to GND", "a főnöké: 220 Ω fent, 470 Ω GND-re")], ["free", tr("free: R1, R2 and load", "szabad: R1, R2 és terhelés")]], st.topo, (v) => {
    st.topo = v;
    if (v === "series") { st.r1 = 690; st.r2 = 1e9; }
    if (v === "boss") { st.r1 = 220; st.r2 = 470; }
    if (v === "free" && st.r2 > 1e6) st.r2 = 1000;
    r1S.set(st.r1); r2S.set(Math.min(st.r2, 1e6)); draw();
  });
  card.append(el("div.ctrls", topo, r1S, r2S, rlS), out);
  function draw() {
    const hasR2 = st.topo !== "series";
    const rLow = hasR2 ? (st.r2 * st.rl) / (st.r2 + st.rl) : st.rl;
    const vout = (st.vin * rLow) / (st.r1 + rLow);
    const unloaded = hasR2 ? (st.vin * st.r2) / (st.r1 + st.r2) : st.vin;
    const itot = st.vin / (st.r1 + rLow);
    const sense = vout / 2;
    g.replaceChildren(
      source(70, 125, 22, si(st.vin, "V")), line(70, 103, 70, 40), line(70, 40, 200, 40), resistor(200, 40, 200, 110, "R1 " + si(st.r1, "Ω")),
      line(200, 110, 200, 125), dot(200, 125), line(200, 125, 380, 125),
      hasR2 ? resistor(200, 125, 200, 205, "R2 " + si(st.r2, "Ω")) : null,
      hasR2 ? null : line(200, 125, 200, 205, "grid"),
      resistor(380, 125, 380, 205, tr("load ", "terhelés ") + si(st.rl, "Ω"), tr("the cell's E+/E−", "a cella E+/E−")),
      line(70, 147, 70, 215), line(70, 215, 380, 215), line(380, 205, 380, 215), hasR2 ? line(200, 205, 200, 215) : null, ground(225, 215),
      text(210, 140, `Vout = ${si(vout, "V")}`, { cls: "lbl ink", style: "font-size:13px" }),
      text(470, 60, tr("unloaded", "terhelés nélkül"), { anchor: "middle" }), text(470, 76, si(unloaded, "V"), { anchor: "middle", cls: "lbl ink" }),
      text(470, 110, tr("loaded", "terhelve"), { anchor: "middle" }), text(470, 126, si(vout, "V"), { anchor: "middle", cls: "lbl ink" }));
    out.put([["Vout (E+ − E−)", si(vout, "V")], ["I", si(itot, "A")], [tr("sense lines ≈ Vout/2", "jelvezetékek ≈ Vout/2"), si(sense, "V"), sense > 1.5 ? "color:var(--bad)" : "color:var(--ok)"],
      [tr("P in R1", "P R1-ben"), si(itot * itot * st.r1, "W")], [tr("cell output @1 mV/V, 5 kg", "cella kimenet @1 mV/V, 5 kg"), si(vout * 1e-3, "V")]]);
  }
  draw();
}

// ------------------------------------------------------------------------------------------- bridge
export function bridge(box, a) {
  const card = frame(box, tr("Wheatstone bridge: the YZC-133 load cell", "Wheatstone-híd: a YZC-133 mérlegcella"), a.fig);
  const W = 560, H = 270;
  const g = svg(W, H);
  card.append(g);
  const st = { vex: +(a.vex ?? 2.0), kg: +(a.kg ?? 1), gain: +(a.gain ?? 128) };
  const out = readout();
  card.append(el("div.ctrls",
    slider({ label: tr("Excitation", "Gerjesztés"), min: 0.5, max: 5, step: 0.05, value: st.vex, fmt: (v) => si(v, "V"), onInput: (v) => { st.vex = v; draw(); } }),
    slider({ label: tr("Load", "Terhelés"), min: -5, max: 5, step: 0.05, value: st.kg, fmt: (v) => `${v.toFixed(2)} kg`, onInput: (v) => { st.kg = v; draw(); } }),
    select(tr("ADC gain", "ADC erősítés"), [1, 2, 4, 8, 16, 32, 64, 128].map((x) => [String(x), `× ${x}  (±${si(1.2 / x, "V")})`]), String(st.gain), (v) => { st.gain = +v; draw(); })), out);
  function draw() {
    const R = 1000, k = (st.kg / 5) * 1e-3; // full bridge, 4 active gauges: Vout/Vex = ΔR/R = 1 mV/V at 5 kg
    const dR = R * k;
    const vout = st.vex * 1e-3 * (st.kg / 5);
    const fs = 1.2 / st.gain;
    const cx = 230, cy = 135, d = 85;
    const T = [cx, cy - d], B = [cx, cy + d], Lp = [cx - d, cy], Rp = [cx + d, cy];
    const gauge = (p, q, lbl, up) => {
      const grp = resistor(p[0], p[1], q[0], q[1]);
      const mx = (p[0] + q[0]) / 2, my = (p[1] + q[1]) / 2;
      grp.append(text(mx + (mx < cx ? -14 : 14), my + (my < cy ? -6 : 14), `${lbl} ${up ? "+" : "−"}${dR.toFixed(2)} Ω`, { anchor: mx < cx ? "end" : "start", style: `fill:${up ? "var(--clay)" : "var(--blue)"}` }));
      return grp;
    };
    const frac = Math.max(-1, Math.min(1, vout / fs));
    g.replaceChildren(
      gauge(T, Lp, "R1", true), gauge(T, Rp, "R2", false), gauge(Lp, B, "R3", false), gauge(Rp, B, "R4", true),
      dot(...T), dot(...B), dot(...Lp), dot(...Rp),
      text(T[0], T[1] - 10, `E+ ${tr("red", "piros")} · ${si(st.vex, "V")}`, { anchor: "middle", cls: "lbl ink" }),
      text(B[0], B[1] + 20, `E− ${tr("black", "fekete")} · 0 V`, { anchor: "middle", cls: "lbl ink" }),
      text(Lp[0] - 8, Lp[1] + 4, `S− ${tr("white", "fehér")}`, { anchor: "end" }),
      text(Rp[0] + 8, Rp[1] + 4, `S+ ${tr("green", "zöld")}`),
      line(Lp[0], Lp[1], Lp[0], cy + 120, "grid"), line(Rp[0], Rp[1], Rp[0], cy + 120, "grid"),
      text(cx, cy + 4, `Vout = ${si(vout, "V")}`, { anchor: "middle", cls: "lbl ink", style: "font-size:12.5px" }),
      // ADC bar
      s("rect", { x: 400, y: 50, width: 26, height: 170, class: "ax" }),
      s("rect", { x: 401, y: frac >= 0 ? 135 - frac * 85 : 135, width: 24, height: Math.abs(frac) * 85, style: `fill:${Math.abs(frac) >= 1 ? "var(--bad)" : "var(--sage)"}` }),
      line(396, 135, 430, 135), text(436, 54, `+${si(fs, "V")}`), text(436, 139, "0"), text(436, 222, `−${si(fs, "V")}`),
      text(413, 238, tr("ADC input range", "ADC tartomány"), { anchor: "middle" }));
    const counts = Math.round((vout / fs) * 8388607);
    out.put([["Vout", si(vout, "V")], [tr("per kg", "kg-onként"), si(st.vex * 1e-3 / 5, "V")], [tr("of full scale", "a teljes skálából"), `${(frac * 100).toFixed(1)} %`, Math.abs(frac) >= 1 ? "color:var(--bad)" : null],
      [tr("ADC code (24-bit)", "ADC kód (24 bit)"), Math.abs(frac) >= 1 ? tr("clipped", "telítve") : counts.toLocaleString()], ["ΔR/R", `${(k * 1e6).toFixed(0)} ppm`]]);
  }
  draw();
}

// ----------------------------------------------------------------------------------------------- rc
export function rc(box, a) {
  const mode = a.mode || "filter";
  const card = frame(box, mode === "step" ? tr("RC charging", "RC töltődés") : tr("RC low-pass filter", "RC aluláteresztő szűrő"), a.fig);
  const W = 560, H = 250;
  const g = svg(W, H);
  card.append(g);
  const st = { R: +(a.r ?? 1000), C: +(a.c ?? 100e-9), f: +(a.f ?? 1000) };
  const out = readout();
  const ctr = [
    slider({ label: "R", min: 10, max: 1e6, log: true, value: st.R, fmt: ohmFmt, onInput: (v) => { st.R = v; draw(); } }),
    slider({ label: "C", min: 1e-9, max: 100e-6, log: true, value: st.C, fmt: (v) => si(v, "F"), onInput: (v) => { st.C = v; draw(); } }),
  ];
  if (mode === "filter") ctr.push(slider({ label: tr("Input frequency", "Bemeneti frekvencia"), min: 1, max: 100000, log: true, value: st.f, fmt: (v) => si(v, "Hz"), onInput: (v) => { st.f = v; draw(); } }));
  card.append(el("div.ctrls", ...ctr), out);
  function draw() {
    const tau = st.R * st.C, fc = 1 / (2 * Math.PI * tau);
    g.replaceChildren();
    if (mode === "step") {
      const tmax = 5 * tau;
      const p = plot(g, { x: 50, y: 20, w: 480, h: 180, x0: 0, x1: tmax, y0: 0, y1: 3.5, xticks: [0, 1, 2, 3, 4, 5].map((k) => k * tau), yticks: [0, 1, 2, 3, 3.3], fmtx: (v) => `${(v / tau).toFixed(0)}τ`, fmty: (v) => `${v} V`, xlab: `τ = RC = ${si(tau, "s")}` });
      const pts = Array.from({ length: 200 }, (_, i) => { const t = (i / 199) * tmax; return [p.X(t), p.Y(3.3 * (1 - Math.exp(-t / tau)))]; });
      g.append(path(pts, "stroke:var(--blue);stroke-width:2"), line(p.X(tau), p.Y(0), p.X(tau), p.Y(3.3 * 0.632), "grid"), text(p.X(tau) + 4, p.Y(2.086) - 4, "63 %", { cls: "lbl ink" }));
      out.put([["τ", si(tau, "s")], [tr("99 % after 5τ", "99 % 5τ után"), si(5 * tau, "s")], ["fc", si(fc, "Hz")]]);
      return;
    }
    const gain = (f) => 1 / Math.sqrt(1 + (f / fc) ** 2);
    const p = plot(g, { x: 50, y: 18, w: 230, h: 180, x0: 1, x1: 1e5, y0: -60, y1: 5, logx: true, xticks: [1, 10, 100, 1e3, 1e4, 1e5], yticks: [0, -20, -40, -60], fmtx: (v) => si(v, ""), fmty: (v) => `${v}`, xlab: "Hz", ylab: "dB" });
    const pts = Array.from({ length: 160 }, (_, i) => { const f = Math.pow(10, (i / 159) * 5); return [p.X(f), p.Y(Math.max(-60, 20 * Math.log10(gain(f))))]; });
    g.append(path(pts, "stroke:var(--blue);stroke-width:2"), line(p.X(fc), p.Y(5), p.X(fc), p.Y(-60), "grid"), text(p.X(fc) + 3, p.Y(-55), `fc ${si(fc, "Hz")}`, { cls: "lbl ink" }),
      dot(p.X(st.f), p.Y(Math.max(-60, 20 * Math.log10(gain(st.f)))), 4, "fill:var(--clay)"));
    const q = plot(g, { x: 310, y: 18, w: 230, h: 180, x0: 0, x1: 2, y0: -1.2, y1: 1.2, yticks: [-1, 0, 1], xticks: [0, 1, 2], fmtx: (v) => `${v}T`, xlab: tr("periods", "periódus") });
    const ph = -Math.atan(st.f / fc), A = gain(st.f);
    const sin = (amp, phase) => Array.from({ length: 160 }, (_, i) => { const x = (i / 159) * 2; return [q.X(x), q.Y(amp * Math.sin(2 * Math.PI * x + phase))]; });
    g.append(path(sin(1, 0), "stroke:var(--ink-3);stroke-dasharray:3 3"), path(sin(A, ph), "stroke:var(--clay);stroke-width:2"),
      text(320, 236, tr("dashed: input · solid: output", "szaggatott: bemenet · folytonos: kimenet")));
    out.put([["fc = 1/(2πRC)", si(fc, "Hz")], [tr("gain at f", "erősítés f-en"), `${A.toFixed(3)} (${(20 * Math.log10(A)).toFixed(1)} dB)`], [tr("phase", "fázis"), `${(ph * 180 / Math.PI).toFixed(0)}°`], ["τ", si(tau, "s")]]);
  }
  draw();
}

// ------------------------------------------------------------------------------------------- opamp
export function opamp(box, a) {
  const card = frame(box, tr("Op-amp: non-inverting amplifier", "Műveleti erősítő: neminvertáló erősítő"), a.fig);
  const W = 560, H = 250;
  const g = svg(W, H);
  card.append(g);
  const st = { rf: +(a.rf ?? 9000), rg: +(a.rg ?? 1000), vin: +(a.vin ?? 0.1), off: +(a.offset ?? 1.65), rail: +(a.rail ?? 3.3), buffer: a.buffer === "1" };
  const out = readout();
  card.append(el("div.ctrls",
    slider({ label: "Rf", min: 0, max: 100000, step: 100, value: st.rf, fmt: ohmFmt, onInput: (v) => { st.rf = v; draw(); } }),
    slider({ label: "Rg", min: 100, max: 100000, log: true, value: st.rg, fmt: ohmFmt, onInput: (v) => { st.rg = v; draw(); } }),
    slider({ label: tr("Input amplitude", "Bemeneti amplitúdó"), min: 0.001, max: 1.5, log: true, value: st.vin, fmt: (v) => si(v, "V"), onInput: (v) => { st.vin = v; draw(); } }),
    slider({ label: tr("Mid-supply bias", "Középfeszültség"), min: 0, max: 3.3, step: 0.05, value: st.off, fmt: (v) => si(v, "V"), onInput: (v) => { st.off = v; draw(); } })), out);
  function draw() {
    const G = 1 + st.rf / st.rg;
    g.replaceChildren();
    // symbol
    g.append(s("path", { d: "M60,40 L60,140 L150,90 Z", class: "comp" }), text(68, 70, "+", { cls: "lbl ink" }), text(68, 118, "−", { cls: "lbl ink" }),
      line(20, 65, 60, 65), text(18, 60, "Vin"), line(150, 90, 200, 90), text(204, 94, "Vout"), line(180, 90, 180, 170), resistor(180, 170, 90, 170, "Rf"), line(90, 170, 40, 170),
      line(40, 170, 40, 115), line(40, 115, 60, 115), resistor(40, 170, 40, 225, "Rg"), ground(40, 225));
    const p = plot(g, { x: 270, y: 18, w: 270, h: 190, x0: 0, x1: 2, y0: -0.2, y1: 3.5, yticks: [0, st.rail, st.off], fmty: (v) => v.toFixed(2), xticks: [0, 1, 2], fmtx: (v) => `${v}T` });
    const vin = (x) => st.off / G + st.vin * Math.sin(2 * Math.PI * x);
    const vo = (x) => Math.max(0.05, Math.min(st.rail - 0.05, G * (st.vin * Math.sin(2 * Math.PI * x)) + st.off));
    const pts = (f) => Array.from({ length: 200 }, (_, i) => { const x = (i / 199) * 2; return [p.X(x), p.Y(f(x))]; });
    g.append(path(pts(vin), "stroke:var(--ink-3);stroke-dasharray:3 3"), path(pts(vo), "stroke:var(--clay);stroke-width:2"),
      line(p.X(0), p.Y(st.rail), p.X(2), p.Y(st.rail), "grid"), text(p.X(2) - 2, p.Y(st.rail) - 4, tr("rail", "táp"), { anchor: "end" }));
    const clip = G * st.vin + st.off > st.rail - 0.05 || st.off - G * st.vin < 0.05;
    out.put([[tr("gain", "erősítés"), `${G.toFixed(2)} × (${(20 * Math.log10(G)).toFixed(1)} dB)`], [tr("output swing", "kimeneti kilengés"), `± ${si(G * st.vin, "V")}`], clip ? [tr("clipping", "levágás"), tr("output hits the rail", "a kimenet eléri a tápot"), "color:var(--bad)"] : [tr("clipping", "levágás"), tr("none", "nincs"), "color:var(--ok)"]]);
  }
  draw();
}

// ------------------------------------------------------------------------------------------- clamp
export function clamp(box, a) {
  const card = frame(box, tr("Input protection: series resistor + clamp diodes", "Bemenetvédelem: soros ellenállás + határoló diódák"), a.fig);
  const W = 560, H = 230;
  const g = svg(W, H);
  card.append(g);
  const st = { amp: +(a.amp ?? 5), r: +(a.r ?? 1000), vf: 0.3 };
  const out = readout();
  card.append(el("div.ctrls",
    slider({ label: tr("Piezo peak", "Piezo csúcs"), min: 0.1, max: 50, log: true, value: st.amp, fmt: (v) => si(v, "V"), onInput: (v) => { st.amp = v; draw(); } }),
    slider({ label: tr("Series R", "Soros R"), min: 100, max: 100000, log: true, value: st.r, fmt: ohmFmt, onInput: (v) => { st.r = v; draw(); } }),
    select(tr("Diodes", "Diódák"), [["0.3", "Schottky (≈0.3 V)"], ["0.7", "silicon (≈0.7 V)"], ["9", tr("none", "nincs")]], "0.3", (v) => { st.vf = +v; draw(); })), out);
  function draw() {
    g.replaceChildren();
    const hi = 3.3 + st.vf, lo = -st.vf;
    const top = Math.max(st.amp, 4);
    const p = plot(g, { x: 50, y: 18, w: 480, h: 170, x0: 0, x1: 2, y0: -top, y1: top, yticks: [-top, 0, 3.3, top].map((v) => +v.toFixed(1)), xticks: [0, 1, 2], fmtx: (v) => `${v}T`, fmty: (v) => `${v} V` });
    const band = s("rect", { x: p.X(0), y: p.Y(3.6), width: 480, height: p.Y(-1.6) - p.Y(3.6), style: "fill:var(--sage-l);opacity:.6" });
    g.insertBefore(band, g.firstChild.nextSibling);
    const pts = (f) => Array.from({ length: 300 }, (_, i) => { const x = (i / 299) * 2; return [p.X(x), p.Y(f(x))]; });
    const vin = (x) => st.amp * Math.sin(2 * Math.PI * x);
    const vout = (x) => Math.max(lo, Math.min(hi, vin(x)));
    g.append(path(pts(vin), "stroke:var(--ink-3);stroke-dasharray:3 3"), path(pts(vout), "stroke:var(--clay);stroke-width:2"),
      text(p.X(0) + 4, p.Y(3.6) - 4, tr("ADS131M0x survives: AGND − 1.6 V … AVDD + 0.3 V", "ADS131M0x még túléli: AGND − 1,6 V … AVDD + 0,3 V")));
    const iPeak = Math.max(0, st.amp - hi) / st.r;
    const safe = hi <= 3.6 && lo >= -1.6;
    out.put([[tr("clamped to", "határolva"), `${si(lo, "V")} … ${si(hi, "V")}`, safe ? "color:var(--ok)" : "color:var(--bad)"], [tr("diode current peak", "dióda csúcsáram"), si(iPeak, "A"), iPeak > 0.01 ? "color:var(--bad)" : null], [tr("series R power peak", "soros R csúcsteljesítmény"), si(iPeak * iPeak * st.r, "W")]]);
  }
  draw();
}

// ------------------------------------------------------------------------------------------- power
export function power(box, a) {
  const card = frame(box, tr("Power budget and the AMS1117 regulator", "Teljesítménymérleg és az AMS1117 stabilizátor"), a.fig);
  const loads = [
    ["ESP32 (Wi-Fi on, est.)", 160], ["ESP32 (Wi-Fi off, est.)", 40], ["ADC 15 Click (est.)", 4], ["load cell via 690 Ω (calc.)", 1.8], ["ADXL355 (est.)", 0.2], ["microSD writing (est.)", 60], ["LED (est.)", 2],
  ];
  const on = new Set([1, 2, 3]);
  const st = { vin: 5 };
  const out = readout();
  const g = svg(560, 120);
  const list = el("div.ctrls", loads.map(([n, mA], i) => {
    const cb = el("input", { type: "checkbox", checked: on.has(i) });
    cb.addEventListener("change", () => { cb.checked ? on.add(i) : on.delete(i); draw(); });
    return el("label", { style: { gridTemplateColumns: "auto 1fr", display: "grid", alignItems: "center", gap: "6px" } }, cb, el("span", `${n} · ${mA} mA`));
  }));
  card.append(g, list, el("div.ctrls", slider({ label: tr("Input (USB/VIN)", "Bemenet (USB/VIN)"), min: 3.5, max: 12, step: 0.1, value: 5, fmt: (v) => si(v, "V"), onInput: (v) => { st.vin = v; draw(); } })), out);
  function draw() {
    const I = [...on].reduce((t, i) => t + loads[i][1], 0) / 1000;
    const pd = (st.vin - 3.3) * I;
    const maxI = 0.8;
    g.replaceChildren(s("rect", { x: 20, y: 40, width: 520, height: 26, class: "ax" }),
      s("rect", { x: 21, y: 41, width: Math.min(518, (518 * I) / maxI), height: 24, style: `fill:${I > maxI ? "var(--bad)" : "var(--ochre)"}` }),
      text(20, 30, tr("3.3 V rail current vs ≈ 800 mA (typical AMS1117 figure: check the datasheet)", "3,3 V-os ág árama ≈ 800 mA-hez képest (tipikus AMS1117 érték: nézd meg az adatlapot)")), text(540, 88, "≈ 800 mA", { anchor: "end" }));
    out.put([[tr("3.3 V current", "3,3 V áram"), si(I, "A")], [tr("LDO heat (Vin − 3.3) × I", "LDO hő (Vin − 3,3) × I"), si(pd, "W"), pd > 1 ? "color:var(--bad)" : null], [tr("efficiency", "hatásfok"), `${Math.round((3.3 / st.vin) * 100)} %`], [tr("dropout margin (≈ 1.1 V typ.)", "dropout tartalék (≈ 1,1 V tip.)"), si(st.vin - 3.3 - 1.1, "V"), st.vin - 3.3 < 1.1 ? "color:var(--bad)" : null]]);
  }
  draw();
}
