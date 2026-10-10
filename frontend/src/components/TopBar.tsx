import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";

export function TopBar() {
  const { theme, toggleTheme } = useStore();
  const [health, setHealth] = useState<any | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setDown(true));
  }, []);

  const connected = !!health && !down;

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-line bg-panel px-4">
      <div className="flex items-center gap-2.5">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-sm font-bold text-accentfg">◧</span>
        <div className="leading-tight">
          <div className="text-sm font-semibold">DBMS-CP</div>
          <div className="text-2xs text-faint">Cost-Based SQL Optimizer</div>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div
          className="flex items-center gap-2 rounded-lg border border-line bg-panel-2 px-2.5 py-1.5 text-xs"
          title={connected ? "Connected to the database backend" : "Backend unreachable"}
        >
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-ok" : "bg-err"}`}
            style={connected ? { boxShadow: "0 0 0 3px var(--ok-soft)" } : undefined} />
          <span className="hidden text-muted sm:inline">
            {connected ? health.database_backend : down ? "Disconnected" : "Connecting…"}
          </span>
          {connected && (
            <span className="rounded bg-panel-3 px-1.5 py-0.5 text-2xs tabular-nums text-faint">
              {health.tables?.length ?? 0} tables
            </span>
          )}
        </div>
        <button className="btn btn-ghost !px-2.5" onClick={toggleTheme}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`} aria-label="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>
    </header>
  );
}
