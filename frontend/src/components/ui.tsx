import { ReactNode, useState } from "react";

/* ---- Instrument-panel primitives (shared by every page) ------------------------------------- */

/** Page title block: mono orange chapter index, Fraunces title, optional subtitle and actions. */
export function PageHeader({
  index, title, subtitle, actions,
}: { index: string; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line pb-6">
      <div className="min-w-0">
        <p className="mb-2 font-mono text-2xs font-semibold uppercase tracking-[0.2em] text-accent">{index}</p>
        <h1 className="font-display text-4xl font-light leading-[1.05] tracking-tight text-ink sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

/** Numbered section: hairline rule, mono index + uppercase label, optional right slot. */
export function Section({
  index, title, right, children, className = "",
}: { index?: string; title: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`mb-8 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-3 border-t border-line-2 pt-3">
        <h2 className="flex items-baseline gap-3 font-mono text-2xs font-semibold uppercase tracking-[0.18em] text-muted">
          {index && <span className="text-accent">{index}</span>}
          <span>{title}</span>
        </h2>
        {right}
      </div>
      {children}
    </section>
  );
}

/** Bordered surface with an optional mono header strip. */
export function Panel({
  title, right, children, className = "", bodyClass = "p-4",
}: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`panel overflow-hidden ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h3 className="font-mono text-2xs font-semibold uppercase tracking-[0.16em] text-muted">{title}</h3>
          {right}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

/**
 * A single figure. `kind` stamps where the number comes from so estimates and measurements
 * are never confused: "estimate" (cost model) or "measured" (wall-clock).
 */
export function Stat({
  label, value, unit, sub, tone = "default", kind, title,
}: {
  label: string; value: ReactNode; unit?: ReactNode; sub?: ReactNode;
  tone?: "default" | "accent" | "ok" | "warn"; kind?: "estimate" | "measured"; title?: string;
}) {
  const toneCls =
    tone === "accent" ? "text-accent" : tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-ink";
  return (
    <div className="border border-line bg-panel-2 px-3.5 py-3" title={title}>
      <div className="flex items-center justify-between gap-2">
        <span className="label">{label}</span>
        {kind && (
          <span className={`font-mono text-[10px] font-semibold uppercase tracking-widest ${kind === "measured" ? "text-ok" : "text-accent"}`}>
            {kind === "measured" ? "measured" : "estimate"}
          </span>
        )}
      </div>
      <div className={`mt-1.5 font-mono text-2xl font-medium tabular-nums leading-none ${toneCls}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-faint">{unit}</span>}
      </div>
      {sub && <div className="mt-1.5 font-mono text-2xs text-faint">{sub}</div>}
    </div>
  );
}

/** The headline outcome of an analysis: big serif statement + evidence line. tone ok = verified. */
export function Verdict({
  tone = "neutral", label, headline, children,
}: { tone?: "ok" | "warn" | "neutral"; label?: string; headline: ReactNode; children?: ReactNode }) {
  const bar = tone === "ok" ? "border-ok" : tone === "warn" ? "border-accent" : "border-line-2";
  const lab = tone === "ok" ? "text-ok" : tone === "warn" ? "text-accent" : "text-muted";
  return (
    <div className={`border-l-2 ${bar} bg-panel py-1 pl-5`}>
      {label && <p className={`mb-1 font-mono text-2xs font-semibold uppercase tracking-[0.18em] ${lab}`}>{label}</p>}
      <p className="font-display text-3xl font-light leading-tight tracking-tight text-ink sm:text-4xl">{headline}</p>
      {children && <div className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">{children}</div>}
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

/** Tab strip: mono uppercase labels, orange underline on the active tab. */
export function Segmented<T extends string>({
  tabs, value, onChange,
}: {
  tabs: { id: T; label: string; icon?: ReactNode; badge?: ReactNode }[];
  value: T; onChange: (t: T) => void;
}) {
  return (
    <div className="seg overflow-x-auto" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className="seg-item whitespace-nowrap"
          data-active={value === t.id} onClick={() => onChange(t.id)}>
          {t.icon}
          {t.label}
          {t.badge != null && (
            <span className="ml-0.5 font-mono text-2xs tabular-nums text-faint">{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 font-mono text-xs uppercase tracking-widest text-muted" role="status">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
      {label}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="border border-[color:var(--err)] border-l-2 bg-[color:var(--err-soft)] px-3.5 py-3 text-sm" role="alert">
      <div className="font-mono text-2xs font-semibold uppercase tracking-widest text-err">Something went wrong</div>
      <div className="mt-1 font-mono text-xs text-err">{message}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 border border-dashed border-line-2 px-6 py-14 text-center">
      {icon && <div className="text-2xl opacity-60">{icon}</div>}
      {title && <div className="font-display text-2xl font-light tracking-tight text-ink">{title}</div>}
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
    <button className="btn btn-ghost !px-2 !py-1 font-mono text-2xs uppercase tracking-wider" onClick={copy}
      title="Copy to clipboard" aria-label="Copy to clipboard">
      {done ? "✓ Copied" : `⧉ ${label}`}
    </button>
  );
}
