// Registry of live diagrams. In lesson Markdown: {{w:id key=value …}} on its own line.
import { el } from "../core.js";
import * as analog from "./analog.js";
import * as signal from "./signal.js";
import * as digital from "./digital.js";

export const WIDGETS = {
  ohm: analog.ohm,           // v, r
  divider: analog.divider,   // vin, r1, r2, rl, topo=series|boss|free
  bridge: analog.bridge,     // vex, kg, gain
  rc: analog.rc,             // mode=filter|step, r, c, f
  opamp: analog.opamp,       // rf, rg, vin, offset
  clamp: analog.clamp,       // amp, r
  power: analog.power,       // (no args)
  sampling: signal.sampling, // f, fs, win
  quantize: signal.quantize, // bits, gain, amp
  decimate: signal.decimate, // f, taps
  clock: signal.clock,       // err (percent)
  geophone: signal.geophone, // zeta, f, vel (mm/s)
  spi: digital.spi,          // byte=0xA5, master, device, bug=1
  i2c: digital.i2c,          // r, c, speed
};

export function mountWidget(id, box, args = {}) {
  const fn = WIDGETS[id];
  if (!fn) { box.append(el("div.card", el("div.tag", "WIDGET"), el("p.empty", `Unknown diagram “${id}”`))); return; }
  try { fn(box, args); } catch (e) { console.error(e); box.append(el("p.empty", `${id}: ${e.message}`)); }
}
