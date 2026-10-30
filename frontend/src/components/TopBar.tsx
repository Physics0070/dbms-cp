import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { RemoteConnect } from "./RemoteConnect";

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
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-2 border-b border-line bg-[color:var(--bg)] px-4 sm:gap-4 sm:px-6">
      <a href="/" className="flex items-baseline gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]" title="Back to the overview" aria-label="QueryPilot, back to the overview">
        <span className="font-display text-xl tracking-tight">Query<span className="text-accent">Pilot</span></span>
        <span className="hidden font-mono text-[10px] uppercase tracking-[0.2em] text-faint md:inline">Query workbench</span>
      </a>

      <div className="relative ml-auto flex min-w-0 items-center gap-2">
        <button
          className="flex min-w-0 max-w-[340px] items-center gap-2 border border-line bg-panel px-2.5 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors hover:border-line-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)]"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-haspopup="dialog"
          title="Change database"
        >
          <span className={`h-1.5 w-1.5 shrink-0 ${connected ? "bg-ok" : "bg-err"}`} aria-hidden="true" />
          <span className="truncate text-muted">{label}</span>
          {connected && (
            <span className="hidden whitespace-nowrap tabular-nums text-faint sm:inline">
              {health.tables?.length ?? 0} tables
            </span>
          )}
          <span className="text-faint" aria-hidden="true">▾</span>
        </button>

        {open && <DatabasePopover onClose={() => setOpen(false)} />}

        <button className="btn btn-ghost shrink-0 !px-2.5" onClick={toggleTheme}
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

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      await api.uploadDatabase(file);
      try { localStorage.removeItem("sql"); } catch { /* ignore */ }
      window.location.reload();
    } catch (e: any) {
      setError(e.message || String(e));  // previous connection is untouched on failure
      setBusy(false);
    }
  }

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
      className="fixed inset-x-2 top-14 z-40 max-h-[calc(100vh-4.5rem)] overflow-y-auto animate-slide-up border border-line-2 bg-panel p-4 shadow-pop sm:absolute sm:inset-x-auto sm:right-12 sm:top-11 sm:w-[360px]">
      <div className="label">Connected database</div>
      {info?.connected ? (
        <div className="mt-1.5 space-y-0.5 text-sm">
          <div className="font-display text-xl font-light tracking-tight">{info.name} <span className="font-mono text-2xs uppercase tracking-widest text-faint">· {info.engine}</span></div>
          <div className="truncate font-mono text-2xs text-faint" title={info.path}>{info.path}</div>
          <div className="text-2xs text-muted">
            {info.tables} tables · {info.read_only ? "opened read-only" : "read-write"}
          </div>
        </div>
      ) : (
        <p className="mt-1.5 text-sm text-muted">{info?.reason || "No database is connected."}</p>
      )}

      <div className="my-3 border-t border-line" />
      <label className="label" htmlFor="db-upload">Upload a SQLite or DuckDB database</label>
      <input id="db-upload" type="file" accept=".db,.sqlite,.sqlite3,.db3,.duckdb,.ddb,application/vnd.sqlite3,application/octet-stream"
        disabled={busy} className="input mt-1.5 w-full text-xs file:mr-3 file:border-0 file:bg-transparent file:text-accent"
        onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
      <p className="mt-1.5 text-2xs text-faint">Stored on the server under a generated name and opened read-only. Max size is set by the server.</p>
      <div className="my-3 border-t border-line" />
      <label className="label" htmlFor="db-path">Open a SQLite or DuckDB file by path</label>
      <input id="db-path" className="input mt-1.5 w-full font-mono text-xs" placeholder="C:\data\my_database.db"
        value={path} onChange={(e) => setPath(e.target.value)} autoFocus
        onKeyDown={(e) => e.key === "Enter" && path.trim() && connect()} />
      <p className="mt-1.5 text-2xs text-faint">
        The path is read by the backend on this machine. Files are opened read-only, so your data is never modified.
      </p>
      <div className="my-3 border-t border-line" />
      <RemoteConnect />
      {error && <p className="mt-2 border-l-2 border-[color:var(--err)] bg-[color:var(--err-soft)] px-2.5 py-1.5 text-xs text-err">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <button className="btn btn-ghost text-xs" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary text-xs" onClick={connect} disabled={busy || !path.trim()}>
          {busy ? "Connecting…" : "Connect"}
        </button>
      </div>
    </div>
  );
}
