// Build it: assemble parts and jumper wires step by step on one 3D stage.
import { app, el, L, t, load } from "../core.js";
import { render } from "../md.js";
import { setContext } from "../ask.js";
import { hydrateTerms } from "../glossary.js";
import { buildStep } from "../progress.js";
import { refreshChrome } from "../app.js";
import { pinText } from "./part.js";

const WIRE_COLORS = { red: "#c27c74", black: "#4a4d52", green: "#7fa58a", white: "#e9e7e0", blue: "#7b93ab", violet: "#9b90b5", yellow: "#d6c27a", orange: "#d29b6f", grey: "#9a9ea3", brown: "#9a7a62" };

export default async function buildView(root, { id, builds }) {
  const hu = app.lang === "hu";
  const b = builds.find((x) => x.id === id) || builds[0];
  const data = await load("parts.json");
  const byId = Object.fromEntries(data.parts.map((p) => [p.id, p]));
  const wrap = el("div.wrap.wide");
  root.append(wrap);
  wrap.append(el("div.hero", el("div.kicker", `${b.code} · ${t("builds")}`), el("h1", L(b.title)), el("p", L(b.blurb)),
    el("div.meta-row", builds.map((x) => el(`a.chip${x.id === b.id ? "" : ""}`, { href: `#/build/${x.id}`, style: x.id === b.id ? { borderColor: "var(--ink)" } : null }, `${x.code} ${L(x.title)}`)),
      b.source ? el("span.chip", "src: ", b.source) : null)));

  const stage = el("div.stage", { style: { height: "560px" } });
  const tip = el("div.pin-tip");
  const hud = el("div.hud", b.proposal ? (hu ? "⚠ S3 vezetékek: JAVASOLT lábkiosztás, nincs eldöntve" : "⚠ S3 wires: PROPOSED pin map, not decided") : t("explodeHint"));
  stage.append(hud, tip);
  const exp = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: 0 });
  const labelsBtn = el("button.btn", { type: "button" }, t("labels"));
  const resetBtn = el("button.btn", { type: "button" }, t("reset"));
  stage.append(el("div.tools", labelsBtn, resetBtn), el("div.slider", t("explode"), exp));
  const steps = el("ol.steps");
  const prevB = el("button.btn", { type: "button" }, "← ", t("prev"));
  const nextB = el("button.btn.primary", { type: "button" }, t("next"), " →");
  const allB = el("button.btn", { type: "button" }, hu ? "Mind" : "All");
  const legend = el("div.legend", Object.entries(data.kinds).filter(([k]) => b.wires.some((w) => w.kind === k)).map(([, v]) => el("span", el("span.swatch", { style: { background: v[2] } }), v[hu ? 1 : 0])));
  wrap.append(stage, el("div.done-bar", { style: { margin: "14px 0" } }, prevB, nextB, allB, el("span", { style: { flex: 1 } }), legend), steps);

  let cur = 0;
  const total = b.steps.length;
  b.steps.forEach((s, i) => steps.append(el("li", { onclick: () => go(i) }, el("div.t", L(s.title)), el("div.d.prose", { html: render(L(s.text)) }))));
  hydrateTerms(steps);

  let viewer, THREE, insts = {}, wires = {};
  try {
    THREE = await import("three");
    const [{ createViewer }, { buildPart, resistor }, { wire }] = await Promise.all([import("../three/viewer.js"), import("../three/parts3d.js"), import("../three/kit3d.js")]);
    viewer = createViewer(stage, {
      onHover(info, at) {
        if (!info) { tip.style.display = "none"; return; }
        const part = byId[info.part] || { features: {} };
        const { title, body, color } = info.wire ? { title: info.name, body: L(info.fn), color: data.kinds[info.kind]?.[2] } : pinText(data, part, info);
        tip.replaceChildren(el("b", title), el("div", body), info.part && byId[info.part] ? el("div", { style: { color: "var(--ink-3)", fontSize: "11px" } }, L(byId[info.part].name)) : null);
        tip.style.borderLeft = color ? `3px solid ${color}` : "";
        tip.style.display = "block";
        tip.style.left = `${Math.min(at.x + 14, stage.clientWidth - 290)}px`;
        tip.style.top = `${Math.min(at.y + 14, stage.clientHeight - 80)}px`;
      },
    });
    const scene = new THREE.Group();
    // extra builders used only in assemblies
    const extra = {
      series690: () => {
        const g = new THREE.Group();
        const r1 = resistor(["yellow", "violet", "brown", "gold"], null, null), r2 = resistor(["red", "red", "brown", "gold"], null, null);
        r1.position.x = -8; r2.position.x = 14;
        g.add(r1, r2);
        const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 6, 12), new THREE.MeshStandardMaterial({ color: "#3a3d42", roughness: 0.8 }));
        sleeve.rotation.z = Math.PI / 2; sleeve.position.x = 3; g.add(sleeve);
        const ends = [["A", -16], ["B", 22]].map(([n, x]) => {
          const m = new THREE.Mesh(new THREE.SphereGeometry(0.9, 12, 10), new THREE.MeshStandardMaterial({ color: "#b8bcc0", metalness: 0.5, roughness: 0.4 }));
          m.position.set(x, 0, 0);
          m.userData = { pin: { name: n, header: "ends", kind: "power", fn: { en: "470 Ω + 220 Ω in series = 690 Ω (joints insulated)", hu: "470 Ω + 220 Ω sorosan = 690 Ω (szigetelt kötések)" } }, anchor: new THREE.Vector3(x, 0, 0), noEdges: true };
          return m;
        });
        g.add(...ends);
        g.userData.label = "470 Ω + 220 Ω = 690 Ω"; g.userData.labelAt = new THREE.Vector3(3, 5, 0);
        return g;
      },
      shunt: () => {
        const g = resistor(["brown", "orange", "orange", "brown"], null, "≈ 1.3 kΩ shunt");
        [["A", -12], ["B", 12]].forEach(([n, x]) => {
          const m = new THREE.Mesh(new THREE.SphereGeometry(0.8, 12, 10), new THREE.MeshStandardMaterial({ color: "#b8bcc0" }));
          m.position.set(x, 0, 0);
          m.userData = { pin: { name: n, header: "ends", kind: "analog", fn: { en: "Damping shunt across the geophone coil (1339 Ω gives ζ ≈ 0.6)", hu: "Csillapító sönt a geofon tekercsén (1339 Ω-mal ζ ≈ 0,6)" } }, anchor: new THREE.Vector3(x, 0, 0), noEdges: true };
          g.add(m);
        });
        return g;
      },
    };
    for (const inst of b.instances) {
      const g = byId[inst.part] ? buildPart(byId[inst.part], byId) : extra[inst.part]();
      g.position.set(...inst.pos);
      if (inst.rotY) g.rotation.y = inst.rotY;
      g.userData.home = g.position.clone();
      g.traverse((o) => { if (o.userData.pin && !o.userData.pin.part) o.userData.pin.part = inst.part; });
      g.visible = false;
      scene.add(g);
      insts[inst.id] = g;
    }
    // collect sub-explodes so the Explode slider separates parts too
    scene.updateMatrixWorld(true);
    const findPin = (instId, h, name) => {
      let hit = null;
      insts[instId]?.traverse((o) => { if (!hit && o.userData.pin && !o.userData.pin.feature && o.userData.pin.header === h && o.userData.pin.name === name) hit = o; });
      return hit;
    };
    for (const w of b.wires) {
      const a = findPin(...w.from), c = findPin(...w.to);
      if (!a || !c) { console.warn("wire end not found", w); continue; }
      const pa = viewer.pinWorld(a), pc = viewer.pinWorld(c);
      const m = wire(pa, pc, WIRE_COLORS[w.color] || "#999", { lift: 14 + (Object.keys(wires).length % 5) * 3 });
      const nameA = `${w.from[0]}.${w.from[2]}`, nameB = `${w.to[0]}.${w.to[2]}`;
      m.userData.pin = { wire: true, name: `${nameA} → ${nameB}`, kind: w.kind, fn: w.proposal ? { en: "Proposed GPIO: the S3 pin map is not decided yet", hu: "Javasolt GPIO: az S3 lábkiosztás még nincs eldöntve" } : { en: data.kinds[w.kind]?.[0] || "", hu: data.kinds[w.kind]?.[1] || "" } };
      m.visible = false;
      scene.add(m);
      wires[w.id] = m;
    }
    viewer.setObject(scene, { scale: 0.62 });
    viewer.setLabels(false);
    const center = new THREE.Box3().setFromObject(scene).getCenter(new THREE.Vector3());
    scene.userData.explode = Object.values(insts).map((g) => ({ obj: g, base: g.userData.home.clone(), offset: g.position.clone().sub(center).setY(0).multiplyScalar(0.35).add(new THREE.Vector3(0, 10, 0)) }));
    exp.addEventListener("input", () => {
      viewer.setExplode(+exp.value);
      Object.values(wires).forEach((m) => { m.material.transparent = true; m.material.opacity = 1 - +exp.value * 0.85; });
    });
    labelsBtn.addEventListener("click", () => { labelsBtn.classList.toggle("on"); viewer.setLabels(labelsBtn.classList.contains("on")); });
    resetBtn.addEventListener("click", () => viewer.reset());
  } catch (e) {
    console.error(e);
    stage.append(el("div.hud", { style: { top: "40px" } }, `3D unavailable: ${e.message}`));
  }

  let anims = [];
  function go(i) {
    cur = Math.max(0, Math.min(total - 1, i));
    const shown = new Set(), wired = new Set();
    b.steps.slice(0, cur + 1).forEach((s) => { s.show.forEach((x) => shown.add(x)); s.wires.forEach((x) => wired.add(x)); });
    const now = b.steps[cur];
    for (const [k, g] of Object.entries(insts)) {
      const was = g.visible;
      g.visible = shown.has(k);
      if (g.visible && !was && THREE) { g.position.copy(g.userData.home).add(new THREE.Vector3(0, 60, 0)); anims.push({ g, t0: performance.now() }); }
    }
    for (const [k, m] of Object.entries(wires)) {
      m.visible = wired.has(k);
      const active = now.wires.includes(k);
      m.scale.setScalar(1);
      if (m.material) { m.material.emissive?.set(active ? "#3a2a20" : "#000000"); }
    }
    steps.querySelectorAll("li").forEach((li, k) => { li.classList.toggle("on", k === cur); li.classList.toggle("past", k < cur); });
    prevB.disabled = cur === 0;
    nextB.textContent = cur === total - 1 ? `✓ ${t("done")}` : `${t("next")} →`;
    buildStep(b.id, cur + 1, total, b.title.en);
    refreshChrome();
    setContext({ title: `${b.code} ${L(b.title)} · ${t("step")} ${cur + 1}/${total}`, excerpt: `${L(b.blurb)}\n\nStep ${cur + 1}: ${L(now.title)}\n${L(now.text)}` });
  }
  (function animate() {
    if (!wrap.isConnected) return;
    const now = performance.now();
    anims = anims.filter(({ g, t0 }) => {
      const k = Math.min(1, (now - t0) / 650);
      const e = 1 - Math.pow(1 - k, 3);
      g.position.y = g.userData.home.y + 60 * (1 - e);
      return k < 1;
    });
    requestAnimationFrame(animate);
  })();
  prevB.addEventListener("click", () => go(cur - 1));
  nextB.addEventListener("click", () => go(cur + 1));
  allB.addEventListener("click", () => go(total - 1));
  go(0);
  return () => viewer?.dispose();
}
