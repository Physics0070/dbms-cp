import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "../api";

const KEYWORDS = new Set([
  "select", "from", "where", "join", "inner", "left", "right", "full", "outer", "cross",
  "on", "group", "by", "order", "having", "limit", "offset", "as", "and", "or", "not",
  "in", "is", "null", "like", "between", "distinct", "asc", "desc", "union", "all",
  "with", "case", "when", "then", "else", "end", "exists",
]);
const FUNCS = new Set(["count", "sum", "avg", "min", "max", "coalesce", "cast", "round", "lower", "upper", "abs", "length"]);

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Single-pass tokenizer → highlighted HTML. Comments/strings first so keywords
// inside them aren't recolored.
const TOKEN = /(--[^\n]*|\/\*[\s\S]*?\*\/)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|([=<>!+\-*/%|]+)|([(),.;])/g;

export function highlight(code: string): string {
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(code))) {
    out += escapeHtml(code.slice(last, m.index));
    const [full, comment, str, num, ident, op, punct] = m;
    if (comment) out += `<span class="tok-com">${escapeHtml(comment)}</span>`;
    else if (str) out += `<span class="tok-str">${escapeHtml(str)}</span>`;
    else if (num) out += `<span class="tok-num">${num}</span>`;
    else if (ident) {
      const low = ident.toLowerCase();
      const cls = KEYWORDS.has(low) ? "tok-kw" : FUNCS.has(low) ? "tok-fn" : "";
      out += cls ? `<span class="${cls}">${escapeHtml(ident)}</span>` : escapeHtml(ident);
    } else if (op) out += `<span class="tok-op">${escapeHtml(op)}</span>`;
    else if (punct) out += `<span class="tok-punct">${escapeHtml(punct)}</span>`;
    last = m.index + full.length;
  }
  out += escapeHtml(code.slice(last));
  // trailing newline keeps the <pre> height in sync with the textarea
  return out + "\n";
}

/** Read-only, highlighted SQL block. Content is HTML-escaped by `highlight`.
 *  `marks` is a set of 0-based line indices to flag as added/removed (see lib/diff). */
export function SqlView({
  sql, maxHeight = 360, marks, markTone,
}: { sql: string; maxHeight?: number; marks?: Set<number>; markTone?: "add" | "del" }) {
  const lines = sql.split("\n");
  return (
    <pre className="sqled-shared overflow-auto rounded-sm border border-line bg-panel-2" style={{ maxHeight }}>
      {lines.map((line, i) => (
        <div key={i}
          className={marks?.has(i) ? (markTone === "del" ? "dl dl-del" : "dl dl-add") : "dl"}
          dangerouslySetInnerHTML={{ __html: highlight(line).replace(/\n$/, "") || "&nbsp;" }} />
      ))}
    </pre>
  );
}

export function SqlEditor({
  value, onChange, onRun, height = 220,
}: {
  value: string;
  onChange: (v: string) => void;
  onRun?: () => void;
  height?: number;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const gutRef = useRef<HTMLDivElement>(null);
  const [check, setCheck] = useState<{ valid: boolean; message: string } | null>(null);
  const lineCount = value.split("\n").length;

  const sync = (ta: HTMLTextAreaElement) => {
    if (preRef.current) { preRef.current.scrollTop = ta.scrollTop; preRef.current.scrollLeft = ta.scrollLeft; }
    if (gutRef.current) gutRef.current.style.transform = `translateY(${-ta.scrollTop}px)`;
  };
  useLayoutEffect(() => { if (taRef.current) sync(taRef.current); }, [value]);

  // Debounced server-side parse check; stale responses are ignored.
  useEffect(() => {
    if (!value.trim()) { setCheck(null); return; }
    let live = true;
    const t = setTimeout(() => {
      api.validate(value).then((r) => live && setCheck(r)).catch(() => live && setCheck(null));
    }, 600);
    return () => { live = false; clearTimeout(t); };
  }, [value]);

  async function format() {
    const { format: fmtSql } = await import("sql-formatter"); // lazy: loaded on first use
    try { onChange(fmtSql(value, { language: "sqlite", keywordCase: "upper" })); }
    catch { /* unparseable text is left as typed; the status line explains why */ }
  }

  const escaped = useRef(false);
  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Escape" && e.key !== "Tab") escaped.current = false;
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); onRun?.(); return; }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "f") { e.preventDefault(); format(); return; }
    if (e.key === "Escape") { escaped.current = true; return; }  // Esc, then Tab: leave the editor (no keyboard trap)
    if (e.key === "Tab" && !escaped.current) {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart, en = ta.selectionEnd;
      onChange(value.slice(0, s) + "  " + value.slice(en));
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 2; });
    }
  }

  return (
    <div>
      <div className="sqled sqled-nowrap overflow-hidden rounded-sm border border-line bg-panel-2 focus-within:border-[color:var(--accent)] focus-within:ring-2 focus-within:ring-[color:var(--ring)]"
        style={{ height }}>
        <div className="sqled-gutter" aria-hidden="true">
          <div ref={gutRef} className="sqled-shared sqled-gut-inner">
            {Array.from({ length: lineCount }, (_, i) => <div key={i}>{i + 1}</div>)}
          </div>
        </div>
        <pre ref={preRef} className="sqled-shared sqled-pre" aria-hidden="true"
          dangerouslySetInnerHTML={{ __html: highlight(value) }} />
        <textarea
          ref={taRef}
          className="sqled-shared sqled-ta"
          value={value}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          wrap="off"
          aria-label="SQL query editor"
          title="Tab inserts spaces. Press Esc, then Tab, to move focus out of the editor."
          aria-describedby="sqled-status"
          aria-invalid={check ? !check.valid : undefined}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          onScroll={(e) => sync(e.currentTarget)}
        />
      </div>
      <div className="mt-1.5 flex items-center gap-2 text-2xs">
        <span id="sqled-status" role="status" aria-live="polite"
          className={`min-w-0 flex-1 truncate ${check ? (check.valid ? "text-ok" : "text-err") : "text-faint"}`}>
          {check ? `${check.valid ? "✓" : "✕"} ${check.message.replace(/\x1b\[[0-9;]*m/g, "")}` : " "}
        </span>
        <button type="button" className="btn btn-ghost !px-2 !py-1 text-2xs" onClick={format}
          title="Format SQL (Ctrl+Shift+F)" aria-label="Format SQL">⌗ Format</button>
      </div>
    </div>
  );
}
