import { ReactNode, useState } from "react";

export function Panel({
  title, right, children, className = "", bodyClass = "p-4",
}: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`panel overflow-hidden ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {right}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Stat({
  label, value, sub, tone = "default", title,
}: {
  label: string; value: ReactNode; sub?: ReactNode;
  tone?: "default" | "accent" | "ok" | "warn"; title?: string;
}) {
  const toneCls =
    tone === "accent" ? "text-accent" : tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="rounded-lg border border-line bg-panel-2 px-3.5 py-3" title={title}>
      <div className="label">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="mt-0.5 text-2xs text-faint">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: Tone }) {
  return <span className={`chip ${TONES[tone]}`}>{children}</span>;
}
type Tone = "neutral" | "accent" | "ok" | "warn" | "err";
const TONES: Record<Tone, string> = {
  neutral: "bg-panel-3 text-muted",
  accent: "bg-[color:var(--accent-soft)] text-accent",
  ok: "bg-[color:var(--ok-soft)] text-ok",
  warn: "bg-[color:var(--warn-soft)] text-warn",
  err: "bg-[color:var(--err-soft)] text-err",
};

export function Segmented<T extends string>({
  tabs, value, onChange,
}: {
  tabs: { id: T; label: string; icon?: ReactNode; badge?: ReactNode }[];
  value: T; onChange: (t: T) => void;
}) {
  return (
    <div className="seg overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.id} className="seg-item whitespace-nowrap" data-active={value === t.id}
          onClick={() => onChange(t.id)}>
          {t.icon}
          {t.label}
          {t.badge != null && (
            <span className="ml-1 rounded bg-panel3 px-1 text-2xs tabular-nums text-faint">{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line2 border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--err)] bg-[color:var(--err-soft)] px-3.5 py-3 text-sm">
      <div className="font-semibold text-err">Something went wrong</div>
      <div className="mt-1 font-mono text-xs text-err">{message}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line px-6 py-14 text-center">
      {icon && <div className="text-2xl opacity-60">{icon}</div>}
      {title && <div className="text-sm font-semibold text-ink">{title}</div>}
      <div className="max-w-sm text-sm text-muted">{children}</div>
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1400);
    } catch { /* ignore */ }
  }
  return (
    <button className="btn btn-ghost !px-2 !py-1 text-2xs" onClick={copy}
      title="Copy to clipboard" aria-label="Copy to clipboard">
      {done ? "✓ Copied" : `⧉ ${label}`}
    </button>
  );
}
