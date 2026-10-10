import { useLayoutEffect, useRef } from "react";

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

function highlight(code: string): string {
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

  useLayoutEffect(() => {
    if (preRef.current && taRef.current) {
      preRef.current.scrollTop = taRef.current.scrollTop;
      preRef.current.scrollLeft = taRef.current.scrollLeft;
    }
  }, [value]);

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl/Cmd+Enter runs; Tab inserts two spaces instead of leaving the field.
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      onRun?.();
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const s = ta.selectionStart, en = ta.selectionEnd;
      const next = value.slice(0, s) + "  " + value.slice(en);
      onChange(next);
      requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 2; });
    }
  }

  return (
    <div className="sqled rounded-lg border border-line bg-panel-2 focus-within:border-[color:var(--accent)] focus-within:ring-2 focus-within:ring-[color:var(--ring)]"
      style={{ height }}>
      <pre ref={preRef} className="sqled-shared sqled-pre" aria-hidden="true"
        dangerouslySetInnerHTML={{ __html: highlight(value) }} />
      <textarea
        ref={taRef}
        className="sqled-shared sqled-ta"
        value={value}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        aria-label="SQL query editor"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKey}
        onScroll={(e) => {
          if (preRef.current) {
            preRef.current.scrollTop = e.currentTarget.scrollTop;
            preRef.current.scrollLeft = e.currentTarget.scrollLeft;
          }
        }}
      />
    </div>
  );
}
