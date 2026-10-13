import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";

export function TopBar() {
  const { theme, toggleTheme } = useStore();
  const [health, setHealth] = useState<any | null>(null);
  const [down, setDown] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setDown(true));
  }, []);

  const connected = !!health && !down && health.status === "ok";
  const label = down
    ? "Backend unreachable"
    : !health
      ? "Connecting…"
      : connected
        ? health.database_backend
        : "No database connected";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b border-line bg-panel px-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm font-bold text-accentfg">◧</span>
        <div className="leading-tight">
          <div className="text-sm font-semibold">QueryPilot AI</div>
          <div className="hidden text-2xs text-faint sm:block">Write smarter queries. Understand every execution.</div>
        </div>
      </div>

      <div className="relative ml-auto flex items-center gap-2">
        <button
          className="flex max-w-[320px] items-center gap-2 rounded-lg border border-line bg-panel-2 px-2.5 py-1.5 text-xs transition-colors hover:border-line-2"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-haspopup="dialog"
          title="Change database"
        >
          <span className={`h-2 w-2 shrink-0 rounded-full ${connected ? "bg-ok" : "bg-err"}`}
            style={connected ? { boxShadow: "0 0 0 3px var(--ok-soft)" } : undefined} />
          <span className="truncate text-muted">{label}</span>
          {connected && (
            <span className="hidden whitespace-nowrap rounded bg-panel-3 px-1.5 py-0.5 text-2xs tabular-nums text-faint sm:inline">
              {health.tables?.length ?? 0} tables
            </span>
          )}
          <span className="text-faint">▾</span>
        </button>

        {open && <DatabasePopover onClose={() => setOpen(false)} />}

        <button className="btn btn-ghost !px-2.5" onClick={toggleTheme}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} aria-label="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}

function DatabasePopover({ onClose }: { onClose: () => void }) {
  const [info, setInfo] = useState<any | null>(null);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { api.database().then(setInfo).catch(() => {}); }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => { document.removeEventListener("keydown", onKey); document.removeEventListener("mousedown", onDown); };
  }, [onClose]);

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await api.connectDatabase(path);
      // A different database means a different schema: drop the saved query and reload clean.
      try { localStorage.removeItem("sql"); } catch { /* ignore */ }
      window.location.reload();
    } catch (e: any) {
      setError(e.message || String(e));
      setBusy(false);
    }
  }

  return (
    <div ref={ref} role="dialog" aria-label="Database connection"
      className="absolute right-12 top-11 z-40 w-[360px] max-w-[92vw] animate-slide-up rounded-xl border border-line bg-panel p-4 shadow-pop">
      <div className="label">Connected database</div>
      {info?.connected ? (
        <div className="mt-1.5 space-y-0.5 text-sm">
          <div className="font-semibold">{info.name} <span className="font-normal text-faint">· {info.engine}</span></div>
          <div className="truncate font-mono text-2xs text-faint" title={info.path}>{info.path}</div>
          <div className="text-2xs text-muted">
            {info.tables} tables · {info.read_only ? "opened read-only" : "read-write"}
          </div>
        </div>
      ) : (
        <p className="mt-1.5 text-sm text-muted">{info?.reason || "No database is connected."}</p>
      )}

      <div className="my-3 border-t border-line" />
      <label className="label" htmlFor="db-path">Open another SQLite file</label>
      <input id="db-path" className="input mt-1.5 w-full font-mono text-xs" placeholder="C:\data\my_database.db"
        value={path} onChange={(e) => setPath(e.target.value)} autoFocus
        onKeyDown={(e) => e.key === "Enter" && path.trim() && connect()} />
      <p className="mt-1.5 text-2xs text-faint">
        The path is read by the backend on this machine. Files are opened read-only, so your data is never modified.
      </p>
      {error && <p className="mt-2 rounded-md bg-[color:var(--err-soft)] px-2.5 py-1.5 text-xs text-err">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn btn-ghost text-xs" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary text-xs" onClick={connect} disabled={busy || !path.trim()}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </div>
    </div>
  );
}
