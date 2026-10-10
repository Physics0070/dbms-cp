import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, OptimizeResult } from "./api";

interface Store {
  sql: string;
  setSql: (s: string) => void;
  result: OptimizeResult | null;
  loading: boolean;
  error: string | null;
  benchmark: boolean;
  setBenchmark: (b: boolean) => void;
  runOptimize: () => Promise<void>;
  loadResult: (r: OptimizeResult) => void;
  theme: "light" | "dark";
  toggleTheme: () => void;
}

const DEFAULT_SQL = `SELECT c.name, o.total, oi.quantity
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND c.country = 'India'
ORDER BY o.total DESC`;

const Ctx = createContext<Store | null>(null);

export function OptimizerProvider({ children }: { children: React.ReactNode }) {
  const [sql, setSql] = useState<string>(() => localStorage.getItem("sql") || DEFAULT_SQL);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [benchmark, setBenchmark] = useState(true);
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (localStorage.getItem("theme") as "light" | "dark") ||
      (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  const runOptimize = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      localStorage.setItem("sql", sql);
      const r = await api.optimize(sql, { benchmark, index_advisor: true });
      setResult(r);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [sql, benchmark]);

  const value: Store = {
    sql, setSql, result, loading, error, benchmark, setBenchmark, runOptimize,
    loadResult: (r) => { setResult(r); if (r?.sql) setSql(r.sql); },
    theme, toggleTheme: () => setTheme((t) => (t === "dark" ? "light" : "dark")),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const c = useContext(Ctx);
  if (!c) throw new Error("useStore must be inside OptimizerProvider");
  return c;
}
