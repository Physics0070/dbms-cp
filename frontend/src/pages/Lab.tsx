import { useState } from "react";
import { CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmt, LabResult, Timing } from "../api";
import { ErrorNote } from "../components/ui";
import { Meta, PageHeader, Section, Tag } from "../components/pagekit";
import { useStore } from "../store";

const VERDICT: Record<string, { text: string; tone: "ok" | "err" | "neutral" | "warn"; tag: string }> = {
  faster: { text: "Candidate measured faster: the timing ranges do not overlap.", tone: "ok", tag: "Faster" },
  slower: { text: "Candidate measured slower: the timing ranges do not overlap.", tone: "err", tag: "Slower" },
  indistinguishable: { text: "No measurable difference: the timing ranges overlap.", tone: "neutral", tag: "Inconclusive" },
  not_comparable: { text: "No verdict: the two queries were not verified to return the same rows.", tone: "warn", tag: "Not comparable" },
};

export default function Lab() {
  const { sql, result } = useStore();
  const [baseline, setBaseline] = useState(sql);
  const [candidate, setCandidate] = useState(result?.optimized_query?.sql ?? sql);
  const [warmup, setWarmup] = useState(2);
  const [runs, setRuns] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<LabResult | null>(null);
  const [title, setTitle] = useState("");
  const [why, setWhy] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  async function run() {
    setBusy(true); setError(null); setSaved(null);
    try { setRes(await api.labCompare({ baseline_sql: baseline, candidate_sql: candidate, warmup, runs })); }
    catch (e: any) { setError(e.message || String(e)); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!res) return;
    try { const r = await api.saveInvestigation({ title, rationale: why, comparison: res }); setSaved(r.id); }
    catch (e: any) { setError(e.message || String(e)); }
  }

  const v = res && VERDICT[res.measured.verdict];
  const editors = [
    { label: "Baseline SQL", val: baseline, set: setBaseline, mark: "A", bar: "bg-ink" },
    { label: "Candidate SQL", val: candidate, set: setCandidate, mark: "B", bar: "bg-accent" },
  ] as const;

  return (
    <div className="space-y-8">
      <PageHeader index="06" title="Lab"
        subtitle="Compare a baseline query with a candidate. Both run read-only. Estimated cost and measured runtime are reported separately, and a result is only compared when both queries return the same rows." />

      <Section index="01" title="Experiment">
        <div className="grid gap-4 md:grid-cols-2">
          {editors.map((e) => (
            <div key={e.label} className="border border-line bg-panel">
              <div className="flex items-center gap-2 border-b border-line px-3 py-2">
                <span className={`h-2 w-2 ${e.bar}`} aria-hidden="true" />
                <label className="font-mono text-[10px] uppercase tracking-widest text-muted" htmlFor={e.label}>{e.label}</label>
                <span className="ml-auto font-mono text-[10px] text-faint">{e.mark}</span>
              </div>
              <textarea id={e.label} className="block h-44 w-full resize-y bg-transparent p-3 font-mono text-xs leading-relaxed text-ink outline-none focus:bg-panel-2"
                spellCheck={false} value={e.val} onChange={(ev) => e.set(ev.target.value)} />
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-end gap-4 border border-line bg-panel px-4 py-3">
          <label className="font-mono text-[10px] uppercase tracking-widest text-faint">Warm-up runs (0-10)
            <input type="number" min={0} max={10} className="input mt-1 block w-24 font-mono" value={warmup} onChange={(e) => setWarmup(+e.target.value)} />
          </label>
          <label className="font-mono text-[10px] uppercase tracking-widest text-faint">Measured runs (3-30)
            <input type="number" min={3} max={30} className="input mt-1 block w-24 font-mono" value={runs} onChange={(e) => setRuns(+e.target.value)} />
          </label>
          <button className="btn btn-primary ml-auto" onClick={run} disabled={busy || !baseline.trim() || !candidate.trim()}>
            {busy ? "Running…" : "Run comparison"}
          </button>
        </div>
      </Section>
      {error && <ErrorNote message={error} />}

      {res && v && (
        <>
          <Section index="02" title="Verdict">
            <div className="border border-line bg-panel p-5">
              <Tag tone={v.tone}>{v.tag}</Tag>
              <p className="mt-3 font-display text-2xl font-light leading-snug tracking-tight">
                {v.text}
                {res.measured.median_change_pct !== null &&
                  ` Median ${res.measured.median_change_pct >= 0 ? "faster" : "slower"} by ${fmt(Math.abs(res.measured.median_change_pct))}%.`}
              </p>
            </div>
          </Section>

          <div className="grid gap-8 md:grid-cols-2">
            <Section index="03" title="Estimated · cost model">
              <dl className="grid grid-cols-2 gap-4 border border-line p-4">
                <Meta k="Baseline" v={res.estimated.baseline.available ? fmt(res.estimated.baseline.cost) : "unavailable"} />
                <Meta k="Candidate" v={res.estimated.candidate.available ? fmt(res.estimated.candidate.cost) : "unavailable"} />
              </dl>
              <p className="mt-2 font-mono text-[10px] leading-snug text-faint">A prediction from this tool's model, in abstract units. It is not a time and can disagree with the measurement.</p>
            </Section>
            <Section index="04" title="Measured · wall-clock ms">
              <div className="grid grid-cols-2 gap-4 border border-line p-4">
                <Timings name="Baseline" t={res.measured.baseline} />
                <Timings name="Candidate" t={res.measured.candidate} />
              </div>
              <p className="mt-2 font-mono text-[10px] leading-snug text-faint">{res.config.warmup_runs} warm-up + {res.config.measured_runs} measured runs each.</p>
            </Section>
          </div>

          <Section index="05" title="Run-time distribution (ms)">
            <div className="border border-line bg-panel p-3"><Distribution res={res} /></div>
          </Section>

          <div className="grid gap-8 md:grid-cols-2">
            <Section index="06" title="Result equivalence">
              <p className="text-sm">
                <Tag tone={res.equivalence.equal ? "ok" : "warn"}>{res.equivalence.equal ? "Same columns and rows" : "Not verified equal"}</Tag>{" "}
                <span className="text-muted">{res.equivalence.note}</span>
              </p>
            </Section>
            <Section index="07" title="Uncertainty and limitations">
              <ul className="list-disc space-y-1 border border-line bg-panel py-3 pl-8 pr-4 text-sm text-muted">{res.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
            </Section>
          </div>

          <Section index="08" title="Save as investigation">
            <div className="grid gap-3 md:grid-cols-2">
              <input className="input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" />
              <input className="input" placeholder="Why was this change proposed?" value={why} onChange={(e) => setWhy(e.target.value)} aria-label="Rationale" />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button className="btn btn-ghost" onClick={save} disabled={!title.trim() || !!saved}>Save</button>
              {saved && <span className="text-xs text-ok">Saved. Find it in History → Investigations.</span>}
              <span className="font-mono text-[10px] text-faint">Stores SQL, plan summary and timings only. No result rows.</span>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}

function Timings({ name, t }: { name: string; t: Timing }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-widest text-faint">{name}</div>
      <div className="mt-1 font-mono text-xl tabular-nums text-ink">{fmt(t.median_ms, 3)}<span className="ml-1 text-xs text-faint">median</span></div>
      <div className="mt-1 font-mono text-[11px] tabular-nums text-muted">range {fmt(t.min_ms, 3)}–{fmt(t.max_ms, 3)} · IQR {fmt(t.iqr_ms, 3)}</div>
    </div>
  );
}

// Strip plot: every measured run is a dot (no averaging hides the spread); the tick is the median.
// Baseline is ivory; candidate is orange, and lime only when the verdict says it measured faster.
function Distribution({ res }: { res: LabResult }) {
  const cand = res.measured.verdict === "faster" ? "var(--ok)" : "var(--accent)";
  const rows = [{ name: "Baseline", y: 1, t: res.measured.baseline, color: "var(--ink)" },
                { name: "Candidate", y: 2, t: res.measured.candidate, color: cand }];
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ScatterChart margin={{ top: 8, right: 16, left: 8, bottom: 28 }}>
        <CartesianGrid stroke="var(--line)" />
        <XAxis type="number" dataKey="x" name="Run time" unit=" ms" domain={["auto", "auto"]} tickLine={false} axisLine={{ stroke: "var(--line-2)" }}
          tick={{ fontSize: 11, fill: "var(--muted)", fontFamily: "JetBrains Mono, monospace" }}
          label={{ value: "Run time (ms)", position: "insideBottom", offset: -14, fill: "var(--muted)", fontSize: 11 }} />
        <YAxis type="number" dataKey="y" domain={[0.5, 2.5]} ticks={[1, 2]} width={72} tickLine={false} axisLine={false}
          tickFormatter={(n) => (n === 1 ? "Baseline" : "Candidate")} tick={{ fontSize: 11, fill: "var(--muted)", fontFamily: "JetBrains Mono, monospace" }} />
        <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={(val: any, n: any) => (n === "Run time" ? `${fmt(val, 3)} ms` : val)}
          contentStyle={{ background: "var(--panel)", border: "1px solid var(--line-2)", borderRadius: 2, fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 11, color: "var(--muted)" }} />
        {rows.map((r) => (
          <Scatter key={r.name} name={`${r.name} runs`} fill={r.color} data={r.t.samples_ms.map((x) => ({ x, y: r.y }))} />
        ))}
        {rows.map((r) => (
          <ReferenceLine key={r.name} segment={[{ x: r.t.median_ms, y: r.y - 0.3 }, { x: r.t.median_ms, y: r.y + 0.3 }]}
            stroke={r.color} strokeWidth={2} ifOverflow="extendDomain" />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}
