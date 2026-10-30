// Scroll-driven 3D scene for the landing page. Plain three.js, no postprocessing.
// Everything drawn here is an ILLUSTRATIVE sample plan: no costs or timings are shown.
import { useEffect, useRef } from "react";
import * as THREE from "three";

const C = { bg: 0x0e0f11, line: 0x3a3d42, node: 0x1a1c20, orange: 0xff5a1f, lime: 0xb6e04a, ivory: 0xefeadf };

type N = { id: string; label: string; x: number; y: number; hot?: boolean };
// Plan A (selected) and Plan B (alternative join order, one expensive join). Edges flow left -> right.
const PLAN_A: N[] = [
  { id: "a1", label: "INDEX SCAN", x: -6, y: 1.6 }, { id: "a2", label: "SEQ SCAN", x: -6, y: -0.2 },
  { id: "a3", label: "FILTER", x: -3.4, y: 1.6 }, { id: "a4", label: "HASH JOIN", x: -0.8, y: 0.7 },
  { id: "a5", label: "AGGREGATE", x: 1.8, y: 0.7 }, { id: "a6", label: "PROJECT", x: 4.4, y: 0.7 },
];
const EDGES_A = [["a1", "a3"], ["a3", "a4"], ["a2", "a4"], ["a4", "a5"], ["a5", "a6"]];
const PLAN_B: N[] = [
  { id: "b1", label: "SEQ SCAN", x: -6, y: -3.2 }, { id: "b2", label: "SEQ SCAN", x: -6, y: -5 },
  { id: "b4", label: "NESTED LOOP", x: -2.6, y: -4.1, hot: true }, { id: "b5", label: "AGGREGATE", x: 1.8, y: -4.1 },
  { id: "b6", label: "PROJECT", x: 4.4, y: -4.1 },
];
const EDGES_B = [["b1", "b4"], ["b2", "b4"], ["b4", "b5"], ["b5", "b6"]];

// camera keyframes [progress, position, lookAt]
const KEYS: [number, number[], number[]][] = [
  [0.0, [0, 1.5, 15], [-3.2, 0.5, 0]],
  [0.25, [-1, 3, 17], [-3.4, 0.8, 0]],
  [0.5, [0, 1.5, 16], [-3.2, 0.7, 0]],
  [0.68, [0, -1.6, 19], [-3.4, -1.6, 0]],
  [0.85, [0, -0.6, 17], [-3.2, 0.4, 0]],
  [1.0, [0, 0.4, 26], [-3.2, 0.4, 0]],
];

const sm = (a: number, b: number, x: number) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

function labelSprite(text: string, color = "#efeadf") {
  const cv = document.createElement("canvas"); cv.width = 512; cv.height = 128;
  const g = cv.getContext("2d")!;
  g.fillStyle = color; g.font = "600 44px 'JetBrains Mono', monospace"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text, 256, 64);
  const tex = new THREE.CanvasTexture(cv); tex.anisotropy = 4;
  const m = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const s = new THREE.Sprite(m); s.scale.set(2, 0.5, 1);
  return s;
}

export default function Scene({ progress, lite }: { progress: React.MutableRefObject<number>; lite: boolean }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: !lite, alpha: false, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, lite ? 1 : 1.75));
    renderer.setClearColor(C.bg);
    el.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-hidden", "true");

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(C.bg, 14, 34);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 80);

    const grid = new THREE.GridHelper(60, 60, C.line, 0x202226);
    grid.position.y = -7; scene.add(grid);

    const lineMat = (c: number, o = 1) => { const m = new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: o }); m.userData.o = o; return m; };
    const groups: { g: THREE.Group; fade: (p: number) => number }[] = [];
    const paths: { pts: THREE.Vector3[]; plan: "A" | "B" }[] = [];

    function buildPlan(nodes: N[], edges: string[][], plan: "A" | "B", fade: (p: number) => number) {
      const g = new THREE.Group();
      const pos = new Map(nodes.map((n) => [n.id, new THREE.Vector3(n.x, n.y, 0)]));
      for (const n of nodes) {
        const w = n.hot ? 2.6 : 1.9; // expensive operator is physically larger, not only recoloured
        const box = new THREE.BoxGeometry(w, 0.9, 0.9);
        const mesh = new THREE.Mesh(box, new THREE.MeshBasicMaterial({ color: C.node, transparent: true }));
        const edge = new THREE.LineSegments(new THREE.EdgesGeometry(box), lineMat(n.hot ? C.orange : plan === "A" ? C.lime : C.ivory));
        const lab = labelSprite(n.label, n.hot ? "#ff8a5c" : "#efeadf");
        lab.position.set(0, 0, 0.6);
        const node = new THREE.Group(); node.add(mesh, edge, lab); node.position.copy(pos.get(n.id)!);
        g.add(node);
      }
      for (const [a, b] of edges) {
        const pa = pos.get(a)!, pb = pos.get(b)!;
        const mid = new THREE.Vector3((pa.x + pb.x) / 2, pa.y, 0), pts = [pa, mid, new THREE.Vector3(mid.x, pb.y, 0), pb].map((v) => v.clone());
        g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lineMat(plan === "A" ? C.lime : C.line, 0.7)));
        paths.push({ pts, plan });
      }
      scene.add(g); groups.push({ g, fade });
    }
    buildPlan(PLAN_A, EDGES_A, "A", (p) => sm(0.08, 0.28, p));
    buildPlan(PLAN_B, EDGES_B, "B", (p) => sm(0.52, 0.66, p));

    // Chapter 1: the "query" as a slab of stacked lines that decomposes in chapter 2.
    const q = new THREE.Group();
    const widths = [3.2, 2.4, 3.6, 2.8, 3.0, 1.8];
    widths.forEach((w, i) => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(w, 0.16), new THREE.MeshBasicMaterial({ color: i === 2 ? C.orange : C.ivory, transparent: true }));
      m.position.set(-w / 2 + 1.6, 1.2 - i * 0.42, 0); q.add(m);
    });
    scene.add(q);

    // Data packets flowing along edges (one InstancedMesh).
    const COUNT = lite ? 24 : 72;
    const packets = new THREE.InstancedMesh(new THREE.BoxGeometry(0.14, 0.14, 0.14), new THREE.MeshBasicMaterial({ color: C.ivory }), COUNT);
    scene.add(packets);
    const seeds = Array.from({ length: COUNT }, (_, i) => ({ path: i % paths.length, off: (i * 0.618) % 1 }));
    const dummy = new THREE.Object3D();
    const curves = paths.map((p) => new THREE.CatmullRomCurve3(p.pts, false, "centripetal", 0.1));

    function resize() {
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setSize(w, h, false); renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
      camera.aspect = w / h; camera.updateProjectionMatrix();
    }
    resize();
    const ro = new ResizeObserver(resize); ro.observe(el);

    const pos = new THREE.Vector3(), look = new THREE.Vector3(), cur = new THREE.Vector3(), curLook = new THREE.Vector3();
    let raf = 0, smooth = 0, visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; }, { threshold: 0 });
    io.observe(el);
    const clock = new THREE.Clock();

    function frame() {
      raf = requestAnimationFrame(frame);
      if (!visible) return;
      const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
      smooth += (progress.current - smooth) * (1 - Math.exp(-dt * 6)); // eased scroll follow
      const p = smooth;

      let i = 0; while (i < KEYS.length - 2 && p > KEYS[i + 1][0]) i++;
      const [p0, c0, l0] = KEYS[i], [p1, c1, l1] = KEYS[i + 1], k = sm(p0, p1, p);
      pos.set(c0[0], c0[1], c0[2]).lerp(cur.set(c1[0], c1[1], c1[2]), k);
      look.set(l0[0], l0[1], l0[2]).lerp(curLook.set(l1[0], l1[1], l1[2]), k);
      // narrow screens: stand further back and centre the scene (text overlays it instead of sitting beside it)
      const narrow = camera.aspect < 1.2, back = narrow ? Math.min(2.4, 1.6 / camera.aspect) : 1;
      (scene.fog as THREE.Fog).near = 14 * back; (scene.fog as THREE.Fog).far = 34 * back;  // keep fog proportional to camera distance
      if (narrow) look.x *= 0.3;
      pos.z *= back; if (narrow) pos.x *= 0.3;
      camera.position.copy(pos); camera.lookAt(look);

      // chapter 1 query slab decomposes (spreads and fades) as operators appear
      const dec = sm(0.08, 0.28, p);
      q.children.forEach((m, j) => {
        const mesh = m as THREE.Mesh; (mesh.material as THREE.Material).opacity = 1 - dec;
        mesh.position.x += ((-6 + j * 0.2) * dec + (1 - dec) * (-widths[j] / 2 + 1.6) - mesh.position.x) * 0.2;
        mesh.position.y = (1.2 - j * 0.42) * (1 - dec * 0.4);
      });
      const end = 1 - sm(0.9, 1, p); // the scene clears behind the final call to action
      for (const { g, fade } of groups) {
        const f = fade(p) * end; g.visible = f > 0.01;
        g.scale.setScalar(0.92 + 0.08 * f);
        g.traverse((o) => { const m = (o as THREE.Mesh).material as THREE.Material | undefined; if (m && "opacity" in m) (m as any).opacity = f * (m.userData.o ?? 1); });
      }
      grid.position.z = -((t * 0.3) % 1);

      const flow = sm(0.12, 0.3, p) * end;
      packets.visible = flow > 0.02;
      seeds.forEach((s, n) => {
        const planB = paths[s.path].plan === "B", on = planB ? sm(0.55, 0.68, p) * end : flow;
        const u = (s.off + t * (planB ? 0.09 : 0.16)) % 1;
        curves[s.path].getPoint(u, dummy.position);
        dummy.scale.setScalar(on > 0.5 ? 1 : 0.001); dummy.updateMatrix(); packets.setMatrixAt(n, dummy.matrix);
      });
      packets.instanceMatrix.needsUpdate = true;
      renderer.render(scene, camera);
    }
    frame();

    const onLost = (e: Event) => { e.preventDefault(); cancelAnimationFrame(raf); };
    const onRestored = () => { frame(); };
    renderer.domElement.addEventListener("webglcontextlost", onLost);
    renderer.domElement.addEventListener("webglcontextrestored", onRestored);

    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); io.disconnect();
      renderer.domElement.removeEventListener("webglcontextlost", onLost);
      renderer.domElement.removeEventListener("webglcontextrestored", onRestored);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mat = m.material as THREE.Material | THREE.SpriteMaterial | undefined;
        if (mat) { (mat as THREE.SpriteMaterial).map?.dispose(); mat.dispose(); }
      });
      renderer.dispose(); renderer.domElement.remove();
    };
  }, [progress, lite]);

  return <div ref={host} className="h-full w-full" />;
}
