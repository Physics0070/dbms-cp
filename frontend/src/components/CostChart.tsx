import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const AXIS = "var(--faint)";

function ChartTip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-panel px-3 py-2 text-xs shadow-pop">
      <div className="font-semibold text-ink">{label}</div>
      <div className="mt-0.5 tabular-nums text-muted">
        {Number(payload[0].value).toLocaleString(undefined, { maximumFractionDigits: 2 })} {unit}
      </div>
    </div>
  );
}

export function CostBarChart({
  data, selectedId, height = 260,
}: {
  data: { id: string; label: string; cost: number }[];
  selectedId?: string;
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
        <XAxis dataKey="label" tick={{ fontSize: 11, fill: AXIS }} tickLine={false}
          axisLine={{ stroke: "var(--line)" }} interval={0} angle={-12} textAnchor="end" height={54} />
        <YAxis tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={false} width={48} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTip unit="cost" />} />
        <Bar dataKey="cost" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.id} fill={d.id === selectedId ? "var(--accent)" : "var(--line-2)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function GenericBarChart({
  data, xKey, yKey, height = 260, unit = "",
}: {
  data: any[]; xKey: string; yKey: string; height?: number; unit?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
        <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: AXIS }} tickLine={false}
          axisLine={{ stroke: "var(--line)" }} interval={0} angle={-12} textAnchor="end" height={54} />
        <YAxis tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={false} width={48} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTip unit={unit} />} />
        <Bar dataKey={yKey} fill="var(--accent)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
