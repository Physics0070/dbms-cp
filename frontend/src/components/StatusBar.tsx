import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";

/** Slim mono footer: engine - tables - access mode - query state. Real values only. */
export function StatusBar() {
  const { loading, result } = useStore();
  const [info, setInfo] = useState<any | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    api.database().then(setInfo).catch(() => setDown(true));
  }, []);

  const state = loading ? "running" : result ? "ready" : "idle";
  const stateCls = loading ? "text-warn" : result ? "text-ok" : "text-faint";
  const sep = <span aria-hidden="true" className="text-line-2">/</span>;

  return (
    <footer className="flex h-8 shrink-0 items-center gap-3 overflow-x-auto whitespace-nowrap border-t border-line bg-panel px-4 font-mono text-[11px] uppercase tracking-[0.12em] text-muted"
      role="status" aria-label="Connection status">
      {down ? <span className="text-err">backend unreachable</span> : info?.connected ? (
        <>
          <span className="text-ink">{info.engine}</span>{sep}
          <span>{info.tables} tables</span>{sep}
          <span>{info.read_only ? "read-only" : "read-write"}</span>
        </>
      ) : <span>no database</span>}
      <span className="ml-auto flex items-center gap-2">
        <span>query</span>
        <span className={stateCls}>{state}</span>
      </span>
    </footer>
  );
}
