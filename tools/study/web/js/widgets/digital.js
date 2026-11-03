// Digital live diagrams: spi (modes and the chip-select timing bug), i2c (pull-ups and rise time).
import { el, si } from "../core.js";
import { s, svg, line, text, path, plot, slider, select, readout, frame, tr } from "./kit.js";

// ---------------------------------------------------------------------------------------------- spi
export function spi(box, a) {
  const card = frame(box, tr("SPI on the wire: modes and chip-select timing", "SPI a vezetéken: módok és chip-select időzítés"), a.fig);
  const g = svg(560, 270);
  card.append(g);
  const st = { byte: parseInt(a.byte ?? "0xA5", 16) || 0xa5, mmode: +(a.master ?? 1), dmode: +(a.device ?? 1), bug: a.bug === "1" };
  const out = readout();
  const bug = el("input", { type: "checkbox", checked: st.bug });
  bug.addEventListener("change", () => { st.bug = bug.checked; draw(); });
  card.append(el("div.ctrls",
    select(tr("Byte the device sends", "A küldött bájt"), [["0xA5", "0xA5 = 1010 0101"], ["0x22", "0x22 = 0010 0010 (ID high byte)"], ["0x05", "0x05 = 0000 0101"], ["0xFF", "0xFF"]], `0x${st.byte.toString(16).toUpperCase().padStart(2, "0")}`, (v) => { st.byte = parseInt(v, 16); draw(); }),
    select(tr("ESP32 SPI mode", "ESP32 SPI mód"), [0, 1, 2, 3].map((m) => [String(m), `mode ${m} (CPOL ${m >> 1}, CPHA ${m & 1})`]), String(st.mmode), (v) => { st.mmode = +v; draw(); }),
    select(tr("Device mode", "Eszköz mód"), [["1", "ADS131M02 · mode 1"], ["0", "LTC6903 · mode 0"]], String(st.dmode), (v) => { st.dmode = +v; draw(); }),
    el("label", { style: { display: "flex", gap: "6px", alignItems: "center" } }, bug, tr("CS goes low too late (ESP-IDF default timing on our bench)", "A CS túl későn megy le (ESP-IDF alap időzítés a pultunkon)"))), out);
  function draw() {
    g.replaceChildren();
    const x0 = 100, bw = 52, n = 8, rows = { CS: 40, SCLK: 90, MISO: 140, READ: 196 };
    const hi = (y) => y - 14, lo = (y) => y + 14;
    Object.entries(rows).forEach(([k, y]) => g.append(text(10, y + 4, k === "READ" ? tr("ESP32 reads", "ESP32 olvas") : k, { cls: "lbl ink" })));
    const cpol = st.mmode >> 1, cpha = st.mmode & 1, dcpha = st.dmode & 1;
    // CS
    const csFall = st.bug ? x0 + bw * 0.6 : x0 - 24;
    g.append(path([[60, hi(rows.CS)], [csFall, hi(rows.CS)], [csFall, lo(rows.CS)], [x0 + n * bw + 16, lo(rows.CS)], [x0 + n * bw + 16, hi(rows.CS)], [550, hi(rows.CS)]], "stroke:var(--ink);stroke-width:1.6"));
    // SCLK
    const idle = cpol ? hi(rows.SCLK) : lo(rows.SCLK), act = cpol ? lo(rows.SCLK) : hi(rows.SCLK);
    const ck = [[60, idle]];
    for (let i = 0; i < n; i++) { const xs = x0 + i * bw; ck.push([xs, idle], [xs, act], [xs + bw / 2, act], [xs + bw / 2, idle]); }
    ck.push([550, idle]);
    g.append(path(ck, "stroke:var(--blue);stroke-width:1.6"));
    // device MISO: device drives bit k starting at its "shift" edge. If CS came late, the device starts one bit late.
    const bits = Array.from({ length: n }, (_, i) => (st.byte >> (7 - i)) & 1);
    const devStart = (i) => (dcpha ? x0 + i * bw : x0 + i * bw - bw / 2);
    const lag = st.bug ? 1 : 0;
    const devBits = Array.from({ length: n + 1 }, (_, i) => (i - lag < 0 ? 0 : bits[i - lag] ?? 0));
    const miso = [];
    for (let i = 0; i <= n; i++) { const xs = Math.max(csFall, devStart(i)), xe = devStart(i + 1); const y = devBits[i] ? hi(rows.MISO) : lo(rows.MISO); miso.push([xs, y], [Math.min(xe, x0 + n * bw + 16), y]); }
    g.append(path(miso, "stroke:var(--clay);stroke-width:1.6"));
    // sample points: leading edge if CPHA 0, trailing if CPHA 1
    const read = [];
    for (let i = 0; i < n; i++) {
      const xs = x0 + i * bw + (cpha ? bw / 2 : 0);
      // which device bit is on the wire at xs? the device changes at devStart(k)
      let k = 0; while (k < n && devStart(k + 1) <= xs + 0.1) k++;
      const onEdge = Math.abs(devStart(k) - xs) < 0.5 || Math.abs(devStart(k + 1) - xs) < 0.5;
      const v = devBits[k];
      read.push(v);
      g.append(line(xs, rows.SCLK - 22, xs, rows.READ - 14, "grid"), text(xs, rows.READ + 4, String(v), { anchor: "middle", cls: "lbl ink", style: onEdge ? "fill:var(--bad)" : "" }));
    }
    const val = read.reduce((acc, b) => (acc << 1) | b, 0);
    for (let i = 0; i < n; i++) g.append(text(x0 + i * bw + bw / 4, rows.MISO - 20, String(bits[i]), { anchor: "middle" }));
    g.append(text(x0, 250, tr("small numbers above MISO: the bits the device means to send · red: sampled while the line changes (unreliable)", "kis számok a MISO felett: amit az eszköz küldeni akar · piros: váltás közben mintavételezve (bizonytalan)")));
    const mismatch = cpha !== dcpha;
    out.put([[tr("sent", "küldve"), `0x${st.byte.toString(16).toUpperCase().padStart(2, "0")}`], [tr("read", "olvasva"), `0x${val.toString(16).toUpperCase().padStart(2, "0")}`, val === st.byte ? "color:var(--ok)" : "color:var(--bad)"],
      mismatch ? [tr("mode", "mód"), tr("phase mismatch: sampling on the changing edge", "fázis eltérés: a váltó élen mintavételez"), "color:var(--bad)"] : null,
      st.bug ? [tr("CS bug", "CS hiba"), tr("first edge missed → everything shifts right by one bit; fix: cs_ena_pretrans = 2", "első él elveszik → minden egy bittel jobbra csúszik; javítás: cs_ena_pretrans = 2"), "color:var(--bad)"] : null]);
  }
  draw();
}

// ---------------------------------------------------------------------------------------------- i2c
export function i2c(box, a) {
  const card = frame(box, tr("I²C: open drain, pull-ups and rise time", "I²C: nyitott kollektor, felhúzó ellenállás és felfutási idő"), a.fig);
  const g = svg(560, 230);
  card.append(g);
  const st = { r: +(a.r ?? 4700), c: +(a.c ?? 100e-12), speed: +(a.speed ?? 400e3) };
  if (st.c >= 1e-6) st.c *= 1e-12; // c given in pF (e.g. c=100)
  const out = readout();
  card.append(el("div.ctrls",
    slider({ label: tr("Pull-up", "Felhúzó"), min: 470, max: 47000, log: true, value: st.r, fmt: (v) => si(v, "Ω"), onInput: (v) => { st.r = v; draw(); } }),
    slider({ label: tr("Bus capacitance", "Busz kapacitás"), min: 10e-12, max: 400e-12, log: true, value: st.c, fmt: (v) => si(v, "F"), onInput: (v) => { st.c = v; draw(); } }),
    select(tr("Speed", "Sebesség"), [["100000", "100 kHz standard"], ["400000", "400 kHz fast"], ["1000000", "1 MHz fast-mode plus"]], String(st.speed), (v) => { st.speed = +v; draw(); })), out);
  function draw() {
    g.replaceChildren();
    const T = 1 / st.speed, tau = st.r * st.c, tr_ = 0.8473 * tau;
    const spec = { 100000: 1000e-9, 400000: 300e-9, 1000000: 120e-9 }[st.speed];
    const p = plot(g, { x: 50, y: 16, w: 490, h: 170, x0: 0, x1: 3 * T, y0: -0.2, y1: 3.6, yticks: [0, 0.99, 2.31, 3.3], fmty: (v) => v.toFixed(2), xticks: [0, T, 2 * T, 3 * T], fmtx: (v) => si(v, "s") });
    const pts = [];
    for (let i = 0; i <= 600; i++) {
      const t = (i / 600) * 3 * T, ph = (t % T) / T;
      const tRise = t % T - T / 2;
      const v = ph < 0.5 ? (i && pts.length ? Math.min(0.1, 3.3 * Math.exp(-(t % T) / 20e-9)) : 0) : 3.3 * (1 - Math.exp(-tRise / tau));
      pts.push([p.X(t), p.Y(v)]);
    }
    g.append(line(p.X(0), p.Y(0.99), p.X(3 * T), p.Y(0.99), "grid"), line(p.X(0), p.Y(2.31), p.X(3 * T), p.Y(2.31), "grid"), text(p.X(3 * T) - 4, p.Y(2.31) - 4, "VIH 0.7·VDD", { anchor: "end" }), text(p.X(3 * T) - 4, p.Y(0.99) + 12, "VIL 0.3·VDD", { anchor: "end" }),
      path(pts, "stroke:var(--lilac);stroke-width:2"), text(50, 215, tr("a device only pulls the line LOW; the resistor pulls it back HIGH, slowly", "egy eszköz csak LE tudja húzni a vonalat; az ellenállás húzza vissza FEL, lassan")));
    const rmin = (3.3 - 0.4) / 3e-3;
    out.put([[tr("rise time 30→70 %", "felfutás 30→70 %"), si(tr_, "s"), tr_ > spec ? "color:var(--bad)" : "color:var(--ok)"], [tr("allowed", "megengedett"), si(spec, "s")], [tr("smallest pull-up (3 mA sink)", "legkisebb felhúzó (3 mA)"), si(rmin, "Ω"), st.r < rmin ? "color:var(--bad)" : null], [tr("largest pull-up here", "legnagyobb felhúzó itt"), si(spec / (0.8473 * st.c), "Ω")]]);
  }
  draw();
}
