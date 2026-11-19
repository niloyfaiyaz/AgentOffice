import { useQuery } from "@tanstack/react-query";
import { ProjectSwitcher } from "../App";
import { api, money, type Budget } from "../api";
import { ModelPricing } from "../components/ModelPricing";
import { Badge, Card, Empty } from "../ui";

interface Agg { key: string; calls: number; input_tokens: number; output_tokens: number; cache_read_tokens: number; estimated_cost_usd: number; unpriced_calls: number; test_calls: number }
interface Costs { estimated_total_usd: number; budget: Budget; by_agent: Agg[]; by_task: Agg[]; by_model: Agg[]; records: any[]; disclaimer: string }

function AggTable({ rows, label }: { rows: Agg[]; label: string }) {
  const max = Math.max(...rows.map((r) => r.estimated_cost_usd), 0);
  if (!rows.length) return <p className="text-sm text-muted">No usage yet.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="text-xs text-muted"><tr><th className="py-1">{label}</th><th>Calls</th><th>Tokens in / out</th><th>Est. cost</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.key} className="border-t border-line">
            <td className="py-1.5">{r.key}</td><td>{r.calls}</td><td className="text-xs">{r.input_tokens.toLocaleString()} / {r.output_tokens.toLocaleString()}</td>
            <td><div className="flex items-center gap-2">
              <span className="w-20">{money(r.estimated_cost_usd)}</span>
              <span className="h-2 rounded bg-accent" style={{ width: `${max ? (r.estimated_cost_usd / max) * 120 : 0}px` }} aria-hidden />
              {r.unpriced_calls > 0 && <Badge tone="warn" title="Calls on models without configured prices">{r.unpriced_calls} unpriced</Badge>}
              {r.test_calls > 0 && <Badge title="Scripted test provider — no real cost">{r.test_calls} test</Badge>}
            </div></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function CostsPage({ pid }: { pid: string }) {
  const q = useQuery({ queryKey: ["costs", pid], queryFn: () => api.get<Costs>(`/projects/${pid}/costs`) });
  const c = q.data;
  const pct = c?.budget.budget_usd ? Math.min(100, (c.estimated_total_usd / c.budget.budget_usd) * 100) : null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Costs</h1><ProjectSwitcher pid={pid} base="/costs" /></div>
      {c && <p role="note" className="rounded-md border border-line bg-panel2 p-3 text-xs text-muted">{c.disclaimer}</p>}
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Estimated spend"><p className="text-3xl font-semibold">{money(c?.estimated_total_usd)}</p></Card>
        <Card title="Budget">
          <p className="text-3xl font-semibold">{c?.budget.budget_usd !== null && c ? money(c.budget.budget_usd) : "None"}</p>
          {pct !== null && <div className="mt-2 h-2 w-full rounded bg-panel2" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
            <div className={`h-2 rounded ${pct >= (c?.budget.warning_threshold_pct ?? 80) ? "bg-warn" : "bg-ok"}`} style={{ width: `${pct}%` }} /></div>}
        </Card>
        <Card title="Model calls"><p className="text-3xl font-semibold">{c?.records.length ?? 0}</p></Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="By agent"><AggTable rows={c?.by_agent ?? []} label="Agent" /></Card>
        <Card title="By model"><AggTable rows={c?.by_model ?? []} label="Model" /></Card>
      </div>
      <Card title="By task"><AggTable rows={c?.by_task ?? []} label="Task" /></Card>
      <ModelPricing />
      <Card title="Usage records">
        {!c?.records.length ? <Empty>No usage records.</Empty> : (
          <div className="max-h-96 overflow-auto">
            <table className="w-full min-w-[720px] text-left text-xs">
              <thead className="sticky top-0 bg-panel text-muted"><tr><th className="py-1">Time</th><th>Agent</th><th>Task / purpose</th><th>Model</th><th>In</th><th>Out</th><th>Cache read</th><th>Est. cost</th></tr></thead>
              <tbody>{[...c.records].reverse().map((r) => (
                <tr key={r.id} className="border-t border-line">
                  <td className="py-1">{new Date(r.created_at).toLocaleString()}</td><td>{r.agent}</td><td>{r.task ?? r.purpose}</td>
                  <td>{r.provider}/{r.model_id}</td><td>{r.input_tokens}</td><td>{r.output_tokens}</td><td>{r.cache_read_tokens}</td>
                  <td>{r.is_test_provider ? "test" : r.estimated_cost_usd === null ? "unpriced" : money(r.estimated_cost_usd, 6)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
