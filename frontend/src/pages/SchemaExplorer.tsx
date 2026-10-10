import { useEffect, useState } from "react";
import { api, fmt, SchemaResponse } from "../api";
import { Card, Loading, ErrorState, Badge } from "../components/ui";

export default function SchemaExplorer() {
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.schema().then(setSchema).catch((e) => setError(e.message)); }, []);

  if (error) return <ErrorState message={error} />;
  if (!schema) return <Loading label="Discovering schema…" />;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Schema Explorer</h1>
        <p className="text-sm text-slate-500">
          Dynamically discovered from {schema.database_backend}. {schema.tables.length} tables,{" "}
          {schema.relationships.length} foreign-key relationships.
        </p>
      </header>

      <Card title="Relationships (ER)">
        {schema.relationships.length === 0 ? (
          <div className="text-sm text-slate-500">No foreign-key relationships discovered.</div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {schema.relationships.map((r, i) => (
              <div key={i} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-950">
                <span className="font-mono">{r.from_table}({r.from_columns.join(",")})</span>
                <span className="mx-2 text-brand-600">→</span>
                <span className="font-mono">{r.to_table}({r.to_columns.join(",")})</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {schema.tables.map((t) => (
          <Card key={t.name} title={<span>{t.name} <span className="text-xs font-normal text-slate-400">· {fmt(t.row_count, 0)} rows</span></span>}>
            <table className="data">
              <thead><tr><th>Column</th><th>Type</th><th>Null</th><th>Key</th></tr></thead>
              <tbody>
                {t.columns.map((c) => (
                  <tr key={c.name}>
                    <td className="font-mono">{c.name}</td>
                    <td className="text-slate-500">{c.data_type}</td>
                    <td>{c.nullable ? "yes" : "no"}</td>
                    <td>{c.primary_key ? <Badge tone="amber">PK</Badge> : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {t.indexes.length > 0 && (
              <div className="mt-3">
                <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Indexes</div>
                <div className="flex flex-wrap gap-2">
                  {t.indexes.map((idx) => (
                    <Badge key={idx.name} tone={idx.unique ? "blue" : "slate"}>
                      {idx.name} ({idx.columns.join(", ")}){idx.unique ? " · unique" : ""}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
