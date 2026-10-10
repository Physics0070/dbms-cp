import { useEffect, useState } from "react";
import { api, fmt, SchemaResponse } from "../api";
import { Badge, ErrorNote, Loading, Panel } from "../components/ui";

export default function SchemaExplorer() {
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.schema().then(setSchema).catch((e) => setError(e.message)); }, []);
  if (error) return <ErrorNote message={error} />;
  if (!schema) return <Loading label="Discovering schema…" />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">Schema Explorer</h1>
        <p className="text-sm text-muted">
          Discovered dynamically from {schema.database_backend} · {schema.tables.length} tables ·{" "}
          {schema.relationships.length} relationships.
        </p>
      </div>

      {schema.relationships.length > 0 && (
        <Panel title="Relationships">
          <div className="flex flex-wrap gap-2">
            {schema.relationships.map((r, i) => (
              <div key={i} className="rounded-lg border border-line bg-panel-2 px-2.5 py-1.5 text-xs">
                <span className="font-mono">{r.from_table}.{r.from_columns.join(",")}</span>
                <span className="mx-1.5 text-accent">→</span>
                <span className="font-mono">{r.to_table}.{r.to_columns.join(",")}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="grid gap-4 lg:grid-cols-2 stagger">
        {schema.tables.map((t) => (
          <Panel key={t.name} bodyClass="p-0"
            title={<div className="flex items-center gap-2">{t.name}<span className="text-2xs font-normal text-faint">{fmt(t.row_count, 0)} rows</span></div>}>
            <table className="data">
              <thead><tr><th>Column</th><th>Type</th><th>Null</th><th>Key</th></tr></thead>
              <tbody>
                {t.columns.map((c) => (
                  <tr key={c.name}>
                    <td className="font-mono text-xs">{c.name}</td>
                    <td className="text-xs text-muted">{c.data_type}</td>
                    <td className="text-xs text-faint">{c.nullable ? "yes" : "no"}</td>
                    <td>{c.primary_key && <Badge tone="warn">PK</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {t.indexes.length > 0 && (
              <div className="flex flex-wrap gap-1.5 border-t border-line p-3">
                {t.indexes.map((idx) => (
                  <Badge key={idx.name} tone={idx.unique ? "accent" : "neutral"}>
                    {idx.name} ({idx.columns.join(", ")}){idx.unique ? " · uniq" : ""}
                  </Badge>
                ))}
              </div>
            )}
          </Panel>
        ))}
      </div>
    </div>
  );
}
