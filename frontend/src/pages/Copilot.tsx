import { useState } from "react";
import { api } from "../api";
import { Card, NeedRun, Loading, Badge } from "../components/ui";
import { useStore } from "../store";

function renderMarkdown(md: string) {
  // Minimal, safe markdown-ish renderer (headings, bold, bullets).
  const lines = md.split("\n");
  return lines.map((line, i) => {
    if (line.startsWith("### ")) return <h3 key={i} className="mt-4 text-sm font-bold uppercase tracking-wide text-brand-600">{line.slice(4)}</h3>;
    if (line.startsWith("- ")) return <li key={i} className="ml-5 list-disc">{inline(line.slice(2))}</li>;
    if (line.trim() === "") return <div key={i} className="h-2" />;
    return <p key={i} className="text-sm">{inline(line)}</p>;
  });
}
function inline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : <span key={i}>{p}</span>
  );
}

export default function Copilot() {
  const { result, sql } = useStore();
  const [answer, setAnswer] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [question, setQuestion] = useState("");
  const [err, setErr] = useState<string | null>(null);

  if (!result) return <NeedRun />;

  async function ask(q?: string) {
    setLoading(true); setErr(null);
    try { setAnswer(await api.copilot(sql, q)); }
    catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">AI Copilot</h1>
        <p className="text-sm text-slate-500">
          Explanations are grounded strictly in the optimizer's own structured output — the model is
          instructed never to invent metrics, and works offline via a deterministic fallback.
        </p>
      </header>

      <Card>
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn btn-primary" onClick={() => ask()} disabled={loading}>Explain selected plan</button>
          <input
            className="min-w-[16rem] flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            placeholder="Ask a question about this plan…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && question && ask(question)}
          />
          <button className="btn btn-ghost" onClick={() => question && ask(question)} disabled={loading || !question}>Ask</button>
        </div>
      </Card>

      {loading && <Card><Loading label="Consulting the copilot…" /></Card>}
      {err && <Card><div className="text-sm text-red-600">{err}</div></Card>}

      {answer && (
        <Card title={<span>Explanation <Badge tone={answer.source === "openai" ? "green" : "slate"}>{answer.source}{answer.model ? ` · ${answer.model}` : ""}</Badge></span>}>
          {answer.warning && <div className="mb-3 rounded bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">{answer.warning}</div>}
          <div className="prose-sm max-w-none">{renderMarkdown(answer.explanation)}</div>
        </Card>
      )}
    </div>
  );
}
