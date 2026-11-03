// Building blocks for the procedural part models. Units: millimetres. Y is up; boards lie in the XZ plane.
import * as THREE from "three";

export const C = {
  pcbSage: "#8fa597", pcbSlate: "#64707e", pcbCharcoal: "#555a61", pcbBlue: "#6f879c", pcbClick: "#7c8a85", pcbOlive: "#8f9479",
  metal: "#c9ccd0", metalDark: "#a7abb0", gold: "#cdb984", plastic: "#4a4d52", plasticWhite: "#eeece5", chip: "#43464b",
  alu: "#c3c8cc", copper: "#c49a7a", blueTerm: "#7d9bb5", silicone: "#f1efe8", rubber: "#5a5d61",
  red: "#c27c74", black: "#45484c", green: "#7fa58a", white: "#ecebe6", yellow: "#d6c27a", orange: "#d29b6f", brown: "#9a7a62", blue: "#7b93ab", grey: "#9a9ea3", violet: "#9b90b5",
  led: "#9fc4a8", ledRed: "#d58f86",
};

const mats = new Map();
export function M(color, { rough = 0.82, metal = 0, opacity = 1, emissive } = {}) {
  const key = `${color}|${rough}|${metal}|${opacity}|${emissive || ""}`;
  if (!mats.has(key)) {
    mats.set(key, new THREE.MeshStandardMaterial({
      color, roughness: rough, metalness: metal, transparent: opacity < 1, opacity, emissive: emissive || "#000000", flatShading: false,
    }));
  }
  return mats.get(key);
}
export const metalM = (c = C.metal) => M(c, { rough: 0.45, metal: 0.55 });

export function mesh(geo, mat, pos = [0, 0, 0], name) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(...pos);
  m.castShadow = true;
  m.receiveShadow = true;
  if (name) m.name = name;
  return m;
}
/** Box centred on pos. */
export const box = (w, h, d, color, pos, name, mat) => mesh(new THREE.BoxGeometry(w, h, d), mat || M(color), pos, name);
/** Cylinder along an axis, centred on pos. */
export function cyl(r, h, color, pos = [0, 0, 0], axis = "y", seg = 28, mat, r2) {
  const m = mesh(new THREE.CylinderGeometry(r, r2 ?? r, h, seg), mat || M(color), pos);
  if (axis === "x") m.rotation.z = Math.PI / 2;
  if (axis === "z") m.rotation.x = Math.PI / 2;
  return m;
}

/** A flat label (canvas texture) lying on top of something, facing up. */
export function labelPlane(text, w, d, { bg = C.chip, fg = "#d9d6cc", font = "600 46px IBM Plex Mono, monospace", y = 0, lines } = {}) {
  const cv = document.createElement("canvas");
  const scale = 512 / Math.max(w, d);
  cv.width = Math.max(64, Math.round(w * scale));
  cv.height = Math.max(64, Math.round(d * scale));
  const g = cv.getContext("2d");
  g.fillStyle = bg; g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = fg; g.textAlign = "center"; g.textBaseline = "middle";
  const ls = lines || String(text).split("\n");
  const px = Math.min(parseInt(font.match(/(\d+)px/)[1], 10), (cv.height / (ls.length + 0.6)) * 0.8);
  g.font = font.replace(/\d+px/, `${px}px`);
  ls.forEach((l, i) => g.fillText(l, cv.width / 2, cv.height / 2 + (i - (ls.length - 1) / 2) * px * 1.15, cv.width * 0.92));
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9 }));
  m.rotation.x = -Math.PI / 2;
  m.position.y = y;
  m.userData.noEdges = true;
  return m;
}

/** PCB slab, top surface at y = t. */
export function pcb(w, d, color, t = 1.6, name = "pcb") {
  const g = box(w, t, d, color, [0, t / 2, 0], name);
  return g;
}

/** Mark a mesh as a hoverable feature (not a pin): shows name + text on hover. */
export function feature(obj, name, fn, kind = "feature") {
  obj.traverse?.((o) => { if (o.isMesh) o.userData.pin = { name, fn, kind, feature: true }; });
  return obj;
}

/**
 * A row of header pins.
 * pins: [{name, kind, fn, num}] in order. opts: {pitch, axis ('x'|'z'), origin [x,y,z] of pin 1 at board surface,
 *   type: 'down'|'up'|'female'|'holes', header, partId, stub}
 * Returns a group; each pin mesh has userData.pin and userData.anchor (local free end).
 */
export function header(pins, { pitch = 2.54, axis = "z", origin = [0, 1.6, 0], type = "down", header: hname = "", dir = 1, plastic = true, boardT = 1.6 } = {}) {
  const g = new THREE.Group();
  const n = pins.length;
  const step = (i) => (axis === "x" ? [origin[0] + i * pitch * dir, origin[1], origin[2]] : [origin[0], origin[1], origin[2] + i * pitch * dir]);
  const len = n * pitch;
  const mid = step((n - 1) / 2);
  if (type === "down" && plastic) g.add(box(axis === "x" ? len : 2.5, 2.5, axis === "x" ? 2.5 : len, C.plastic, [mid[0], origin[1] - boardT - 1.25, mid[2]], "header-plastic"));
  if (type === "up" && plastic) g.add(box(axis === "x" ? len : 2.5, 2.5, axis === "x" ? 2.5 : len, C.plastic, [mid[0], origin[1] + 1.25, mid[2]], "header-plastic"));
  if (type === "female") g.add(box(axis === "x" ? len : 2.6, 8.5, axis === "x" ? 2.6 : len, C.plastic, [mid[0], origin[1] + 4.25, mid[2]], "female-header"));
  pins.forEach((p, i) => {
    const [x, y, z] = step(i);
    let m;
    const pinMat = new THREE.MeshStandardMaterial({ color: p.kind === "nc" ? C.metalDark : C.gold, roughness: 0.35, metalness: 0.6 });
    if (type === "down") { m = mesh(new THREE.BoxGeometry(0.64, 11.5, 0.64), pinMat, [x, y - boardT - 3.5, z]); m.userData.anchor = new THREE.Vector3(x, y - boardT - 9.2, z); }
    else if (type === "up") { m = mesh(new THREE.BoxGeometry(0.64, 9, 0.64), pinMat, [x, y + 3.5, z]); m.userData.anchor = new THREE.Vector3(x, y + 8, z); }
    else if (type === "female") { m = mesh(new THREE.BoxGeometry(1.1, 0.3, 1.1), M("#222428"), [x, y + 8.56, z]); m.userData.anchor = new THREE.Vector3(x, y + 8.6, z); }
    else { m = cyl(0.75, 0.2, C.gold, [x, y + 0.02, z], "y", 16, pinMat); m.userData.anchor = new THREE.Vector3(x, y + 0.2, z); }
    m.name = `pin:${hname}:${p.name}`;
    m.userData.pin = { ...p, header: hname, num: p.num ?? i + 1 };
    m.userData.noEdges = true;
    g.add(m);
    if (type !== "holes") g.add(Object.assign(cyl(0.9, 0.3, C.gold, [x, y + 0.15, z], "y", 14, metalM(C.gold)), { userData: { noEdges: true } }));
  });
  return g;
}

/** Gull-wing IC (SOIC / TSSOP / MSOP). pins: array in datasheet order (pin 1 at -X,+Z corner, counter-clockwise from the top). */
export function ic({ w, d, h = 1.1, pitch = 0.65, pins = [], label = "", sub = "", leadLen = 0.9, pos = [0, 1.6, 0], dip = false }) {
  const g = new THREE.Group();
  g.position.set(...pos);
  const body = box(w, h, d, C.chip, [0, h / 2 + (dip ? 0.6 : 0.1), 0], "ic-body");
  g.add(body);
  if (label) g.add(labelPlane(sub ? `${label}\n${sub}` : label, w * 0.86, d * 0.8, { y: h + (dip ? 0.61 : 0.11) }));
  g.add(cyl(Math.min(w, d) * 0.06 + 0.15, 0.05, "#2f3236", [-w / 2 + Math.min(w, d) * 0.16 + 0.2, h + (dip ? 0.62 : 0.12), d / 2 - Math.min(w, d) * 0.16 - 0.2]));
  const per = Math.ceil(pins.length / 2);
  // Top view, pin 1 at the (-x, +z) corner, numbered counter-clockwise: pins 1..N/2 along z = +d/2 from -x to +x,
  // then N/2+1..N along z = -d/2 from +x back to -x.
  const c = (per - 1) / 2;
  pins.forEach((p, i) => {
    const first = i < per;
    const k = first ? i : i - per;
    const x = first ? (-c + k) * pitch : (c - k) * pitch;
    const z = first ? d / 2 : -d / 2;
    const zz = z + Math.sign(z) * (dip ? 0.4 : leadLen / 2);
    const pinMat = new THREE.MeshStandardMaterial({ color: C.metal, roughness: 0.4, metalness: 0.6 });
    const lead = dip
      ? mesh(new THREE.BoxGeometry(0.5, 3.4, 0.25), pinMat, [x, -1.0, z + Math.sign(z) * 0.15])
      : mesh(new THREE.BoxGeometry(Math.min(0.3, pitch * 0.5), 0.15, leadLen), pinMat, [x, 0.08, zz]);
    lead.name = `pin:${label}:${p.name}`;
    lead.userData.pin = { ...p, num: p.num ?? i + 1, header: label };
    lead.userData.noEdges = true;
    lead.userData.anchor = new THREE.Vector3(x, 0.1, zz);
    g.add(lead);
  });
  return g;
}

/** Small SMD passive (resistor/capacitor). */
export const smd = (x, z, rot = 0, kind = "r", y = 1.6) => {
  const g = new THREE.Group();
  g.add(box(1.6, 0.5, 0.8, kind === "r" ? "#2f3236" : "#b7a58b", [0, 0.25, 0]));
  g.add(box(0.3, 0.52, 0.82, C.metal, [-0.65, 0.26, 0], null, metalM()), box(0.3, 0.52, 0.82, C.metal, [0.65, 0.26, 0], null, metalM()));
  g.position.set(x, y, z);
  g.rotation.y = rot;
  g.traverse((o) => (o.userData.noEdges = true));
  return g;
};

export function usbMicro(pos, rotY = 0) {
  const g = new THREE.Group();
  g.add(box(7.5, 2.6, 5.4, C.metal, [0, 1.3, 0], "usb", metalM()), box(6.4, 1.6, 0.2, "#2c2e31", [0, 1.4, -2.75]));
  g.position.set(...pos); g.rotation.y = rotY;
  return g;
}
export function usbC(pos, rotY = 0) {
  const g = new THREE.Group();
  const shape = new THREE.Shape();
  const w = 8.9, h = 3.2, r = 1.5;
  shape.moveTo(-w / 2 + r, -h / 2); shape.lineTo(w / 2 - r, -h / 2); shape.absarc(w / 2 - r, 0, r, -Math.PI / 2, Math.PI / 2); shape.lineTo(-w / 2 + r, h / 2); shape.absarc(-w / 2 + r, 0, r, Math.PI / 2, Math.PI * 1.5);
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 7.3, bevelEnabled: false });
  const m = mesh(geo, metalM(), [0, h / 2, -3.65]);
  g.add(m, box(6.6, 0.7, 0.2, "#2c2e31", [0, h / 2, -3.7]));
  g.position.set(...pos); g.rotation.y = rotY;
  return g;
}
export function button(pos, label) {
  const g = new THREE.Group();
  g.add(box(4.2, 1.6, 3.2, C.metal, [0, 0.8, 0], null, metalM()), cyl(1, 0.9, "#3c3f44", [0, 2.0, 0]));
  g.position.set(...pos);
  if (label) g.userData.label = label;
  return g;
}
export function led(pos, color = C.led) {
  const m = box(1.6, 0.6, 0.8, color, pos, "led", M(color, { emissive: color, rough: 0.5 }));
  m.material = m.material.clone(); m.material.emissiveIntensity = 0.25;
  return m;
}

/** Screw terminal block with n poles. Wire entries face -Z. */
export function screwTerminal(n, pitch, pos, names = []) {
  const g = new THREE.Group();
  const w = n * pitch;
  g.add(box(w, 8.5, 7.5, C.blueTerm, [0, 4.25, 0], "terminal"));
  for (let i = 0; i < n; i++) {
    const x = -w / 2 + pitch * (i + 0.5);
    g.add(cyl(1.4, 0.6, C.metal, [x, 8.6, 0.8], "y", 20, metalM()), box(2.2, 0.25, 0.5, "#6e7176", [x, 8.95, 0.8]));
    const hole = box(2.6, 2.6, 0.3, "#2c2e31", [x, 3.0, -3.8]);
    hole.userData.noEdges = true;
    if (names[i]) { hole.userData.pin = names[i]; hole.userData.anchor = new THREE.Vector3(x, 3.0, -4.2); hole.name = `pin:term:${names[i].name}`; }
    g.add(hole);
  }
  g.position.set(...pos);
  return g;
}

/** A metal-can module (ESP32-WROOM style): PCB + shield + antenna area. */
export function wroom({ w = 18, d = 25.5, can = [15.8, 17.6], label = "ESP32-WROOM-32", pos = [0, 1.6, 0], rotY = 0 }) {
  const g = new THREE.Group();
  g.add(box(w, 0.8, d, "#3c4248", [0, 0.4, 0], "module-pcb"));
  const cz = d / 2 - can[1] / 2 - 0.9;
  g.add(box(can[0], 2.4, can[1], C.metal, [0, 0.8 + 1.2, cz], "shield-can", metalM("#cfd2d5")));
  g.add(labelPlane(label, can[0] * 0.8, can[1] * 0.45, { bg: "#cfd2d5", fg: "#5b6068", y: 3.21 }).translateZ(0).translateY(0));
  g.children[g.children.length - 1].position.set(0, 3.21, cz);
  // antenna meander
  const az = -d / 2 + (d - can[1] - 1.8) / 2;
  for (let i = 0; i < 6; i++) g.add(Object.assign(box(0.6, 0.06, d - can[1] - 3.5, C.gold, [-w / 2 + 2.5 + i * 2.4, 0.83, az], null, metalM(C.gold)), { userData: { noEdges: true } }));
  g.position.set(...pos); g.rotation.y = rotY;
  return g;
}

/** Wire (jumper) between two world points with a sag/lift. */
export function wire(a, b, color, { lift = 18, r = 0.7, sag = 0 } = {}) {
  const mid = a.clone().lerp(b, 0.5);
  const dist = a.distanceTo(b);
  const up = Math.max(a.y, b.y) + lift + dist * 0.08 - sag;
  const curve = new THREE.CatmullRomCurve3([
    a.clone(), a.clone().add(new THREE.Vector3(0, (up - a.y) * 0.6, 0)),
    new THREE.Vector3(mid.x, up, mid.z),
    b.clone().add(new THREE.Vector3(0, (up - b.y) * 0.6, 0)), b.clone(),
  ]);
  const m = mesh(new THREE.TubeGeometry(curve, 64, r, 8, false), M(color, { rough: 0.6 }));
  m.userData.noEdges = true;
  return m;
}

/** Dotted dimension line between two points with a label (rendered by the viewer as CSS2D). */
export function dim(a, b, text) { return { a: new THREE.Vector3(...a), b: new THREE.Vector3(...b), text }; }
