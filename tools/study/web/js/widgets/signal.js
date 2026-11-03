// Signal live diagrams: sampling (aliasing), quantize, decimate (FIR), clock (ppm), geophone (resonance).
import { el, si } from "../core.js";
import { s, svg, line, text, path, plot, dot, slider, select, readout, frame, tr } from "./kit.js";

// ----------------------------------------------------------------------------------------- sampling
export function sampling(box, a) {
  const card = frame(box, tr("Sampling and aliasing", "Mintavételezés és aliasing"), a.fig);
  const g = svg(560, 240);
  card.append(g);
  const st = { f: +(a.f ?? 60), fs: +(a.fs ?? 2000), win: +(a.win ?? 0.05) };
  const out = readout();
  card.append(el("div.ctrls",
    slider({ label: tr("Signal", "Jel"), min: 1, max: 3000, log: true, value: st.f, fmt: (v) => si(v, "Hz"), onInput: (v) => { st.f = v; draw(); } }),
    select(tr("Sample rate", "Mintavételi frekvencia"), [["10", "10 SPS (HX711 slow)"], ["80", "80 SPS (HX711 fast)"], ["1000", "1 kSPS (packs)"], ["2000", "2 kSPS (our ADC)"]], String(st.fs), (v) => { st.fs = +v; draw(); }),
    select(tr("Time window", "Időablak"), [["0.02", "20 ms"], ["0.05", "50 ms"], ["0.2", "200 ms"], ["1", "1 s"]], String(st.win), (v) => { st.win = +v; draw(); })), out);
  function draw() {
    g.replaceChildren();
    const T = st.win;
    const p = plot(g, { x: 40, y: 16, w: 500, h: 180, x0: 0, x1: T, y0: -1.25, y1: 1.25, yticks: [-1, 0, 1], xticks: [0, T / 2, T], fmtx: (v) => si(v, "s") });
    const nyq = st.fs / 2;
    let fa = st.f % st.fs; if (fa > nyq) fa = st.fs - fa;
    const N = Math.min(1500, Math.ceil(T * Math.max(st.f, fa) * 40) + 200);
    const cont = Array.from({ length: N }, (_, i) => { const t = (i / (N - 1)) * T; return [p.X(t), p.Y(Math.sin(2 * Math.PI * st.f * t))]; });
    g.append(path(cont, "stroke:var(--ink-3);stroke-width:1"));
    const alias = Array.from({ length: 600 }, (_, i) => { const t = (i / 599) * T; const sign = (st.f % st.fs) > nyq ? -1 : 1; return [p.X(t), p.Y(sign * Math.sin(2 * Math.PI * fa * t))]; });
    if (st.f > nyq) g.append(path(alias, "stroke:var(--clay);stroke-width:2;stroke-dasharray:5 3"));
    const ns = Math.floor(T * st.fs);
    if (ns <= 400) for (let k = 0; k <= ns; k++) { const t = k / st.fs; g.append(line(p.X(t), p.Y(0), p.X(t), p.Y(Math.sin(2 * Math.PI * st.f * t)), "grid"), dot(p.X(t), p.Y(Math.sin(2 * Math.PI * st.f * t)), 2.6, "fill:var(--blue)")); }
    else g.append(text(290, 210, tr("(too many samples to draw: shorten the window)", "(túl sok minta: rövidítsd az ablakot)"), { anchor: "middle" }));
    g.append(text(40, 225, tr("grey: real signal · blue: samples · dashed: what the samples look like (alias)", "szürke: valódi jel · kék: minták · szaggatott: amit a minták mutatnak (alias)")));
    out.put([[tr("Nyquist limit fs/2", "Nyquist-határ fs/2"), si(nyq, "Hz")], [tr("you see", "amit látsz"), si(fa, "Hz"), st.f > nyq ? "color:var(--bad)" : "color:var(--ok)"], [tr("samples per period", "minta periódusonként"), (st.fs / st.f).toFixed(1)]]);
  }
  draw();
}

// ----------------------------------------------------------------------------------------- quantize
export function quantize(box, a) {
  const card = frame(box, tr("Quantization: LSB size, gain and resolution", "Kvantálás: LSB, erősítés és felbontás"), a.fig);
  const g = svg(560, 230);
  card.append(g);
  const st = { bits: +(a.bits ?? 24), gain: +(a.gain ?? 128), amp: +(a.amp ?? 400e-6), vref: 1.2 };
  const out = readout();
  card.append(el("div.ctrls",
    select(tr("Bits", "Bitek"), [4, 6, 8, 10, 12, 16, 24].map((b) => [String(b), `${b} bit`]), String(st.bits), (v) => { st.bits = +v; draw(); }),
    select(tr("PGA gain", "PGA erősítés"), [1, 2, 4, 8, 16, 32, 64, 128].map((x) => [String(x), `× ${x}`]), String(st.gain), (v) => { st.gain = +v; draw(); }),
    slider({ label: tr("Signal amplitude", "Jel amplitúdó"), min: 1e-6, max: 1.2, log: true, value: st.amp, fmt: (v) => si(v, "V"), onInput: (v) => { st.amp = v; draw(); } })), out);
  function draw() {
    g.replaceChildren();
    const fs = st.vref / st.gain, lsb = (2 * fs) / 2 ** st.bits;
    const p = plot(g, { x: 50, y: 16, w: 490, h: 180, x0: 0, x1: 1, y0: -1.1, y1: 1.1, yticks: [-1, 0, 1], xticks: [], fmty: (v) => (v ? `${v > 0 ? "+" : "−"}${si(fs * Math.abs(v), "V")}` : "0") });
    const A = Math.min(st.amp, fs * 1.2);
    const cont = Array.from({ length: 300 }, (_, i) => { const x = i / 299; return [p.X(x), p.Y(A * Math.sin(2 * Math.PI * x) / fs)]; });
    // display quantization: real for few bits, otherwise exaggerate with a visible note
    const showBits = Math.min(st.bits, 6);
    const dl = (2 * fs) / 2 ** showBits;
    const q = Array.from({ length: 300 }, (_, i) => { const x = i / 299; const v = Math.max(-fs, Math.min(fs - dl, Math.round(A * Math.sin(2 * Math.PI * x) / dl) * dl)); return [p.X(x), p.Y(v / fs)]; });
    const stair = []; q.forEach((pt, i) => { if (i) stair.push([pt[0], q[i - 1][1]]); stair.push(pt); });
    g.append(path(cont, "stroke:var(--ink-3)"), path(stair, "stroke:var(--clay);stroke-width:1.6"));
    if (st.bits > 6) g.append(text(55, 210, tr(`steps drawn as 6 bit; at ${st.bits} bit they are ${2 ** (st.bits - 6)}× finer`, `a lépcsők 6 bitesként rajzolva; ${st.bits} biten ${2 ** (st.bits - 6)}× finomabbak`)));
    const codes = Math.round(st.amp / lsb);
    out.put([[tr("full scale ±1.2 V / gain", "teljes skála ±1,2 V / erősítés"), `± ${si(fs, "V")}`], ["LSB", si(lsb, "V")], [tr("signal in codes", "jel kódokban"), st.amp > fs ? tr("clipped", "telítve") : `± ${codes.toLocaleString()}`, st.amp > fs ? "color:var(--bad)" : null],
      [tr("dynamic range (ideal)", "dinamikatartomány (ideális)"), `${(6.02 * st.bits + 1.76).toFixed(0)} dB`]]);
  }
  draw();
}

// ----------------------------------------------------------------------------------------- decimate
function firTaps(n, fc) { // windowed sinc, fc as fraction of the input sample rate
  const m = (n - 1) / 2, h = [];
  for (let i = 0; i < n; i++) { const x = i - m; const sinc = x === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * x) / (Math.PI * x); const w = 0.42 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)) + 0.08 * Math.cos((4 * Math.PI * i) / (n - 1)); h.push(sinc * w); }
  const sum = h.reduce((a, b) => a + b, 0); return h.map((v) => v / sum);
}
function resp(h, f) { let re = 0, im = 0; h.forEach((v, i) => { re += v * Math.cos(2 * Math.PI * f * i); im -= v * Math.sin(2 * Math.PI * f * i); }); return Math.hypot(re, im); }

export function decimate(box, a) {
  const card = frame(box, tr("FIR low-pass and decimation: 2 kSPS → 1 kSPS", "FIR aluláteresztő és decimálás: 2 kSPS → 1 kSPS"), a.fig);
  const g = svg(560, 240);
  card.append(g);
  const st = { f: +(a.f ?? 700), taps: +(a.taps ?? 63), on: true };
  const out = readout();
  const cb = el("input", { type: "checkbox", checked: true });
  cb.addEventListener("change", () => { st.on = cb.checked; draw(); });
  card.append(el("div.ctrls",
    slider({ label: tr("Tone in the 2 kSPS stream", "Hang a 2 kSPS-es adatban"), min: 1, max: 1000, step: 1, value: st.f, fmt: (v) => si(v, "Hz"), onInput: (v) => { st.f = v; draw(); } }),
    select(tr("FIR taps", "FIR együtthatók"), [["15", "15"], ["31", "31"], ["63", tr("63 (like our firmware)", "63 (mint a firmware-ünk)")]], String(st.taps), (v) => { st.taps = +v; draw(); }),
    el("label", { style: { display: "flex", gap: "6px", alignItems: "center" } }, cb, tr("FIR before dropping samples", "FIR a mintaeldobás előtt"))), out);
  function draw() {
    g.replaceChildren();
    const h = firTaps(st.taps, 0.25); // windowed-sinc stand-in for the firmware filter (63-tap Parks–McClellan, pass 0–400 Hz, stop 600–1000 Hz)
    const p = plot(g, { x: 50, y: 16, w: 490, h: 180, x0: 0, x1: 1000, y0: -80, y1: 5, xticks: [0, 250, 450, 500, 750, 1000], yticks: [0, -20, -40, -60, -80], fmtx: (v) => `${v}`, xlab: tr("Hz (input, 2 kSPS)", "Hz (bemenet, 2 kSPS)"), ylab: "dB" });
    const curve = Array.from({ length: 200 }, (_, i) => { const f = (i / 199) * 1000; return [p.X(f), p.Y(Math.max(-80, 20 * Math.log10(resp(h, f / 2000) + 1e-9)))]; });
    g.append(s("rect", { x: p.X(500), y: 16, width: p.X(1000) - p.X(500), height: 180, style: "fill:var(--rose-l);opacity:.55" }), text(p.X(750), 32, tr("folds back below 500 Hz after ÷2", "÷2 után 500 Hz alá tükröződik"), { anchor: "middle" }));
    if (st.on) g.append(path(curve, "stroke:var(--blue);stroke-width:2"));
    const att = st.on ? resp(h, st.f / 2000) : 1;
    const fo = st.f <= 500 ? st.f : 1000 - st.f;
    g.append(line(p.X(st.f), p.Y(5), p.X(st.f), p.Y(-80), "grid"), dot(p.X(st.f), p.Y(Math.max(-80, 20 * Math.log10(att + 1e-9))), 4, "fill:var(--clay)"));
    out.put([[tr("after ÷2 it appears at", "÷2 után itt jelenik meg"), si(fo, "Hz"), st.f > 500 ? "color:var(--bad)" : null], [tr("its level", "szintje"), `${(20 * Math.log10(att + 1e-12)).toFixed(1)} dB`],
      [tr("FIR delay", "FIR késleltetés"), `${(st.taps - 1) / 2} ${tr("samples", "minta")} = ${si((st.taps - 1) / 2 / 2000, "s")}`]]);
  }
  draw();
}

// -------------------------------------------------------------------------------------------- clock
export function clock(box, a) {
  const card = frame(box, tr("Clock error → sample-rate error", "Órajelhiba → mintavételi hiba"), a.fig);
  const st = { err: +(a.err ?? -0.21), rate: 1000 };
  const out = readout();
  const g = svg(560, 110);
  const sl = slider({ label: tr("Clock error", "Órajel hiba"), min: -1.65, max: 1.65, step: 0.005, value: st.err, fmt: (v) => `${v.toFixed(3)} % (${Math.round(v * 1e4)} ppm)`, onInput: (v) => { st.err = v; draw(); } });
  card.append(g, el("div.ctrls", sl, select(tr("Preset", "Előbeállítás"), [["-0.21", tr("our LTC6903, measured −0.21 %", "a mi LTC6903-unk, mért −0,21 %")], ["0.5", "LTC6903 typ 0.5 %"], ["1.1", "LTC6903 max 1.1 % @25 °C"], ["0.0025", tr("QTM325 crystal ±25 ppm", "QTM325 kristály ±25 ppm")]], "-0.21", (v) => { st.err = +v; sl.set(st.err); draw(); })), out);
  function draw() {
    const real = st.rate * (1 + st.err / 100), perH = (real - st.rate) * 3600;
    g.replaceChildren(text(10, 20, tr("one hour of recording, nominal 1 kSPS", "egy óra felvétel, névleges 1 kSPS")), s("rect", { x: 10, y: 30, width: 540, height: 22, class: "ax" }),
      s("rect", { x: perH >= 0 ? 280 : 280 - Math.min(269, Math.abs(perH) / 40000 * 269), y: 31, width: Math.min(269, Math.abs(perH) / 40000 * 269), height: 20, style: "fill:var(--ochre)" }),
      line(280, 26, 280, 56), text(280, 72, "0", { anchor: "middle" }), text(550, 72, "+40 000", { anchor: "end" }), text(10, 72, "−40 000"));
    out.put([[tr("real rate", "valódi ráta"), `${real.toFixed(2)} Hz`], [tr("samples off per hour", "eltérés óránként"), `${perH >= 0 ? "+" : ""}${Math.round(perH).toLocaleString()}`], [tr("time error per hour", "időhiba óránként"), si(Math.abs(st.err / 100) * 3600, "s")]]);
  }
  draw();
}

// ----------------------------------------------------------------------------------------- geophone
export function geophone(box, a) {
  const card = frame(box, tr("SM-24 geophone: a magnet on a spring", "SM-24 geofon: rugón lógó mágnes"), a.fig);
  const g = svg(560, 250);
  card.append(g);
  const st = { zeta: +(a.zeta ?? 0.6), f: +(a.f ?? 40), vel: +(a.vel ?? 0.1) }; // vel in mm/s
  const fn = 10, S0 = 28.8;
  const out = readout();
  card.append(el("div.ctrls",
    select(tr("Damping (shunt)", "Csillapítás (sönt)"), [["0.25", tr("ζ 0.25 · open circuit", "ζ 0,25 · nyitott")], ["0.6", "ζ 0.60 · 1339 Ω"], ["0.69", "ζ 0.69 · 1000 Ω"]], String(st.zeta), (v) => { st.zeta = +v; draw(); }),
    slider({ label: tr("Vibration frequency", "Rezgés frekvenciája"), min: 1, max: 500, log: true, value: st.f, fmt: (v) => si(v, "Hz"), onInput: (v) => { st.f = v; draw(); } }),
    slider({ label: tr("Floor velocity", "Padló sebesség"), min: 0.001, max: 10, log: true, value: st.vel, fmt: (v) => `${si(v / 1000, "m/s")}`, onInput: (v) => { st.vel = v; draw(); } })), out);
  const H = (f) => { const r = f / fn; return (r * r) / Math.sqrt((1 - r * r) ** 2 + (2 * st.zeta * r) ** 2); };
  function draw() {
    g.replaceChildren();
    const p = plot(g, { x: 50, y: 16, w: 300, h: 190, x0: 1, x1: 1000, y0: 0, y1: 2.2, logx: true, xticks: [1, 10, 100, 1000], yticks: [0, 0.5, 1, 1.5, 2], fmtx: (v) => si(v, ""), xlab: "Hz", ylab: tr("relative sensitivity", "relatív érzékenység") });
    const pts = Array.from({ length: 200 }, (_, i) => { const f = Math.pow(10, (i / 199) * 3); return [p.X(f), p.Y(Math.min(2.2, H(f)))]; });
    g.append(s("rect", { x: p.X(10), y: 16, width: p.X(240) - p.X(10), height: 190, style: "fill:var(--sage-l);opacity:.5" }), text(p.X(48), 30, "10–240 Hz", { anchor: "middle" }),
      path(pts, "stroke:var(--blue);stroke-width:2"), dot(p.X(st.f), p.Y(Math.min(2.2, H(st.f))), 4, "fill:var(--clay)"));
    // cartoon
    const cx = 450, by = 210;
    const disp = Math.sin(performance.now() / 200) * 0;
    g.append(s("rect", { x: cx - 45, y: 30, width: 90, height: 180, rx: 8, class: "comp" }), text(cx, 24, "SM-24", { anchor: "middle", cls: "lbl ink" }),
      s("path", { d: `M${cx},40 l10,8 l-20,8 l20,8 l-20,8 l20,8 l-10,6`, class: "wire" }), s("rect", { x: cx - 22, y: 86 + disp, width: 44, height: 50, rx: 3, style: "fill:var(--ochre-l);stroke:var(--ink)" }),
      text(cx, 115, tr("magnet", "mágnes"), { anchor: "middle" }), s("rect", { x: cx - 32, y: 80, width: 64, height: 62, rx: 2, style: "fill:none;stroke:var(--clay);stroke-dasharray:2 2" }), text(cx + 36, 150, tr("coil", "tekercs"), {}),
      s("path", { d: `M${cx},136 l10,8 l-20,8 l20,8 l-20,8 l20,8 l-10,6`, class: "wire" }), line(cx - 60, by + 10, cx + 60, by + 10, "ax"), text(cx, by + 26, tr("floor", "padló"), { anchor: "middle" }));
    const V = S0 * H(st.f) * (st.vel / 1000);
    out.put([[tr("sensitivity at f", "érzékenység f-en"), `${(S0 * H(st.f)).toFixed(1)} V/(m/s)`], [tr("output", "kimenet"), si(V, "V")], [tr("at gain 32 (±37.5 mV)", "32× erősítésnél (±37,5 mV)"), `${((V / 0.0375) * 100).toFixed(2)} %`, V > 0.0375 ? "color:var(--bad)" : null]]);
  }
  draw();
}
