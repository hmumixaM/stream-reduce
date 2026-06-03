import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { Card } from "@/components/ui";
import { formatCost, formatMs } from "@/lib/utils";

const COLORS = ["#818cf8", "#f87171", "#34d399", "#fbbf24", "#f472b6", "#60a5fa"];

export function Stats() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.getStats, refetchInterval: 10000 });
  if (!stats.data) return <p className="text-muted-foreground">Loading...</p>;
  const s = stats.data;

  const stageData = Object.entries(s.avg_stage_ms).map(([stage, ms]) => ({
    stage,
    avg: Math.round(ms / 1000),
  }));
  const platformData = Object.entries(s.items_by_platform).map(([name, value]) => ({
    name,
    value,
  }));

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Stats</h1>

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Items" value={String(s.total_items)} />
        <Stat label="Total cost" value={formatCost(s.total_cost_usd)} />
        <Stat
          label="STT requests"
          value={s.openrouter_requests.toLocaleString()}
          sub={`${s.openrouter_tokens.toLocaleString()} tok`}
        />
        <Stat
          label="Gemini tokens"
          value={s.gemini_tokens.toLocaleString()}
          sub={s.http_429_total > 0 ? `${s.http_429_total}× 429` : "no 429s"}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-4 text-sm font-semibold">Avg time per stage (s)</h2>
          {stageData.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={stageData}>
                <XAxis dataKey="stage" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                />
                <Bar dataKey="avg" radius={[4, 4, 0, 0]}>
                  {stageData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty />
          )}
        </Card>

        <Card className="p-5">
          <h2 className="mb-4 text-sm font-semibold">Items by platform</h2>
          {platformData.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={platformData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={50}
                  outerRadius={90}
                  paddingAngle={2}
                >
                  {platformData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <Empty />
          )}
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <h2 className="mb-3 text-sm font-semibold">Total time per stage</h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Object.entries(s.total_stage_ms).map(([stage, ms]) => (
            <div key={stage} className="rounded-md bg-muted/50 p-3">
              <div className="text-lg font-semibold">{formatMs(ms)}</div>
              <div className="text-xs capitalize text-muted-foreground">{stage}</div>
            </div>
          ))}
          {Object.keys(s.total_stage_ms).length === 0 && <Empty />}
        </div>
      </Card>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
      {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
    </Card>
  );
}

function Empty() {
  return <p className="text-sm text-muted-foreground">No data yet.</p>;
}
