// A Three.js stage: orbit controls, soft light, engineering edges, hoverable pins, explode, labels, dimensions.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

const EDGE = new THREE.LineBasicMaterial({ color: 0x3a3e44, transparent: true, opacity: 0.32 });
const DIM = new THREE.LineDashedMaterial({ color: 0x8b9097, dashSize: 1.2, gapSize: 1.2 });

export function createViewer(container, { onHover, onClick } = {}) {
  const W = () => container.clientWidth, H = () => container.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio));
  renderer.setSize(W(), H());
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.append(renderer.domElement);

  const labels = new CSS2DRenderer();
  labels.setSize(W(), H());
  Object.assign(labels.domElement.style, { position: "absolute", left: 0, top: 0, pointerEvents: "none" });
  container.append(labels.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, W() / H(), 0.5, 8000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0xd9d4c6, 1.35));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  scene.add(sun, sun.target);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), new THREE.ShadowMaterial({ opacity: 0.13 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const halo = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 14), new THREE.MeshBasicMaterial({ color: 0xc1937c, transparent: true, opacity: 0.45, depthTest: false }));
  halo.renderOrder = 10;
  halo.visible = false;
  scene.add(halo);

  let root = null, explodeT = 0, showLabels = true, showDims = false, pickables = [], dimGroup = null, labelObjs = [], hovered = null, lockHL = null;
  const ray = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function addEdges(obj) {
    obj.traverse((o) => {
      if (!o.isMesh || o.userData.noEdges || o.userData.edged || o.geometry.attributes.position.count > 6000) return;
      o.userData.edged = true;
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 28), EDGE);
      e.raycast = () => {};
      o.add(e);
    });
  }

  let fitScale = 0.95;
  function fit(obj, keep = false) {
    const b = new THREE.Box3().setFromObject(obj);
    const s = b.getBoundingSphere(new THREE.Sphere());
    const dist = s.radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * fitScale;
    controls.target.copy(s.center);
    if (!keep) camera.position.copy(s.center).add(new THREE.Vector3(0.55, 0.75, 0.9).normalize().multiplyScalar(dist));
    camera.near = Math.max(0.1, dist / 200);
    camera.far = dist * 30;
    camera.updateProjectionMatrix();
    sun.position.copy(s.center).add(new THREE.Vector3(-0.6, 1.4, 0.8).multiplyScalar(s.radius * 2.5));
    sun.target.position.copy(s.center);
    const sc = sun.shadow.camera;
    sc.left = sc.bottom = -s.radius * 1.6; sc.right = sc.top = s.radius * 1.6; sc.near = 1; sc.far = s.radius * 8;
    sc.updateProjectionMatrix();
    ground.position.y = b.min.y - 0.01;
    halo.scale.setScalar(Math.max(0.9, s.radius / 70));
    controls.update();
  }

  function rebuildLabels() {
    labelObjs.forEach((l) => l.removeFromParent());
    labelObjs = [];
    if (!root || !showLabels) return;
    root.traverse((o) => {
      if (!o.userData.label) return;
      const div = document.createElement("div");
      div.className = "lbl3d";
      div.textContent = o.userData.label;
      const lo = new CSS2DObject(div);
      lo.position.copy(o.userData.labelAt || new THREE.Vector3(0, 0, 0));
      o.add(lo);
      labelObjs.push(lo);
    });
  }

  function rebuildDims() {
    dimGroup?.removeFromParent();
    dimGroup = null;
    if (!root || !showDims || !root.userData.dims) return;
    dimGroup = new THREE.Group();
    for (const d of root.userData.dims) {
      const geo = new THREE.BufferGeometry().setFromPoints([d.a, d.b]);
      const ln = new THREE.Line(geo, DIM);
      ln.computeLineDistances();
      dimGroup.add(ln);
      const div = document.createElement("div");
      div.className = "lbl3d dim";
      div.textContent = d.text;
      const lo = new CSS2DObject(div);
      lo.position.copy(d.a.clone().lerp(d.b, 0.5));
      dimGroup.add(lo);
    }
    root.add(dimGroup);
  }

  function applyExplode() {
    if (!root) return;
    for (const e of root.userData.explode || []) {
      if (!e.base) e.base = e.obj.position.clone();
      e.obj.position.copy(e.base).addScaledVector(e.offset, explodeT);
      if (e.rot) e.obj.rotation.set(e.rot[0] * explodeT, e.rot[1] * explodeT, e.rot[2] * explodeT);
      if (e.fade) e.obj.traverse((o) => { if (o.isMesh) { o.material.transparent = true; o.material.opacity = 1 - explodeT * e.fade; } });
    }
    root.userData.onExplode?.(explodeT);
  }

  // anchors are stored in the pin's parent space (same space as the pin's position)
  function pinWorld(m) {
    m.updateWorldMatrix(true, false);
    return m.userData.anchor ? m.parent.localToWorld(m.userData.anchor.clone()) : m.getWorldPosition(new THREE.Vector3());
  }

  function setHL(m) {
    if (!m) { halo.visible = false; return; }
    const p = new THREE.Vector3();
    m.getWorldPosition(p);
    halo.position.copy(p);
    halo.visible = true;
  }

  function onMove(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, false)[0];
    const m = hit?.object || null;
    if (m !== hovered) {
      hovered = m;
      if (!lockHL) setHL(m);
      renderer.domElement.style.cursor = m ? "pointer" : "grab";
    }
    onHover?.(m ? m.userData.pin : null, { x: ev.clientX - r.left, y: ev.clientY - r.top }, m);
  }
  renderer.domElement.addEventListener("pointermove", onMove);
  renderer.domElement.addEventListener("pointerleave", () => { hovered = null; if (!lockHL) setHL(null); onHover?.(null); });
  renderer.domElement.addEventListener("click", () => { if (hovered) onClick?.(hovered.userData.pin, hovered); });

  const ro = new ResizeObserver(() => {
    renderer.setSize(W(), H());
    labels.setSize(W(), H());
    camera.aspect = W() / H();
    camera.updateProjectionMatrix();
  });
  ro.observe(container);

  let raf = 0, alive = true;
  const clock = new THREE.Clock();
  function loop() {
    if (!alive) return;
    raf = requestAnimationFrame(loop);
    controls.update();
    root?.userData.tick?.(clock.getElapsedTime());
    renderer.render(scene, camera);
    labels.render(scene, camera);
  }
  loop();

  return {
    scene, camera, controls,
    setObject(obj, { keepCamera = false, scale = 0.95 } = {}) {
      fitScale = scale;
      if (root) scene.remove(root);
      root = obj;
      scene.add(obj);
      addEdges(obj);
      pickables = [];
      obj.traverse((o) => { if (o.isMesh && o.userData.pin) pickables.push(o); });
      (obj.userData.explode || []).forEach((e) => (e.base = null));
      applyExplode();
      fit(obj, keepCamera);
      rebuildLabels();
      rebuildDims();
    },
    refreshPickables() { pickables = []; root?.traverse((o) => { if (o.isMesh && o.userData.pin) pickables.push(o); }); addEdges(root); },
    setExplode(t) { explodeT = t; applyExplode(); },
    setLabels(on) { showLabels = on; rebuildLabels(); },
    setDims(on) { showDims = on; rebuildDims(); },
    reset() { if (root) fit(root); },
    highlight(match) {
      // match: (pinInfo) => bool ; locks the halo on the first match
      lockHL = null;
      if (match) for (const m of pickables) if (match(m.userData.pin)) { lockHL = m; break; }
      setHL(lockHL || hovered);
    },
    pinWorld,
    findPin(pred) { return pickables.find((m) => pred(m.userData.pin)) || null; },
    dispose() {
      alive = false; cancelAnimationFrame(raf); ro.disconnect(); controls.dispose(); renderer.dispose();
      renderer.domElement.remove(); labels.domElement.remove();
    },
  };
}
