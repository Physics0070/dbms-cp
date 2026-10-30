import { useState } from "react";
import { remoteApi, RemoteConnection } from "../api";

const PORTS = { postgresql: "5432", mysql: "3306" } as const;
const SSL = ["prefer", "require", "verify-full", "verify-ca", "allow", "disable"] as const;

/**
 * PostgreSQL / MySQL connection form. The password lives only in this component's state, is sent once
 * over the request body, and is cleared as soon as the request settles; it is never written
 * to localStorage or kept in the shared store, and the server never returns it.
 */
export function RemoteConnect({ onConnected }: { onConnected?: () => void }) {
  const [engine, setEngine] = useState<"postgresql" | "mysql">("postgresql");
  const [f, setF] = useState({ host: "", port: "5432", database: "", user: "", sslmode: "prefer" as RemoteConnection["sslmode"] });
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"test" | "connect" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const port = Number(f.port);
  const portOk = Number.isInteger(port) && port >= 1 && port <= 65535;
  const valid = f.host.trim() && f.database.trim() && f.user.trim() && portOk;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }));

  async function run(kind: "test" | "connect") {
    setBusy(kind);
    setMsg(null);
    const body: RemoteConnection = { engine, ...f, host: f.host.trim(), port, password };
    try {
      if (kind === "test") {
        const r = await remoteApi.test(body);
        setMsg({ ok: true, text: `Connected to ${engine === "mysql" ? "MySQL" : "PostgreSQL"} ${r.server_version}: ${r.tables} tables. Nothing was switched.` });
      } else {
        await remoteApi.connect(body);
        try { localStorage.removeItem("sql"); } catch { /* ignore */ }
        (onConnected ?? (() => window.location.reload()))();
      }
    } catch (e: any) {
      setMsg({ ok: false, text: e.message || String(e) });  // previous connection is untouched on failure
    } finally {
      setPassword("");
      setBusy(null);
    }
  }

  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (valid && !busy) run("connect"); }} autoComplete="off">
      <div className="label">Connect to a database server</div>
      <select className="input w-full text-xs" aria-label="Engine" value={engine}
        onChange={(e) => { const v = e.target.value as "postgresql" | "mysql"; setEngine(v); setF((s) => ({ ...s, port: PORTS[v] })); }}>
        <option value="postgresql">PostgreSQL</option>
        <option value="mysql">MySQL 8 (MariaDB unverified)</option>
      </select>
      <div className="grid grid-cols-[1fr_5rem] gap-2">
        <input className="input text-xs" placeholder="host" aria-label="Host" value={f.host} onChange={set("host")} />
        <input className="input text-xs" placeholder="5432" aria-label="Port" inputMode="numeric" value={f.port} onChange={set("port")}
          aria-invalid={!portOk} />
      </div>
      <input className="input w-full text-xs" placeholder="database" aria-label="Database" value={f.database} onChange={set("database")} />
      <div className="grid grid-cols-2 gap-2">
        <input className="input text-xs" placeholder="user" aria-label="User" autoComplete="off" value={f.user} onChange={set("user")} />
        <input className="input text-xs" type="password" placeholder="password" aria-label="Password" autoComplete="new-password"
          value={password} onChange={(e) => setPassword(e.target.value)} />
      </div>
      {engine === "postgresql" && <select className="input w-full text-xs" aria-label="SSL mode" value={f.sslmode} onChange={set("sslmode")}>
        {SSL.map((s) => <option key={s} value={s}>sslmode={s}</option>)}
      </select>}
      <p className="text-2xs text-faint">
        Use a read-only role. Every statement runs in a read-only session with a server-side timeout. The password is sent once,
        never stored, and not shown again. Hosts on private or loopback addresses are blocked unless the server operator allows them.
      </p>
      {msg && (
        <p role="status" className={`border-l-2 px-2.5 py-1.5 text-xs ${msg.ok ? "border-[color:var(--ok)] bg-[color:var(--ok-soft)] text-ok" : "border-[color:var(--err)] bg-[color:var(--err-soft)] text-err"}`}>
          {msg.text}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" className="btn btn-ghost text-xs" disabled={!valid || !!busy} onClick={() => run("test")}>
          {busy === "test" ? "Testing…" : "Test"}
        </button>
        <button type="submit" className="btn btn-primary text-xs" disabled={!valid || !!busy}>
          {busy === "connect" ? "Connecting…" : "Connect"}
        </button>
      </div>
    </form>
  );
}
