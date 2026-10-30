import { useEffect, useState } from "react";
import { setApiToken } from "../api";

/** Prompts for the shared API token when the server answers 401. Stored in sessionStorage only. */
export function TokenGate() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");

  useEffect(() => {
    const on = () => setOpen(true);
    window.addEventListener("qp-unauthorized", on);
    return () => window.removeEventListener("qp-unauthorized", on);
  }, []);

  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label="API token required"
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
      <form className="panel w-full max-w-sm space-y-3 border-line-2 p-6 shadow-pop"
        onSubmit={(e) => { e.preventDefault(); setApiToken(value.trim()); window.location.reload(); }}>
        <h2 className="font-display text-xl font-light tracking-tight">This server requires an access token</h2>
        <p className="text-2xs text-faint">It is a single shared token set by whoever runs the server, kept only for this browser tab.</p>
        <input className="input w-full font-mono text-xs" type="password" autoFocus autoComplete="off"
          aria-label="Access token" value={value} onChange={(e) => setValue(e.target.value)} />
        <div className="flex justify-end">
          <button className="btn btn-primary text-xs" disabled={!value.trim()}>Continue</button>
        </div>
      </form>
    </div>
  );
}
