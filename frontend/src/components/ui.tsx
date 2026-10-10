import { ReactNode } from "react";
import { Link } from "react-router-dom";

export function NeedRun() {
  return (
    <Empty>
      No optimization result yet. Head to the{" "}
      <Link to="/optimizer" className="font-semibold text-brand-600 hover:underline">SQL Optimizer</Link>{" "}
      and run a query first.
    </Empty>
  );
}

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={`card ${className}`}>
      {title && (
        <div className="card-header flex items-center justify-between">
          <span>{title}</span>
          {right}
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub, title }: { label: string; value: ReactNode; sub?: ReactNode; title?: string }) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-8 text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
      <div className="font-semibold">Something went wrong</div>
      <div className="mt-1 font-mono">{message}</div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
      {children}
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    slate: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    green: "bg-green-100 text-green-700 dark:bg-green-900/50 dark:text-green-300",
    blue: "bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300",
    amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300",
    red: "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300",
  };
  return <span className={`badge ${tones[tone] || tones.slate}`}>{children}</span>;
}
