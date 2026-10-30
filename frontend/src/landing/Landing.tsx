import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const Scene = lazy(() => import("./Scene"));

const CHAPTERS = [
  { k: "01", title: "Every query has a cost.", body: "The same logical request can run as many different physical strategies. The database has to choose one before it reads a single row.", code: "SELECT c.name, SUM(o.total)\nFROM orders o JOIN customers c ON …\nWHERE o.status = 'shipped'\nGROUP BY c.name;" },
  { k: "02", title: "Inside the execution engine.", body: "A query is decomposed into operators: scans, filters, joins, aggregates, projections. Rows flow from the leaves to the root, and every operator adds work." },
  { k: "03", title: "The plan fork.", body: "A join order or access path changes the plan, and often the cost. A cost model picks the plan it estimates to be cheapest. That is a prediction, not a measurement, and the scene shows an illustrative sample plan, not your database." },
  { k: "04", title: "The experiment.", body: "QueryPilot reads your real schema and statistics, costs candidate plans, checks that a rewritten query returns the same rows, then times both. Estimated and measured results are always labelled separately." },
  { k: "05", title: "The evidence.", body: "A speedup is reported only when the measured ranges do not overlap. Otherwise you are told the difference is not measurable, or that your original query was better.", cta: true },
];

function webglOk() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch { return false; }
}

export default function Landing() {
  const scroller = useRef<HTMLDivElement>(null);
  const progress = useRef(0);
  const [mode, setMode] = useState<"scene" | "static">("static");
  const [lite, setLite] = useState(false);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setMode(!reduce && webglOk() ? "scene" : "static");
    setLite(window.innerWidth < 760);
  }, []);

  useEffect(() => {
    const el = scroller.current!;
    const on = () => { progress.current = el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight); };
    on();
    el.addEventListener("scroll", on, { passive: true });
    return () => el.removeEventListener("scroll", on);
  }, []);

  return (
    <div ref={scroller} className="relative h-full overflow-y-auto bg-[#0e0f11] text-[#efeadf]" style={{ scrollBehavior: "auto" }}>
      <div className="fixed inset-0" aria-hidden="true">
        {mode === "scene" ? (
          <Suspense fallback={<div className="grid h-full place-items-center font-mono text-xs text-[#8a867c]">Loading 3D scene…</div>}>
            <Scene progress={progress} lite={lite} />
          </Suspense>
        ) : <StaticBackdrop />}
        <div className="pointer-events-none absolute inset-0 bg-[#0e0f11]/65 sm:hidden" />
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_left,rgba(14,15,17,0.85),transparent_65%)]" />
      </div>

      <header className="fixed inset-x-0 top-0 z-20 flex items-center justify-between bg-gradient-to-b from-[#0e0f11] via-[#0e0f11]/80 to-transparent px-5 pb-6 pt-4 sm:px-10">
        <span className="font-['Fraunces',serif] text-xl tracking-tight">Query<span className="text-[#ff5a1f]">Pilot</span></span>
        <Link to="/app" className="rounded-sm border border-[#efeadf]/30 px-3 py-1.5 font-mono text-xs hover:border-[#ff5a1f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#b6e04a]">Open workbench →</Link>
      </header>

      <main className="relative z-10">
        {CHAPTERS.map((c) => (
          <section key={c.k} className="flex min-h-screen items-center px-5 sm:px-10" aria-labelledby={`ch-${c.k}`}>
            <div className="max-w-xl">
              <p className="mb-4 font-mono text-xs tracking-widest text-[#ff5a1f]">CHAPTER {c.k}</p>
              <h2 id={`ch-${c.k}`} className="font-['Fraunces',serif] text-5xl font-light leading-[1.02] tracking-tight sm:text-7xl">{c.title}</h2>
              <p className="mt-6 text-base leading-relaxed text-[#bdb8ab] sm:text-lg">{c.body}</p>
              {c.code && <pre className="mt-6 overflow-x-auto border-l-2 border-[#ff5a1f] bg-black/30 p-4 font-mono text-xs text-[#efeadf]">{c.code}</pre>}
              {c.k === "03" && <p className="mt-4 font-mono text-[11px] uppercase tracking-wider text-[#8a867c]">Sample plan · illustrative · not from your database</p>}
              {c.cta && (
                <div className="mt-8 flex flex-wrap gap-3">
                  <Link to="/app" className="bg-[#ff5a1f] px-5 py-3 font-medium text-[#0e0f11] hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#b6e04a]">Open Query Workbench</Link>
                  <a href="https://github.com/Physics0070/dbms-cp/blob/main/OPTIMIZER.md" className="border border-[#efeadf]/40 px-5 py-3 hover:border-[#b6e04a] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#b6e04a]">Explore the optimizer</a>
                </div>
              )}
            </div>
          </section>
        ))}
      </main>
    </div>
  );
}

/** Lightweight fallback: no WebGL, reduced motion, or the scene failed to load. */
function StaticBackdrop() {
  return (
    <div className="h-full w-full opacity-60" style={{ backgroundImage: "linear-gradient(#202226 1px,transparent 1px),linear-gradient(90deg,#202226 1px,transparent 1px)", backgroundSize: "48px 48px" }} />
  );
}
