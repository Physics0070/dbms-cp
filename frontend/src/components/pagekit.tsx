// Page-level building blocks for the "instrument panel" look: chapter numbers in mono orange,
// Fraunces page titles, hairline rules. Same names/props as the shell kit (PageHeader, Section).
import { ReactNode } from "react";

export function PageHeader({
  index, title, subtitle, actions,
}: { index: string; title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-line pb-5">
      <div className="min-w-0">
        <p className="font-mono text-2xs uppercase tracking-[0.2em] text-accent">{index} / {title}</p>
        <h1 className="mt-2 font-display text-4xl font-light leading-none tracking-tight text-ink sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-3 max-w-3xl text-sm leading-relaxed text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Section({
  index, title, right, children, className = "",
}: { index?: string; title: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className}>
      <div className="mb-3 flex items-baseline justify-between gap-3 border-b border-line pb-2">
        <h2 className="flex items-baseline gap-3 font-mono text-xs uppercase tracking-[0.14em] text-ink">
          {index && <span className="text-accent">{index}</span>}
          {title}
        </h2>
        {right}
      </div>
      {children}
    </section>
  );
}

type Tone = "neutral" | "accent" | "ok" | "warn" | "err";
const TAG: Record<Tone, string> = {
  neutral: "border-line-2 text-muted",
  accent: "border-accent text-accent",
  ok: "border-ok text-ok",
  warn: "border-warn text-warn",
  err: "border-err text-err",
};

/** Small mono tag with a hairline border; the text carries the meaning, colour only reinforces it. */
export function Tag({ children, tone = "neutral", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center whitespace-nowrap border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest ${TAG[tone]}`}>
      {children}
    </span>
  );
}

/** Mono label/value pair used in dense metadata strips. */
export function Meta({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[10px] uppercase tracking-widest text-faint">{k}</dt>
      <dd className="mt-0.5 truncate font-mono text-sm tabular-nums text-ink">{v}</dd>
    </div>
  );
}

export const TAB_BTN =
  "border-b-2 px-3 py-2 font-mono text-xs uppercase tracking-widest transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]";
export const tabCls = (active: boolean) =>
  `${TAB_BTN} ${active ? "border-accent text-ink" : "border-transparent text-faint hover:text-ink"}`;
