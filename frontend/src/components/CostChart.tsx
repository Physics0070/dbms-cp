import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const AXIS = "var(--faint)";
const MONO = "'JetBrains Mono', ui-monospace, monospace";

function ChartTip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="border border-line-2 bg-panel px-3 py-2 font-mono text-xs">
      <div className="text-ink">{label ?? payload[0].payload?.label}</div>
      <div className="mt-0.5 tabular-nums text-muted">
        {Number(payload[0].value).toLocaleString(undefined, { maximumFractionDigits: 2 })} {unit}
      </div>
    </div>
  );
}

/** Horizontal bars so join-order labels stay readable. The selected plan is orange AND says so in text. */
export function CostBarChart({
  data, selectedId,
}: {
  data: { id: string; label: string; cost: number }[];
  selectedId?: string;
}) {
  const height = Math.max(150, data.length * 34 + 44);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 96, left: 4, bottom: 4 }} barCategoryGap={6}>
        <XAxis type="number" tick={{ fontSize: 11, fill: AXIS, fontFamily: MONO }} tickLine={false}
          axisLine={{ stroke: "var(--line)" }} />
        <YAxis type="category" dataKey="label" width={132} interval={0}
          tick={{ fontSize: 11, fill: "var(--muted)", fontFamily: MONO }} tickLine={false} axisLine={{ stroke: "var(--line-2)" }} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTip unit="cost (estimated)" />} />
        <Bar dataKey="cost" radius={0} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={d.id} fill={d.id === selectedId ? "var(--accent)" : "var(--line-2)"} />
          ))}
          <LabelList dataKey="cost" position="right" content={(p: any) => {
            const d = data[p.index];
            const sel = d?.id === selectedId;
            return (
              <text x={Number(p.x) + Number(p.width) + 8} y={Number(p.y) + Number(p.height) / 2 + 4}
                fontSize={11} fontFamily={MONO} fill={sel ? "var(--accent)" : "var(--muted)"}>
                {Number(d.cost).toLocaleString(undefined, { maximumFractionDigits: 1 })}{sel ? "  ◀ selected" : ""}
              </text>
            );
          }} />
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
        <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: AXIS, fontFamily: MONO }} tickLine={false}
          axisLine={{ stroke: "var(--line)" }} interval={0} angle={-12} textAnchor="end" height={54} />
        <YAxis tick={{ fontSize: 11, fill: AXIS, fontFamily: MONO }} tickLine={false} axisLine={false} width={48} />
        <Tooltip cursor={{ fill: "var(--accent-soft)" }} content={<ChartTip unit={unit} />} />
        <Bar dataKey={yKey} fill="var(--accent)" radius={0} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
