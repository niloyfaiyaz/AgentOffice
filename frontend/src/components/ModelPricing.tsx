import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ModelConfig } from "../api";
import { Badge, Button, Card, ErrorText, inputCls } from "../ui";

function Row({ m }: { m: ModelConfig }) {
  const qc = useQueryClient();
  const [inp, setInp] = useState(m.input_price_per_mtok?.toString() ?? "");
  const [out, setOut] = useState(m.output_price_per_mtok?.toString() ?? "");
  const save = useMutation({
    mutationFn: () => api.patch(`/models/${m.id}`, { input_price_per_mtok: inp === "" ? null : Number(inp), output_price_per_mtok: out === "" ? null : Number(out) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
  const toggle = useMutation({ mutationFn: () => api.patch(`/models/${m.id}`, { enabled: !m.enabled }), onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }) });
  return (
    <tr className="border-t border-line align-top">
      <td className="py-1.5"><div className="font-medium">{m.display_name}</div><div className="text-xs text-muted">{m.provider}/{m.model_id}{m.discovered && " · visible to your key"}</div></td>
      <td className="text-xs">{m.context_window ? `${(m.context_window / 1000).toFixed(0)}k ctx` : "—"}{m.max_output_tokens ? ` · ${(m.max_output_tokens / 1000).toFixed(0)}k out` : ""}</td>
      <td><input aria-label={`Input price for ${m.model_id}`} className={`${inputCls} w-20`} inputMode="decimal" value={inp} onChange={(e) => setInp(e.target.value)} /></td>
      <td><input aria-label={`Output price for ${m.model_id}`} className={`${inputCls} w-20`} inputMode="decimal" value={out} onChange={(e) => setOut(e.target.value)} /></td>
      <td className="max-w-[220px] text-xs text-muted">{m.pricing_source}</td>
      <td><Badge title="Heuristic tier from configured prices">{m.cost_tier}</Badge></td>
      <td className="space-x-1 whitespace-nowrap">
        <Button disabled={save.isPending} onClick={() => save.mutate()}>Save</Button>
        <Button variant="ghost" onClick={() => toggle.mutate()}>{m.enabled ? "Hide" : "Show"}</Button>
        <ErrorText error={save.error} />
      </td>
    </tr>
  );
}

export function ModelPricing() {
  const models = useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelConfig[]>("/models") });
  const rows = (models.data ?? []).filter((m) => m.provider !== "scripted-test");
  return (
    <Card title="Model prices (USD per million tokens)">
      <p className="mb-2 text-xs text-muted">Published prices change; verify them with your provider. Models without prices cannot be budget-enforced.
        Capability notes come from provider model listings, not from AgentOffice benchmarks.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="text-xs text-muted"><tr><th className="py-1">Model</th><th>Limits</th><th>Input</th><th>Output</th><th>Source</th><th>Tier</th><th></th></tr></thead>
          <tbody>{rows.map((m) => <Row key={m.id} m={m} />)}</tbody>
        </table>
      </div>
    </Card>
  );
}
