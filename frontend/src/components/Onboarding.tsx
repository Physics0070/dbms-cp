import { ReactNode, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";

/** First-run guide shown before any result. Every value comes from the connected database. */
export function Onboarding() {
  const { examples, setSql, runOptimize, loading } = useStore();
  const [db, setDb] = useState<any | null>(null);
  useEffect(() => { api.database().then(setDb).catch(() => setDb({ connected: false, reason: "Backend unreachable." })); }, []);

  const connected = !!db?.connected;
  return (
    <div className="border border-line bg-panel p-6 sm:p-8">
      <p className="mb-2 font-mono text-2xs font-semibold uppercase tracking-[0.2em] text-accent">Start here</p>
      <h2 className="font-display text-3xl font-light tracking-tight">Get to your first optimization</h2>
      <ol className="mt-6 space-y-5 text-sm">
        <Step n={1} done={connected} title="Choose a database">
          {connected
            ? <>Connected to <span className="font-mono">{db.name}</span> ({db.tables} tables, {db.read_only ? "read-only" : "read-write"}). Use the database button in the top bar to switch or upload another SQLite file.</>
            : <>{db ? db.reason || "No database is connected." : "Checking…"} Use the database button in the top bar to upload a SQLite file.</>}
        </Step>
        <Step n={2} done={false} title="Pick an example generated from your schema">
          {examples.length ? (
            <div className="mt-1 flex flex-wrap gap-2">
              {examples.map((ex) => (
                <button key={ex.label} className="btn btn-ghost font-mono text-2xs uppercase tracking-wider" onClick={() => setSql(ex.sql)}>{ex.label}</button>
              ))}
            </div>
          ) : "Examples appear once a database with tables is connected."}
        </Step>
        <Step n={3} done={false} title="Optimize">
          <button className="btn btn-primary mt-1" disabled={!connected || loading} onClick={runOptimize}>Optimize the query above →</button>
          <p className="mt-2 text-2xs text-faint">Estimated cost and measured runtime are always labelled separately. Ctrl+Enter also runs it.</p>
        </Step>
      </ol>
    </div>
  );
}

function Step({ n, done, title, children }: { n: number; done: boolean; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className={`mt-0.5 w-6 shrink-0 font-mono text-xs font-semibold ${done ? "text-ok" : "text-accent"}`}>{done ? "✓" : String(n).padStart(2, "0")}</span>
      <div className="min-w-0"><div className="font-medium text-ink">{title}</div><div className="text-muted">{children}</div></div>
    </li>
  );
}
