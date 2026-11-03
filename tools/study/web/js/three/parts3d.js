// Procedural models of the 18 parts. Each builder returns a THREE.Group whose userData holds
// explode: [{obj, offset: Vector3, rot?, fade?}], dims: [{a, b, text}], tick?(t).
// Pins and features carry userData.pin; texts come from content/parts.json (looked up by the part view).
import * as THREE from "three";
import { C, M, metalM, mesh, box, cyl, labelPlane, pcb, header, ic, smd, usbMicro, usbC, button, led, screwTerminal, wroom, dim } from "./kit3d.js";

const V = (x, y, z) => new THREE.Vector3(x, y, z);
/** "NAME|kind|en|hu" -> {name, kind, fn:{en,hu}} */
export function pinSpecs(part, hname) {
  return (part.headers?.[hname] || []).map((s, i) => {
    const [name, kind = "gpio", en = "", hu = ""] = s.split("|");
    return { name, kind, fn: en ? { en, hu: hu || en } : null, num: i + 1 };
  });
}
function feat(obj, key) { obj.traverse((o) => { if (o.isMesh && !o.userData.pin) o.userData.pin = { key, feature: true }; }); return obj; }
function lab(obj, text, at) { obj.userData.label = text; if (at) obj.userData.labelAt = at; return obj; }
function grp(...kids) { const g = new THREE.Group(); kids.forEach((k) => k && g.add(k)); return g; }

// ------------------------------------------------------------------------------------- ESP32 DevKit V1
function devkitBoard(part) {
  const g = new THREE.Group();
  const L = 51.8, W = 28.2, rz = 12.7;
  g.add(pcb(L, W, C.pcbSlate));
  const x0 = -17.78;
  g.add(header(pinSpecs(part, "left"), { axis: "x", origin: [x0, 1.6, rz], header: "left" }));
  g.add(header(pinSpecs(part, "right"), { axis: "x", origin: [x0, 1.6, -rz], header: "right" }));
  g.add(lab(feat(wroom({ pos: [-L / 2 + 12.75 - 0.5, 1.6, 0], rotY: Math.PI / 2 }), "wroom"), "ESP32-WROOM-32", V(0, 6, 0)));
  g.add(lab(feat(usbMicro([L / 2 - 2.2, 1.6, 0], -Math.PI / 2), "usb"), "micro-USB", V(0, 5, 0)));
  g.add(lab(feat(ic({ w: 5, d: 5, h: 0.9, pitch: 0.5, pins: [], label: "CP2102", pos: [13, 1.6, 6.5] }), "cp2102"), "CP2102", V(0, 4, 0)));
  const ams = grp(box(6.5, 1.6, 3.5, C.chip, [0, 0.8, 0]), box(3.2, 0.3, 1.6, C.metal, [0, 0.15, 2.4], null, metalM()));
  ams.position.set(13, 1.6, -6.5);
  ams.add(labelPlane("AMS1117", 5.6, 2.6, { y: 1.61 }));
  g.add(lab(feat(ams, "ams1117"), "AMS1117 3.3 V", V(0, 4, 0)));
  g.add(lab(feat(button([L / 2 - 4, 1.6, -9]), "en"), "EN", V(0, 4, 0)), lab(feat(button([L / 2 - 4, 1.6, 9]), "boot"), "BOOT", V(0, 4, 0)));
  g.add(led([L / 2 - 9, 1.9, -3], C.ledRed), led([L / 2 - 9, 1.9, 3], "#8fb0c9"));
  [[4, 2], [6, -2], [18, 2], [20, -3], [8, 9], [8, -9]].forEach(([x, z]) => g.add(smd(x, z)));
  return g;
}

function esp32Devkit(part) {
  const g = new THREE.Group();
  const EW = 72, ED = 64, rz = 12.7, x0 = -17.78;
  const exp = new THREE.Group();
  exp.add(feat(pcb(EW, ED, C.pcbSage), "exp"));
  exp.add(header(pinSpecs(part, "left").map((p) => ({ ...p, kind: p.kind })), { axis: "x", origin: [x0, 1.6, rz], type: "female", header: "socket-left" }));
  exp.add(header(pinSpecs(part, "right"), { axis: "x", origin: [x0, 1.6, -rz], type: "female", header: "socket-right" }));
  // signal / V / G rows outside each socket (order S, V, G from the socket outwards: not checked on the real board)
  const triple = (side, z0, dz) => {
    const specs = pinSpecs(part, side);
    exp.add(header(specs, { axis: "x", origin: [x0, 1.6, z0], type: "up", header: `exp-${side}` }));
    exp.add(header(specs.map((p) => ({ name: "V", kind: "power", fn: { en: "V: 3.3 V or 5 V, set by the jumper", hu: "V: 3,3 V vagy 5 V, a jumper szerint" } })), { axis: "x", origin: [x0, 1.6, z0 + dz], type: "up", header: `exp-${side}-V` }));
    exp.add(header(specs.map(() => ({ name: "G", kind: "gnd" })), { axis: "x", origin: [x0, 1.6, z0 + 2 * dz], type: "up", header: `exp-${side}-G` }));
  };
  triple("left", rz + 5.08, 2.54);
  triple("right", -rz - 5.08, -2.54);
  // power block, jumper, I2C header, sockets
  exp.add(header([{ name: "D22", kind: "i2c" }, { name: "D21", kind: "i2c" }, { name: "VCC", kind: "power" }, { name: "GND", kind: "gnd" }], { axis: "z", origin: [27, 1.6, -3.8], type: "up", header: "i2c" }));
  const jump = grp(box(5, 2.5, 2.5, C.plastic, [0, 1.25, 0]), box(2.4, 5, 2.6, "#c27c74", [0, 4.5, 0]));
  jump.position.set(-27, 1.6, 0);
  exp.add(lab(feat(jump, "jumper"), "5V | 3.3V", V(0, 9, 0)));
  exp.add(feat(usbC([-EW / 2 + 3, 1.6, -22], Math.PI / 2), "exp"));
  exp.add(feat(grp(Object.assign(box(9, 11, 14, "#3c3f44", [0, 5.5, 0]))), "exp").translateX(-EW / 2 + 5).translateZ(22).translateY(1.6));
  g.add(exp);
  const dk = devkitBoard(part);
  dk.position.y = 1.6 + 8.5 + 2.5;
  g.add(dk);
  g.userData.explode = [{ obj: dk, offset: V(0, 34, 0) }];
  g.userData.dims = [dim([-25.9, 15.5, -14.1], [25.9, 15.5, -14.1], "51.8 mm (typ.)"), dim([30, 15.5, -14.1], [30, 15.5, 14.1], "28.2 mm (typ.)"), dim([-36, 0, 34], [36, 0, 34], "≈ 72 mm (est.)")];
  return g;
}

// ------------------------------------------------------------------------------------------ ESP32-S3
function esp32s3(part) {
  const g = new THREE.Group();
  const L = 62.74, W = 25.4, rz = 11.43, x0 = -26.67;
  g.add(pcb(L, W, C.pcbCharcoal));
  g.add(header(pinSpecs(part, "J1"), { axis: "x", origin: [x0, 1.6, rz], header: "J1" }));
  g.add(header(pinSpecs(part, "J3"), { axis: "x", origin: [x0, 1.6, -rz], header: "J3" }));
  g.add(lab(feat(wroom({ pos: [-L / 2 + 12.75 - 1, 1.6, 0], rotY: Math.PI / 2, label: "ESP32-S3-WROOM-1\nN16R8" }), "wroom"), "ESP32-S3-WROOM-1 (N16R8)", V(0, 6, 0)));
  g.add(lab(feat(usbC([L / 2 - 3.5, 1.6, 5.5], -Math.PI / 2), "usbuart"), "USB-C UART", V(0, 6, 0)));
  g.add(lab(feat(usbC([L / 2 - 3.5, 1.6, -5.5], -Math.PI / 2), "usbnative"), "USB-C USB", V(0, 6, 0)));
  g.add(lab(button([L / 2 - 12, 1.6, 8.5]), "BOOT", V(0, 4, 0)), lab(button([L / 2 - 12, 1.6, -8.5]), "RST", V(0, 4, 0)));
  g.add(lab(feat(box(5, 1.6, 5, C.plasticWhite, [8, 2.4, 0]), "rgb"), "RGB LED (GPIO 38)", V(0, 3, 0)));
  const ldo = grp(box(3, 1.2, 1.6, C.chip, [0, 0.6, 0])); ldo.position.set(16, 1.6, 4);
  g.add(feat(ldo, "ldo"));
  [[0, 6], [3, -6], [14, -4], [20, 8], [20, -8]].forEach(([x, z]) => g.add(smd(x, z)));
  g.userData.dims = [dim([-L / 2, 1.6, -15], [L / 2, 1.6, -15], "62.74 mm"), dim([L / 2 + 4, 1.6, -W / 2], [L / 2 + 4, 1.6, W / 2], "25.40 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ ADC 15 Click
function adc15(part) {
  const g = new THREE.Group();
  const L = 42.9, W = 25.4, rz = 11.43;
  g.add(pcb(L, W, C.pcbClick));
  g.add(header(pinSpecs(part, "left"), { axis: "x", origin: [1.0, 1.6, rz], header: "left" }));
  g.add(header(pinSpecs(part, "right"), { axis: "x", origin: [1.0, 1.6, -rz], header: "right" }));
  const t = pinSpecs(part, "terminals").map((p) => ({ ...p, header: "terminals" }));
  const ch2 = screwTerminal(2, 5.08, [-L / 2 + 4.6, 1.6, 6], [t[1], t[0]]);
  ch2.rotation.y = Math.PI / 2;
  const ch1 = screwTerminal(2, 5.08, [-L / 2 + 4.6, 1.6, -6], [t[3], t[2]]);
  ch1.rotation.y = Math.PI / 2;
  g.add(lab(ch2, "CH2", V(0, 11, 0)), lab(ch1, "CH1", V(0, 11, 0)));
  g.add(lab(feat(ic({ w: 6.5, d: 4.4, pitch: 0.65, pins: [], label: "ADS131M02", pos: [-6, 1.6, 0] }), "adc"), "ADS131M02", V(0, 4, 0)));
  g.add(lab(feat(ic({ w: 3, d: 3, h: 0.9, pitch: 0.65, pins: [], label: "6903", pos: [6, 1.6, 0] }), "ltc"), "LTC6903", V(0, 4, 0)));
  g.add(lab(feat(led([15, 1.9, 5.5]), "led"), "PWR", V(0, 2.5, 0)));
  [[-6, 5.5], [-6, -5.5], [0, 4], [0, -4], [12, 3], [12, -3], [15, -5]].forEach(([x, z]) => g.add(smd(x, z, Math.PI / 2)));
  const silk = labelPlane("ADC 15 CLICK", 14, 3, { bg: C.pcbClick, fg: "#eef0ea", y: 1.61 });
  silk.position.set(13, 1.61, -7.5);
  g.add(silk);
  g.userData.dims = [dim([-L / 2, 1.6, 15.5], [L / 2, 1.6, 15.5], "≈ 42.9 mm (Click M, typ.)"), dim([L / 2 + 3, 1.6, -W / 2], [L / 2 + 3, 1.6, W / 2], "25.4 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ ADS131M04
function ads131m04(part) {
  const g = new THREE.Group();
  const w = 6.5, d = 4.4, h = 1.0;
  const chip = ic({ w, d, h, pitch: 0.65, pins: pinSpecs(part, "pins"), label: "", leadLen: 1.0, pos: [0, 0.3, 0] });
  const body = chip.getObjectByName("ic-body");
  chip.remove(body);
  const bottom = box(w, h / 2, d, C.chip, [0, 0.1 + h / 4, 0]);
  const top = grp(box(w, h / 2, d, C.chip, [0, 0, 0]), labelPlane("ADS131M04\nTI · PW", w * 0.86, d * 0.75, { y: h / 4 + 0.005 }), cyl(0.3, 0.05, "#2f3236", [-w / 2 + 0.7, h / 4 + 0.01, d / 2 - 0.7]));
  top.position.set(0, 0.1 + (3 * h) / 4, 0);
  const die = feat(box(2.6, 0.12, 2.0, "#8f8aa3", [0, 0.1 + h / 2 + 0.06, 0], "die", M("#8f8aa3", { rough: 0.3, metal: 0.4 })), "die");
  chip.add(bottom, top, die);
  const bond = new THREE.Group();
  chip.children.filter((c) => c.userData.pin && !c.userData.pin.feature).forEach((lead) => {
    const a = V(Math.sign(lead.position.x) * Math.min(1.2, Math.abs(lead.position.x)), 0.1 + h / 2 + 0.12, Math.sign(lead.position.z) * 0.95);
    const b = V(lead.position.x, 0.1 + h / 2, Math.sign(lead.position.z) * (d / 2 - 0.25));
    const mid = a.clone().lerp(b, 0.5).add(V(0, 0.35, 0));
    const tube = mesh(new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(a, mid, b), 12, 0.02, 5), M(C.gold, { rough: 0.3, metal: 0.8 }));
    tube.userData.noEdges = true;
    bond.add(tube);
  });
  feat(bond, "bond");
  bond.visible = false;
  chip.add(bond);
  // pads on a footprint
  const fp = box(10, 0.4, 8.6, C.pcbSage, [0, -0.2, 0], "footprint");
  g.add(fp, chip);
  g.userData.explode = [{ obj: top, offset: V(0, 3.5, 0) }];
  g.userData.onExplode = (t) => { bond.visible = t > 0.05; };
  g.userData.dims = [dim([-w / 2, 0.3, d / 2 + 2.2], [w / 2, 0.3, d / 2 + 2.2], "6.5 mm"), dim([w / 2 + 1.2, 0.3, -d / 2], [w / 2 + 1.2, 0.3, d / 2], "4.4 mm (body)"), dim([-w / 2 - 1.2, 0.3, -3.2], [-w / 2 - 1.2, 0.3, 3.2], "6.4 mm (leads)")];
  return g;
}

// ------------------------------------------------------------------------------------------ oscillator
function osc8m(part) {
  const g = new THREE.Group();
  g.add(box(9, 0.8, 7.5, C.pcbSage, [0, -0.4, 0], "footprint"));
  const pads = pinSpecs(part, "pads");
  const pos = [[-0.95, 0.75], [0.95, 0.75], [0.95, -0.75], [-0.95, -0.75]];
  pads.forEach((p, i) => {
    const m = box(1.0, 0.06, 0.9, C.gold, [pos[i][0] * 1.0, 0.03, pos[i][1]], `pad${i + 1}`, new THREE.MeshStandardMaterial({ color: C.gold, roughness: 0.35, metalness: 0.6 }));
    m.userData.pin = { ...p, header: "pads", num: i + 1 };
    m.userData.anchor = V(pos[i][0], 0.06, pos[i][1]);
    m.userData.noEdges = true;
    g.add(m);
  });
  g.add(lab(new THREE.Object3D(), "1", V(-1.6, 0.1, 1.2)));
  const can = new THREE.Group();
  const base = box(3.2, 0.5, 2.5, "#d9d3c5", [0, 0.25, 0]);
  const quartz = feat(cyl(0.9, 0.08, "#dfe7ea", [0, 0.55, 0], "y", 24, M("#dfe7ea", { rough: 0.15, opacity: 0.85 })), "quartz");
  const lid = feat(grp(box(3.0, 0.35, 2.3, C.metal, [0, 0, 0], null, metalM()), labelPlane("8.192\nQTM325", 2.6, 2.0, { bg: "#cfd2d5", fg: "#5b6068", y: 0.18 })), "lid");
  lid.position.y = 0.68;
  can.add(base, quartz, lid);
  can.position.y = 0.08;
  g.add(lab(can, "QTM325 · 8.192 MHz", V(0, 2, 0)));
  g.userData.explode = [{ obj: can, offset: V(0, 2.5, 0) }, { obj: lid, offset: V(0, 1.6, 0) }];
  g.userData.dims = [dim([-1.6, 1.2, 1.8], [1.6, 1.2, 1.8], "3.2 mm"), dim([2.2, 1.2, -1.25], [2.2, 1.2, 1.25], "2.5 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ HX711
function hx711(part) {
  const g = new THREE.Group();
  const L = 34, W = 21;
  g.add(pcb(L, W, C.pcbSage));
  g.add(header(pinSpecs(part, "J1"), { axis: "z", origin: [-L / 2 + 2.5, 1.6, -6.35], type: "holes", header: "J1" }));
  g.add(header(pinSpecs(part, "JP2"), { axis: "z", origin: [L / 2 - 2.5, 1.6, -3.81], type: "holes", header: "JP2" }));
  g.add(lab(feat(ic({ w: 9.9, d: 3.9, h: 1.5, pitch: 1.27, pins: [], label: "HX711", pos: [0, 1.6, 0] }), "chip"), "HX711", V(0, 4, 0)));
  const tr = grp(box(2.9, 1.0, 1.3, C.chip, [0, 0.5, 0])); tr.position.set(-8, 1.6, 6);
  g.add(lab(feat(tr, "transistor"), "S8550", V(0, 3, 0)));
  [[-8, -6], [6, 6], [8, -6], [10, 6], [-3, 6], [3, -6]].forEach(([x, z]) => g.add(smd(x, z)));
  const strip = grp(...Array.from({ length: 10 }, (_, i) => box(0.64, 11.5, 0.64, C.gold, [0, 0, i * 2.54], null, metalM(C.gold))), box(2.5, 2.5, 25.4, C.plastic, [0, 0, 11.43]));
  strip.position.set(0, 14, -11.43);
  g.add(lab(strip, "loose 10-pin header", V(0, 8, 11)));
  g.userData.explode = [{ obj: strip, offset: V(0, 12, 0) }];
  g.userData.dims = [dim([-L / 2, 1.6, W / 2 + 3], [L / 2, 1.6, W / 2 + 3], "≈ 34 mm (typ.)"), dim([L / 2 + 3, 1.6, -W / 2], [L / 2 + 3, 1.6, W / 2], "≈ 21 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ YZC-133 load cell
export function loadCellWires(part) {
  return pinSpecs(part, "wires").map((p, i) => ({ ...p, color: [C.red, C.black, C.green, C.white][i] }));
}
function yzc133(part) {
  const g = new THREE.Group();
  const L = 80, H = 12.7, D = 12.7;
  const sh = new THREE.Shape();
  sh.moveTo(-L / 2, -H / 2); sh.lineTo(L / 2, -H / 2); sh.lineTo(L / 2, H / 2); sh.lineTo(-L / 2, H / 2); sh.closePath();
  const r = 4.6, cx = 6.2, hh = 1.6, a = Math.asin(hh / r);
  const hole = new THREE.Path();
  hole.absarc(-cx, 0, r, a, 2 * Math.PI - a, false);
  hole.lineTo(cx - r * Math.cos(a), -hh);
  hole.absarc(cx, 0, r, Math.PI + a, 3 * Math.PI - a, false);
  hole.lineTo(-cx + r * Math.cos(a), hh);
  sh.holes.push(hole);
  const geo = new THREE.ExtrudeGeometry(sh, { depth: D, bevelEnabled: true, bevelThickness: 0.3, bevelSize: 0.3, bevelSegments: 2, curveSegments: 28 });
  geo.translate(0, 0, -D / 2);
  const bar = mesh(geo, M(C.alu, { rough: 0.45, metal: 0.35 }), [0, H / 2, 0], "bar");
  g.add(lab(feat(bar, "flex"), "YZC-133 · 5 kg", V(-28, 9, 0)));
  [-34, -24, 24, 34].forEach((x) => g.add(feat(cyl(2.4, H + 0.2, "#6d7176", [x, H / 2, 0]), "hole")));
  g.add(Object.assign(labelPlane("5", 4, 4, { bg: C.alu, fg: "#7c8288", y: 0 }), {}));
  g.children[g.children.length - 1].position.set(-14, H + 0.31, 3);
  const gauges = new THREE.Group();
  [[-cx, H + 0.06], [cx, H + 0.06], [-cx, -0.06], [cx, -0.06]].forEach(([x, y], i) => {
    const gg = grp(box(5, 0.08, 6, "#c9a97c", [0, 0, 0]));
    for (let k = 0; k < 6; k++) gg.add(box(0.25, 0.1, 4.6, C.copper, [-1.9 + k * 0.76, 0.02, 0]));
    gg.position.set(x, y, 0);
    if (y < 0) gg.rotation.x = Math.PI;
    lab(gg, `R${i + 1}`, V(0, y < 0 ? -2 : 2, 0));
    gauges.add(feat(gg, "gauge"));
  });
  g.add(gauges);
  const pot = feat(box(22, 1.8, 11, C.silicone, [0, H + 1.0, 0], "potting", M(C.silicone, { opacity: 0.92 })), "potting");
  g.add(pot);
  // wires out of the +X end
  const specs = loadCellWires(part);
  specs.forEach((p, i) => {
    const z = -3 + i * 2;
    const a = V(L / 2 - 2, H * 0.7, z), b = V(L / 2 + 30, 2, z * 2.5);
    const curve = new THREE.CatmullRomCurve3([a, V(L / 2 + 8, H * 0.8, z), V(L / 2 + 20, 4, z * 2), b]);
    const m = mesh(new THREE.TubeGeometry(curve, 40, 0.55, 8), new THREE.MeshStandardMaterial({ color: p.color, roughness: 0.6 }));
    m.userData = { pin: { ...p, header: "wires" }, anchor: b, noEdges: true };
    m.name = `pin:wires:${p.name}`;
    g.add(m);
  });
  g.add(cyl(2.2, 6, C.plastic, [L / 2 - 1, H * 0.7, 0], "x"));
  g.userData.explode = [{ obj: pot, offset: V(0, 10, 0), fade: 0.6 }];
  g.userData.dims = [dim([-L / 2, 0, D / 2 + 4], [L / 2, 0, D / 2 + 4], "≈ 80 mm (typ.)"), dim([-L / 2 - 4, 0, D / 2], [-L / 2 - 4, H, D / 2], "≈ 12.7 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ SM-24
function sm24(part) {
  const g = new THREE.Group();
  const disc = feat(cyl(20, 3, "#e6e1d6", [0, 1.5, 0], "y", 48), "disc");
  const caseG = new THREE.Group();
  const shell = feat(mesh(new THREE.CylinderGeometry(12.7, 12.7, 32, 48, 1, true), new THREE.MeshStandardMaterial({ color: "#7e8389", roughness: 0.5, metalness: 0.3, side: THREE.DoubleSide, transparent: true }), [0, 19, 0]), "case");
  const bottom = cyl(12.7, 1, "#7e8389", [0, 3.5, 0], "y", 48);
  caseG.add(shell, bottom);
  const cap = grp(cyl(12.9, 2, "#6f747a", [0, 0, 0], "y", 48), cyl(4, 1.5, "#3c3f44", [0, 1.6, 0]));
  cap.position.y = 36;
  const t = pinSpecs(part, "terminals");
  t.forEach((p, i) => {
    const m = cyl(0.9, 4, C.gold, [i ? 5 : -5, 2.5, 0], "y", 16, new THREE.MeshStandardMaterial({ color: C.gold, roughness: 0.35, metalness: 0.6 }));
    m.userData = { pin: { ...p, header: "terminals", num: i + 1 }, anchor: V(i ? 5 : -5, 4.5, 0), noEdges: true };
    cap.add(m);
  });
  lab(cap, "+   −", V(0, 7, 0));
  const inner = new THREE.Group();
  const coil = feat(mesh(new THREE.CylinderGeometry(10, 10, 14, 40, 1, true), new THREE.MeshStandardMaterial({ color: C.copper, roughness: 0.5, metalness: 0.4, side: THREE.DoubleSide }), [0, 19, 0]), "coil");
  const ring = (r, tube, mat, y) => { const m = mesh(new THREE.TorusGeometry(r, tube, 6, 40), mat); m.rotation.x = Math.PI / 2; m.position.y = y; m.userData.noEdges = true; return m; };
  for (let k = 0; k < 12; k++) coil.add(ring(10.05, 0.25, M("#b88b6b"), -6.5 + k * 1.2));
  const magnet = feat(cyl(6, 16, "#55595f", [0, 19, 0], "y", 32), "magnet");
  const springs = feat(grp(ring(8.5, 0.35, metalM(), 28.5), ring(8.5, 0.35, metalM(), 9.5)), "spring");
  inner.add(coil, magnet, springs);
  lab(magnet, "magnet", V(0, 0, 0)); lab(coil, "coil", V(10, 4, 0)); lab(springs.children[0], "spring", V(8.5, 0, 0));
  g.add(lab(disc, "insulating disc", V(18, 0, 0)), caseG, cap, inner);
  g.userData.explode = [{ obj: cap, offset: V(0, 26, 0) }, { obj: caseG, offset: V(0, 0, 0), fade: 0.8 }, { obj: inner, offset: V(0, 4, 0) }];
  inner.visible = false;
  g.userData.onExplode = (t) => { inner.visible = t > 0.02; };
  g.userData.tick = (time) => { magnet.position.y = 19 + Math.sin(time * 2 * Math.PI) * (inner.position.y > 0.5 ? 1.2 : 0); };
  g.userData.dims = [dim([-12.7, 40, 16], [12.7, 40, 16], "Ø 25.4 mm"), dim([16, 3, 0], [16, 35, 0], "32 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ ADXL355
function adxl355(part) {
  const g = new THREE.Group();
  const S = 20.3;
  g.add(pcb(S, S, C.pcbBlue));
  [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(([a, b]) => g.add(cyl(1.3, 1.7, "#e8e6df", [a * (S / 2 - 2), 0.82, b * (S / 2 - 2)])));
  g.add(header(pinSpecs(part, "P1"), { axis: "x", origin: [-6.35, 1.6, 7.3], type: "holes", header: "P1" }));
  g.add(header(pinSpecs(part, "P2"), { axis: "x", origin: [-6.35, 1.6, -7.3], type: "holes", header: "P2" }));
  const chip = new THREE.Group();
  const lid = grp(box(6, 1.2, 6, "#e9e6dc", [0, 0, 0]), labelPlane("ADXL355", 5, 2, { bg: "#e9e6dc", fg: "#6b7077", y: 0.61 }));
  lid.position.y = 1.6 + 1.5;
  const base = box(6, 0.8, 6, "#d8d3c6", [0, 1.6 + 0.4, 0]);
  const mems = new THREE.Group();
  mems.add(box(3, 0.2, 3, "#9a96ad", [0, 0, 0]));
  for (let i = 0; i < 7; i++) mems.add(box(0.15, 0.25, 1.1, "#7c7894", [-1.35 + i * 0.45, 0.05, 2.0]), box(0.15, 0.25, 1.1, "#7c7894", [-1.35 + i * 0.45, 0.05, -2.0]));
  mems.position.y = 1.6 + 0.9;
  chip.add(base, feat(mems, "chip"), feat(lid, "chip"));
  g.add(lab(chip, "ADXL355", V(0, 6, 0)));
  const ax = new THREE.Group();
  [[V(1, 0, 0), "#c27c74", "X"], [V(0, 0, -1), "#7fa58a", "Y"], [V(0, 1, 0), "#7b93ab", "Z"]].forEach(([dir, col, n]) => {
    const arrow = new THREE.ArrowHelper(dir, V(0, 0, 0), 7, col, 1.6, 1.0);
    const o = new THREE.Object3D(); o.position.copy(dir.clone().multiplyScalar(8)); lab(o, n);
    ax.add(arrow, o);
  });
  ax.position.set(0, 4, 0);
  g.add(ax);
  const hdr = grp(box(15.24, 2.5, 2.5, C.plastic, [0, 0, 7.3]), box(15.24, 2.5, 2.5, C.plastic, [0, 0, -7.3]));
  hdr.position.y = 12;
  g.add(lab(hdr, "6-pin headers (solder yourself)", V(0, 3, 0)));
  g.userData.explode = [{ obj: lid, offset: V(0, 6, 0) }, { obj: hdr, offset: V(0, 8, 0) }];
  g.userData.dims = [dim([-S / 2, 1.6, S / 2 + 3], [S / 2, 1.6, S / 2 + 3], "20.3 mm (0.8 in)")];
  return g;
}

// ------------------------------------------------------------------------------------------ AT24C02 (DIP-8)
function at24c02(part) {
  const g = new THREE.Group();
  const chip = ic({ w: 9.3, d: 6.4, h: 3.3, pitch: 2.54, pins: pinSpecs(part, "pins"), label: "AT24C02", sub: "2 kbit I²C", dip: true, pos: [0, 3.5, 0] });
  g.add(chip);
  g.userData.dims = [dim([-4.65, 0, 6], [4.65, 0, 6], "≈ 9.3 mm"), dim([6.5, 0, -3.81], [6.5, 0, 3.81], "7.62 mm rows")];
  return g;
}

// ------------------------------------------------------------------------------------------ TCA9548A
function tca9548a(part) {
  const g = new THREE.Group();
  const L = 43, W = 21;
  g.add(pcb(L, W, C.pcbBlue));
  g.add(header(pinSpecs(part, "top"), { axis: "x", origin: [-8.89, 1.6, -W / 2 + 2], type: "holes", header: "top" }));
  g.add(header(pinSpecs(part, "bottom"), { axis: "x", origin: [-19.05, 1.6, W / 2 - 2], type: "holes", header: "bottom" }));
  g.add(lab(feat(ic({ w: 7.8, d: 4.4, pitch: 0.65, pins: [], label: "TCA9548A", pos: [0, 1.6, 0] }), "chip"), "TCA9548A", V(0, 4, 0)));
  [[-10, 0], [10, 0], [14, -3], [-14, 3]].forEach(([x, z]) => g.add(smd(x, z)));
  g.userData.dims = [dim([-L / 2, 1.6, W / 2 + 3], [L / 2, 1.6, W / 2 + 3], "≈ 43 mm (est.)")];
  return g;
}

// ------------------------------------------------------------------------------------------ microSD card + breakout
function sdCardMesh(part, withPads = true) {
  const g = new THREE.Group();
  const s = new THREE.Shape();
  s.moveTo(0, 0); s.lineTo(11, 0); s.lineTo(11, 15); s.lineTo(1.5, 15); s.lineTo(1.5, 9.5); s.lineTo(0.6, 8.5); s.lineTo(0.6, 6.5); s.lineTo(0, 6.5); s.closePath();
  const geo = new THREE.ExtrudeGeometry(s, { depth: 1, bevelEnabled: false });
  geo.rotateX(-Math.PI / 2);
  geo.translate(-5.5, 0, 7.5);
  g.add(mesh(geo, M("#3f4a57")));
  g.add(Object.assign(labelPlane("64 GB\nHIGH ENDURANCE", 9, 6, { bg: "#3f4a57", fg: "#dfe3e8", y: 1.01 }), {}));
  g.children[1].position.set(0.3, 1.01, 2.5);
  if (withPads) {
    const pads = pinSpecs(part, "pads");
    pads.forEach((p, i) => {
      const m = box(0.8, 0.05, 3.4, C.gold, [-4.4 + i * 1.1, 1.03, -5.3], null, new THREE.MeshStandardMaterial({ color: C.gold, roughness: 0.35, metalness: 0.6 }));
      m.userData = { pin: { ...p, header: "pads", num: i + 1 }, anchor: V(-4.4 + i * 1.1, 1.05, -5.3), noEdges: true };
      g.add(m);
    });
    g.add(lab(new THREE.Object3D(), "pads are on the underside: drawn on top here", V(0, 2, -8.5)));
  }
  return g;
}
function sdCard(part) {
  const g = new THREE.Group();
  const c = sdCardMesh(part);
  g.add(c);
  g.userData.dims = [dim([-5.5, 0, 9], [5.5, 0, 9], "11 mm"), dim([7, 0, -7.5], [7, 0, 7.5], "15 mm")];
  return g;
}
function sdBreakout(part, parts) {
  const g = new THREE.Group();
  const L = 42, W = 24;
  g.add(pcb(L, W, C.pcbBlue));
  g.add(header(pinSpecs(part, "pins"), { axis: "z", origin: [-L / 2 + 2.5, 1.6, -6.35], type: "up", header: "pins" }));
  const sock = feat(grp(box(14, 1.8, 15, C.metal, [0, 0.9, 0], null, metalM())), "socket");
  sock.position.set(L / 2 - 9, 1.6, 0);
  g.add(lab(sock, "microSD socket", V(0, 4, 0)));
  const card = sdCardMesh(parts?.["sd-card"] || part, false);
  card.rotation.y = -Math.PI / 2;
  card.position.set(L / 2 - 9 + 3, 2.3, 0);
  g.add(card);
  g.add(lab(feat(ic({ w: 8.7, d: 3.9, pitch: 1.27, pins: [], label: "LVC125", pos: [-4, 1.6, 4] }), "buffer"), "74LVC125", V(0, 4, 0)));
  const ldo = grp(box(6.5, 1.6, 3.5, C.chip, [0, 0.8, 0]), labelPlane("AMS1117", 5.6, 2.6, { y: 1.61 }));
  ldo.position.set(-6, 1.6, -5);
  g.add(lab(feat(ldo, "ldo"), "AMS1117-3.3", V(0, 4, 0)));
  g.userData.explode = [{ obj: card, offset: V(16, 3, 0) }];
  g.userData.dims = [dim([-L / 2, 1.6, W / 2 + 3], [L / 2, 1.6, W / 2 + 3], "≈ 42 mm (typ.)")];
  return g;
}

// ------------------------------------------------------------------------------------------ RJ45
function rj45(part) {
  const g = new THREE.Group();
  const L = 30, W = 24;
  g.add(pcb(L, W, C.pcbOlive));
  const jack = new THREE.Group();
  jack.add(box(16, 13.5, 18, C.metal, [0, 6.75, 0], null, metalM()));
  jack.add(box(11.7, 7, 0.4, "#2b2d30", [0, 6, -9]));
  for (let i = 0; i < 8; i++) jack.add(box(0.35, 0.3, 4, C.gold, [-4.45 + i * 1.27, 8.6, -7.3], null, metalM(C.gold)));
  jack.position.set(0, 1.6, -2);
  g.add(lab(feat(jack, "jack"), "RJ45 · NOT ETHERNET", V(0, 16, 0)));
  g.add(header(pinSpecs(part, "pins"), { axis: "x", origin: [-8.89, 1.6, W / 2 - 2.5], type: "up", header: "pins" }));
  g.userData.dims = [dim([-L / 2, 1.6, W / 2 + 3], [L / 2, 1.6, W / 2 + 3], "≈ 30 mm (est.)")];
  return g;
}

// ------------------------------------------------------------------------------------------ Cat5e
function cat5e(part) {
  const g = new THREE.Group();
  const jacket = feat(cyl(2.7, 70, "#c9cfd6", [-35, 3, 0], "x", 32), "jacket");
  g.add(lab(jacket, "Cat5e · 4 twisted pairs", V(0, 6, 0)));
  const pairs = pinSpecs(part, "pairs");
  const cols = [C.orange, C.green, C.blue, C.brown];
  const centers = [[0.9, 0.9], [-0.9, 0.9], [-0.9, -0.9], [0.9, -0.9]];
  const twist = [5.5, 6.3, 7.1, 8.0];
  pairs.forEach((p, i) => {
    [0, Math.PI].forEach((ph, k) => {
      const pts = [];
      for (let s = 0; s <= 160; s++) {
        const x = (s / 160) * 50;
        const a = (x / twist[i]) * 2 * Math.PI + ph;
        const spread = 1 + Math.min(1, x / 40) * 2.2;
        pts.push(V(x, 3 + centers[i][1] * spread + Math.sin(a) * 0.62, centers[i][0] * spread + Math.cos(a) * 0.62));
      }
      const m = mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 160, 0.5, 8), M(k ? C.white : cols[i], { rough: 0.6 }));
      m.userData = { pin: { ...p, header: "pairs" }, noEdges: true };
      g.add(m);
    });
  });
  const plug = new THREE.Group();
  plug.add(box(21, 8, 11.7, "#e3eef2", [0, 0, 0], null, M("#e3eef2", { opacity: 0.45, rough: 0.2 })));
  for (let i = 0; i < 8; i++) plug.add(box(16, 0.3, 0.4, C.gold, [1, 3.6, -4.45 + i * 1.27], null, metalM(C.gold)));
  plug.position.set(-82, 3, 0);
  g.add(lab(feat(plug, "plug"), "RJ45 plug (T568B)", V(0, 7, 0)));
  return g;
}

// ------------------------------------------------------------------------------------------ breadboard
function breadboard() {
  const g = new THREE.Group();
  const L = 165, D = 55, H = 8.5;
  const top = new THREE.Group();
  top.add(feat(box(L, H, D, "#f2f0ea", [0, H / 2, 0]), "row"));
  const holes = [];
  const rowZ = [];
  for (let k = 0; k < 5; k++) { rowZ.push(3.81 + k * 2.54, -(3.81 + k * 2.54)); }
  for (let c = 0; c < 63; c++) for (const z of rowZ) holes.push([-78.74 + c * 2.54, z]);
  const railZ = [20.3, 22.84, -20.3, -22.84];
  for (const z of railZ) for (let k = 0; k < 50; k++) holes.push([-74 + (k + Math.floor(k / 5)) * 2.54, z]);
  const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(1.1, 0.2, 1.1), M("#3b3e42"), holes.length);
  const m4 = new THREE.Matrix4();
  holes.forEach(([x, z], i) => { m4.makeTranslation(x, H + 0.01, z); inst.setMatrixAt(i, m4); });
  inst.userData.noEdges = true;
  top.add(inst);
  [[24.6, "#c27c74"], [-24.6, "#c27c74"], [18.5, "#7b93ab"], [-18.5, "#7b93ab"]].forEach(([z, col]) => { const ln = box(150, 0.05, 0.4, col, [0, H + 0.02, z]); ln.userData.noEdges = true; top.add(ln); });
  const gap = feat(box(L - 4, 0.6, 3.5, "#e3e0d7", [0, H - 0.2, 0]), "gap");
  top.add(lab(gap, "centre gap", V(-70, 2, 0)));
  // invisible hover zones for rails
  railZ.forEach((z) => { const r = feat(box(150, 1, 2.2, "#000", [0, H + 0.3, z]), "rail"); r.material = r.material.clone(); r.material.transparent = true; r.material.opacity = 0; r.userData.noEdges = true; top.add(r); });
  const clips = new THREE.Group();
  const clipM = metalM("#c7b98f");
  for (let c = 0; c < 63; c++) for (const s of [1, -1]) clips.add(Object.assign(box(1.6, 3, 10.6, C.gold, [-78.74 + c * 2.54, 3, s * (3.81 + 5.08)], null, clipM), { userData: { noEdges: true } }));
  for (const z of railZ) clips.add(Object.assign(box(148, 3, 1.4, C.gold, [0, 3, z], null, clipM), { userData: { noEdges: true } }));
  feat(clips, "clip");
  g.add(top, lab(clips, "spring clips", V(70, 6, 0)));
  g.userData.explode = [{ obj: top, offset: V(0, 22, 0), fade: 0.55 }];
  g.userData.dims = [dim([-L / 2, 0, D / 2 + 5], [L / 2, 0, D / 2 + 5], "≈ 165 mm"), dim([L / 2 + 5, 0, -D / 2], [L / 2 + 5, 0, D / 2], "≈ 55 mm")];
  return g;
}

// ------------------------------------------------------------------------------------------ passives
const BAND = { black: "#3a3a3a", brown: "#8a6a52", red: "#c27c74", orange: "#d29b6f", yellow: "#d6c27a", green: "#7fa58a", blue: "#7b93ab", violet: "#9b90b5", grey: "#9a9ea3", white: "#eeeeea", gold: "#c9ad6e" };
export function resistor(bands, key, label) {
  const g = new THREE.Group();
  const body = cyl(1.2, 6.3, "#e2d3b5", [0, 0, 0], "x", 20);
  g.add(body, mesh(new THREE.SphereGeometry(1.35, 16, 12), M("#e2d3b5"), [-3.1, 0, 0]), mesh(new THREE.SphereGeometry(1.35, 16, 12), M("#e2d3b5"), [3.1, 0, 0]));
  bands.forEach((b, i) => g.add(Object.assign(cyl(1.27, 0.55, BAND[b], [-2.3 + i * 1.25 + (i === 3 ? 0.6 : 0), 0, 0], "x", 20), { userData: { noEdges: true } })));
  const leadM = metalM("#b8bcc0");
  g.add(cyl(0.3, 8, null, [-8, 0, 0], "x", 8, leadM), cyl(0.3, 8, null, [8, 0, 0], "x", 8, leadM));
  if (key) feat(g, key);
  if (label) lab(g, label, new THREE.Vector3(0, 4, 0));
  return g;
}
function passives() {
  const g = new THREE.Group();
  const rs = [[["yellow", "violet", "brown", "gold"], "r470", "470 Ω"], [["red", "red", "brown", "gold"], "r220", "220 Ω"], [["blue", "grey", "yellow", "gold"], "r680k", "680 kΩ ✗"]];
  rs.forEach(([b, k, l], i) => { const r = resistor(b, k, l); r.position.set(-20, 2, -14 + i * 12); g.add(r); });
  const disc = new THREE.Group();
  disc.add(cyl(2.6, 1.4, "#d6a37b", [0, 6, 0], "z", 28), cyl(0.25, 6, null, [-1.2, 1.5, 0], "y", 8, metalM()), cyl(0.25, 6, null, [1.2, 1.5, 0], "y", 8, metalM()));
  const lp = labelPlane("104", 3, 2, { bg: "#d6a37b", fg: "#5b4a3c" }); lp.rotation.set(0, 0, 0); lp.position.set(0, 6, 0.72); disc.add(lp);
  disc.position.set(12, 0, -8);
  g.add(lab(feat(disc, "c100n"), "100 nF (104)", V(0, 11, 0)));
  const el = new THREE.Group();
  el.add(cyl(2.5, 11, "#5e6b7a", [0, 7.5, 0], "y", 28), Object.assign(cyl(2.52, 11, "#b9c2cb", [0, 7.5, 0], "y", 28), {}), cyl(0.25, 3, null, [-1, 0.5, 0], "y", 8, metalM()), cyl(0.25, 4, null, [1, 0, 0], "y", 8, metalM()));
  el.children[1].geometry = new THREE.CylinderGeometry(2.52, 2.52, 11, 28, 1, true, -0.5, 1.0);
  el.position.set(12, 0, 10);
  g.add(lab(feat(el, "c10u"), "10 µF (stripe = −)", V(0, 16, 0)));
  return g;
}

// ------------------------------------------------------------------------------------------ flux pen
function fluxPen() {
  const g = new THREE.Group();
  const barrel = feat(grp(cyl(8, 105, "#e4dfd0", [0, 0, 0], "x", 32), cyl(8.05, 30, "#bda56b", [-20, 0, 0], "x", 32)), "tip");
  barrel.children[1].geometry = new THREE.CylinderGeometry(8.05, 8.05, 30, 32, 1, true);
  const tip = feat(grp(cyl(3, 8, "#9a9ea3", [56.5, 0, 0], "x", 20), mesh(new THREE.ConeGeometry(2.4, 6, 20), M("#f0ece0"), [63.5, 0, 0])), "tip");
  tip.children[1].rotation.z = -Math.PI / 2;
  const cap = feat(cyl(8.4, 32, "#7b93ab", [56, 0, 0], "x", 32), "cap");
  const pen = grp(barrel, tip, cap);
  pen.position.y = 8.4;
  g.add(lab(pen, "FLUX", V(-20, 10, 0)));
  g.userData.explode = [{ obj: cap, offset: V(40, 0, 0) }];
  return g;
}

export const BUILDERS = {
  "esp32-devkit": esp32Devkit, "esp32-s3": esp32s3, adc15, ads131m04, osc8m, hx711, yzc133, sm24, adxl355, at24c02, tca9548a,
  "sd-breakout": sdBreakout, "sd-card": sdCard, rj45, cat5e, breadboard, passives, "flux-pen": fluxPen,
};

export function buildPart(part, partsById) {
  const fn = BUILDERS[part.id];
  if (!fn) throw new Error(`no 3D model for ${part.id}`);
  const g = fn(part, partsById);
  g.userData.partId = part.id;
  g.traverse((o) => { if (o.userData.pin) o.userData.pin.part = part.id; });
  return g;
}
