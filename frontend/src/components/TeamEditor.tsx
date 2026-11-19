import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, money, type Agent, type AgentDefinition, type ModelConfig } from "../api";
import { useBootstrap } from "../hooks";
import { AvatarIcon, Badge, Button, Card, Dialog, ErrorText, Field, StatusBadge, inputCls } from "../ui";

interface Recommendation { basis: string; roles: { role_key: string; reason: string; definition: AgentDefinition }[] }

export function modelLabel(m: ModelConfig | undefined) {
  if (!m) return "unknown model";
  const price = m.input_price_per_mtok !== null && m.output_price_per_mtok !== null
    ? `$${m.input_price_per_mtok}/$${m.output_price_per_mtok} per M tokens` : "price not configured";
  return `${m.display_name} — ${price}`;
}

export function ModelSelect({ provider, modelId, onChange, id }: { provider: string | null; modelId: string | null; onChange: (p: string, m: string) => void; id?: string }) {
  const models = useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelConfig[]>("/models") });
  const boot = useBootstrap();
  const providers = boot.data?.providers ?? [];
  const value = provider && modelId ? `${provider}::${modelId}` : "";
  const groups = new Map<string, ModelConfig[]>();
  for (const m of (models.data ?? []).filter((x) => x.enabled)) groups.set(m.provider, [...(groups.get(m.provider) ?? []), m]);
  return (
    <select id={id} className={inputCls} value={value} onChange={(e) => { const [p, m] = e.target.value.split("::"); onChange(p, m); }}>
      {!value && <option value="">Choose a model…</option>}
      {[...groups.entries()].map(([prov, ms]) => {
        const st = providers.find((p) => p.provider === prov);
        const note = prov === "scripted-test" ? " (test only — not AI)" : st?.status === "valid" ? "" : " (no API key yet)";
        return (
          <optgroup key={prov} label={`${prov}${note}`}>
            {ms.map((m) => <option key={m.id} value={`${m.provider}::${m.model_id}`}>{modelLabel(m)} [{m.cost_tier}]</option>)}
          </optgroup>
        );
      })}
    </select>
  );
}

function AgentForm({ pid, agent, onDone }: { pid: string; agent: Agent; onDone: () => void }) {
  const qc = useQueryClient();
  const boot = useBootstrap();
  const [f, setF] = useState({
    name: agent.display_name, role: agent.role, description: agent.description, instructions: agent.instructions,
    provider: agent.provider, model_id: agent.model_id, effort: agent.effort, tools: agent.tools,
    spend_limit_usd: agent.spend_limit_usd === null ? "" : String(agent.spend_limit_usd), is_orchestrator: agent.is_orchestrator,
    max_calls_per_task: agent.max_calls_per_task,
  });
  const save = useMutation({
    mutationFn: () => api.patch(`/projects/${pid}/agents/${agent.id}`, {
      ...f, spend_limit_usd: f.spend_limit_usd === "" ? null : Number(f.spend_limit_usd), is_orchestrator: f.is_orchestrator || undefined,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["state", pid] }); onDone(); },
  });
  const perms = boot.data?.tool_permissions ?? {};
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Role"><input className={inputCls} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} /></Field>
      </div>
      <Field label="AI model" hint="Model changes take effect at the agent's next safe checkpoint, never mid-tool-call.">
        <ModelSelect provider={f.provider} modelId={f.model_id} onChange={(p, m) => setF({ ...f, provider: p, model_id: m })} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Effort" hint="Higher effort thinks longer and costs more.">
          <select className={inputCls} value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>
            {["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}
          </select>
        </Field>
        <Field label="Spending limit (USD)" hint="Blank = no per-agent limit.">
          <input className={inputCls} inputMode="decimal" value={f.spend_limit_usd} onChange={(e) => setF({ ...f, spend_limit_usd: e.target.value })} />
        </Field>
        <Field label="Max model calls per task">
          <input className={inputCls} type="number" min={1} max={100} value={f.max_calls_per_task} onChange={(e) => setF({ ...f, max_calls_per_task: Number(e.target.value) })} />
        </Field>
      </div>
      <Field label="Job description (instructions)">
        <textarea className={`${inputCls} h-28`} value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} />
      </Field>
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Authorized responsibilities</legend>
        <div className="grid gap-1 sm:grid-cols-2">
          {Object.entries(perms).map(([k, v]) => (
            <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={f.tools.includes(k)}
                onChange={(e) => setF({ ...f, tools: e.target.checked ? [...f.tools, k] : f.tools.filter((t) => t !== k) })} />
              {v.label}{v.consequential && <Badge tone="warn" title="Needs your approval per run">approval</Badge>}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={f.is_orchestrator} onChange={(e) => setF({ ...f, is_orchestrator: e.target.checked })} />
        Project manager for this project (plans and delegates)
      </label>
      <ErrorText error={save.error} />
      <div className="flex justify-end gap-2"><Button type="button" onClick={onDone}>Cancel</Button><Button variant="primary" disabled={save.isPending}>Save</Button></div>
    </form>
  );
}

export function TeamEditor({ pid, agents, locked }: { pid: string; agents: Agent[]; locked?: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Agent | null>(null);
  const [showLibrary, setShowLibrary] = useState(false);
  const [presetName, setPresetName] = useState("");
  const rec = useQuery({ queryKey: ["recommendation", pid], queryFn: () => api.get<Recommendation>(`/projects/${pid}/recommendation`) });
  const [aiRec, setAiRec] = useState<Recommendation | null>(null);
  const defs = useQuery({ queryKey: ["definitions"], queryFn: () => api.get<AgentDefinition[]>("/agent-definitions"), enabled: showLibrary });
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api.get<{ id: string; name: string }[]>("/team-presets") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["state", pid] });
  const hire = useMutation({ mutationFn: (definitionId: string) => api.post(`/projects/${pid}/agents`, { agent_definition_id: definitionId }), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/projects/${pid}/agents/${id}`), onSuccess: refresh });
  const applyPreset = useMutation({ mutationFn: (id: string) => api.post(`/projects/${pid}/agents/apply-preset`, { preset_id: id }), onSuccess: refresh });
  const savePreset = useMutation({ mutationFn: () => api.post(`/projects/${pid}/team/save-preset`, { name: presetName }),
    onSuccess: () => { setPresetName(""); qc.invalidateQueries({ queryKey: ["presets"] }); } });
  const askPm = useMutation({ mutationFn: () => api.post<Recommendation>(`/projects/${pid}/recommendation/ai`), onSuccess: setAiRec });
  const hiredDefs = new Set(agents.map((a) => a.agent_definition_id));
  const models = useQuery({ queryKey: ["models"], queryFn: () => api.get<ModelConfig[]>("/models") });
  const modelOf = (a: Agent) => models.data?.find((m) => m.provider === a.provider && m.model_id === a.model_id);
  const suggestions = (aiRec ?? rec.data)?.roles.filter((r) => !agents.some((a) => a.role_key === r.role_key)) ?? [];

  return (
    <div className="space-y-4">
      <Card title={`Hired team (${agents.length})`} actions={!locked && <Button onClick={() => setShowLibrary(true)}>+ Hire from library</Button>}>
        {agents.length === 0 ? <p className="text-sm text-muted">No one hired yet. Start with the recommendations below.</p> : (
          <ul className="grid gap-3 md:grid-cols-2">
            {agents.map((a) => (
              <li key={a.id} className="flex gap-3 rounded-md border border-line bg-bg p-3">
                <AvatarIcon avatar={a.avatar} label={`${a.display_name} avatar`} />
                <div className="min-w-0 flex-1 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{a.display_name}</span>
                    {a.is_orchestrator && <Badge tone="info">Project manager</Badge>}
                    <Badge title="Relative price tier derived from configured prices (heuristic, not a benchmark)">{a.cost_tier}</Badge>
                  </div>
                  <div className="text-muted">{a.role}</div>
                  <div className="truncate text-xs text-muted">{modelLabel(modelOf(a))}</div>
                  <div className="mt-1 text-xs text-muted">{a.tools.length} responsibilities · spent {money(a.estimated_spend_usd)}{a.spend_limit_usd !== null && ` of ${money(a.spend_limit_usd)}`}</div>
                  <div className="mt-2 flex gap-2">
                    <Button onClick={() => setEditing(a)}>Edit</Button>
                    {!locked && <Button variant="ghost" onClick={() => remove.mutate(a.id)}>Remove</Button>}
                    <StatusBadge status={a.status} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        <ErrorText error={hire.error || remove.error} />
      </Card>

      {!locked && (
        <Card title="Recommended roles" actions={agents.some((a) => a.is_orchestrator) &&
          <Button disabled={askPm.isPending} onClick={() => askPm.mutate()}>{askPm.isPending ? "Asking…" : "Ask the PM to propose a team"}</Button>}>
          <p className="mb-2 text-xs text-muted">Basis: {(aiRec ?? rec.data)?.basis ?? "…"}</p>
          <ErrorText error={askPm.error} />
          {suggestions.length === 0 ? <p className="text-sm text-muted">All recommended roles are hired.</p> : (
            <ul className="grid gap-2 md:grid-cols-2">
              {suggestions.map((r) => (
                <li key={r.role_key} className="flex items-center gap-3 rounded-md border border-line p-2.5 text-sm">
                  <AvatarIcon avatar={r.definition.avatar} size={2} />
                  <div className="min-w-0 flex-1"><div className="font-medium">{r.definition.name} — {r.definition.role}</div><div className="text-xs text-muted">{r.reason}</div></div>
                  <Button variant="primary" disabled={hire.isPending} onClick={() => hire.mutate(r.definition.id)}>Hire</Button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-line pt-3">
            {presets.data && presets.data.length > 0 && (
              <select aria-label="Apply saved team" className={`${inputCls} w-auto`} defaultValue="" onChange={(e) => e.target.value && applyPreset.mutate(e.target.value)}>
                <option value="" disabled>Apply a saved team…</option>
                {presets.data.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            )}
            <input aria-label="Saved team name" className={`${inputCls} w-auto`} placeholder="Save this team as…" value={presetName} onChange={(e) => setPresetName(e.target.value)} />
            <Button disabled={!presetName || agents.length === 0} onClick={() => savePreset.mutate()}>Save team</Button>
            {savePreset.isSuccess && <span className="text-xs text-ok">Saved</span>}
          </div>
        </Card>
      )}

      <Dialog open={!!editing} title={`Edit ${editing?.display_name ?? ""}`} onClose={() => setEditing(null)} wide>
        {editing && <AgentForm pid={pid} agent={editing} onDone={() => setEditing(null)} />}
      </Dialog>
      <Dialog open={showLibrary} title="Hire from the agent library" onClose={() => setShowLibrary(false)} wide>
        <ul className="grid gap-2 md:grid-cols-2">
          {defs.data?.map((d) => (
            <li key={d.id} className="flex items-center gap-3 rounded-md border border-line p-2.5 text-sm">
              <AvatarIcon avatar={d.avatar} size={2} />
              <div className="min-w-0 flex-1"><div className="font-medium">{d.name} — {d.role}</div><div className="line-clamp-2 text-xs text-muted">{d.description}</div></div>
              <Button variant="primary" disabled={hire.isPending || hiredDefs.has(d.id)} onClick={() => hire.mutate(d.id)}>{hiredDefs.has(d.id) ? "Hired" : "Hire"}</Button>
            </li>
          ))}
        </ul>
      </Dialog>
    </div>
  );
}
