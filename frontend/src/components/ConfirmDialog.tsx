import { ReactNode, useEffect, useRef } from "react";

/** Accessible confirmation modal for dangerous actions (e.g. schema-changing SQL). */
export function ConfirmDialog({
  open, title, children, confirmLabel = "Confirm", danger = false, onConfirm, onCancel,
}: {
  open: boolean; title: string; children: ReactNode; confirmLabel?: string; danger?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cancelBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    cancelBtn.current?.focus(); // safe default focus: Cancel
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onCancel(); return; }
      if (e.key !== "Tab" || !box.current) return;
      const f = box.current.querySelectorAll<HTMLElement>("button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div ref={box} role="alertdialog" aria-modal="true" aria-labelledby="cd-title" aria-describedby="cd-body"
        className="w-full max-w-md animate-slide-up border border-line-2 bg-panel p-6 shadow-pop">
        <h2 id="cd-title" className="font-display text-2xl font-light tracking-tight">{title}</h2>
        <div id="cd-body" className="mt-2 text-sm text-muted">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button ref={cancelBtn} className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button className={danger ? "btn border border-err bg-[color:var(--err-soft)] text-err hover:brightness-125" : "btn btn-primary"} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
