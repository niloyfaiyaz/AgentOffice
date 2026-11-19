import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type AgentDefinition } from "../api";
import { ModelSelect } from "../components/TeamEditor";
import { useBootstrap } from "../hooks";
import { AvatarIcon, Badge, Button, Card, Dialog, ErrorText, Field, inputCls } from "../ui";

const blank = {
  name: "", role: "", description: "", instructions: "", provider: "anthropic", model_id: "claude-opus-5-5",
  effort: "medium", tools: ["file_read", "artifact_read", "artifact_write", "client_questions"],
  avatar: { skin: "#e0ac69", hair: "#333333", shirt: "#6c757d", pants: "#343a40", accent: "#ffc107" },
};

function DefinitionForm({ d, onDone }: { d: AgentDefinition | null; onDone: () => void }) {
  const qc = useQueryClient();
  const boot = useBootstrap();
  const [f, setF] = useState(d ? { name: d.name, role: d.role, description: d.description, instructions: d.instructions,
    provider: d.provider ?? "anthropic", model_id: d.model_id ?? "", effort: d.effort, tools: d.tools, avatar: { ...blank.avatar, ...d.avatar } } : blank);
  const save = useMutation({
    mutationFn: () => d ? api.patch(`/agent-definitions/${d.id}`, f) : api.post("/agent-definitions", f),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["definitions"] }); onDone(); },
  });
  const colors = ["skin", "hair", "shirt", "pants", "accent"] as const;
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <div className="flex gap-4">
        <AvatarIcon avatar={f.avatar} size={5} label="Avatar preview" />
        <div className="grid flex-1 gap-3 sm:grid-cols-2">
          <Field label="Name"><input required className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Role"><input required className={inputCls} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} /></Field>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            {colors.map((c) => (
              <label key={c} className="flex items-center gap-1 text-xs capitalize">{c}
                <input type="color" value={(f.avatar as Record<string, string>)[c]} onChange={(e) => setF({ ...f, avatar: { ...f.avatar, [c]: e.target.value } })} /></label>
            ))}
          </div>
        </div>
      </div>
      <Field label="Specialization (shown on the card)"><input className={inputCls} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="Job description"><textarea className={`${inputCls} h-28`} value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} /></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Default model"><ModelSelect provider={f.provider} modelId={f.model_id} onChange={(p, m) => setF({ ...f, provider: p, model_id: m })} /></Field>
        <Field label="Effort"><select className={inputCls} value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>
          {["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}</select></Field>
      </div>
      <fieldset><legend className="mb-1 text-sm font-medium">Authorized responsibilities</legend>
        <div className="grid gap-1 sm:grid-cols-2">{Object.entries(boot.data?.tool_permissions ?? {}).map(([k, v]) => (
          <label key={k} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.tools.includes(k)}
            onChange={(e) => setF({ ...f, tools: e.target.checked ? [...f.tools, k] : f.tools.filter((t) => t !== k) })} />{v.label}</label>
        ))}</div>
      </fieldset>
      <ErrorText error={save.error} />
      <div className="flex justify-end gap-2"><Button type="button" onClick={onDone}>Cancel</Button><Button variant="primary">Save</Button></div>
    </form>
  );
}

export function TeamPage() {
  const qc = useQueryClient();
  const defs = useQuery({ queryKey: ["definitions"], queryFn: () => api.get<AgentDefinition[]>("/agent-definitions") });
  const presets = useQuery({ queryKey: ["presets"], queryFn: () => api.get<{ id: string; name: string; agent_definition_ids: string[] }[]>("/team-presets") });
  const [edit, setEdit] = useState<AgentDefinition | null | "new">(null);
  const archive = useMutation({ mutationFn: (id: string) => api.del(`/agent-definitions/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["definitions"] }) });
  const delPreset = useMutation({ mutationFn: (id: string) => api.del(`/team-presets/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["presets"] }) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">Team library</h1>
          <p className="text-sm text-muted">Reusable employee profiles. Hire them onto a project from its Team tab; project copies can be customized.</p></div>
        <Button variant="primary" onClick={() => setEdit("new")}>Create custom role</Button>
      </div>
      <Card title="Consultants">
        <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {defs.data?.map((d) => (
            <li key={d.id} className="flex gap-3 rounded-md border border-line bg-bg p-3 text-sm">
              <AvatarIcon avatar={d.avatar} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{d.name}</span>{d.is_builtin && <Badge>built-in</Badge>}
                  <Badge title="Heuristic price tier from configured prices, not a benchmark">{d.cost_tier}</Badge></div>
                <div className="text-muted">{d.role}</div>
                <p className="mt-1 line-clamp-3 text-xs text-muted">{d.description}</p>
                <p className="mt-1 text-xs text-muted">{d.provider}/{d.model_id} · {d.tools.length} responsibilities</p>
                <div className="mt-2 flex gap-2"><Button onClick={() => setEdit(d)}>Edit</Button>{!d.is_builtin && <Button variant="ghost" onClick={() => archive.mutate(d.id)}>Archive</Button>}</div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Saved teams">
        {presets.data?.length ? (
          <ul className="space-y-1 text-sm">{presets.data.map((p) => (
            <li key={p.id} className="flex items-center justify-between"><span>{p.name} <span className="text-muted">· {p.agent_definition_ids.length} agents</span></span>
              <Button variant="ghost" onClick={() => delPreset.mutate(p.id)}>Delete</Button></li>
          ))}</ul>
        ) : <p className="text-sm text-muted">Save a team from any project's Team tab.</p>}
      </Card>
      <Dialog open={edit !== null} title={edit === "new" ? "Create a custom role" : `Edit ${edit?.name ?? ""}`} onClose={() => setEdit(null)} wide>
        {edit !== null && <DefinitionForm d={edit === "new" ? null : edit} onDone={() => setEdit(null)} />}
      </Dialog>
    </div>
  );
}
