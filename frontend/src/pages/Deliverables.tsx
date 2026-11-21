import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ProjectSwitcher } from "../App";
import { api, type Artifact, type Finding } from "../api";
import { useProjectState } from "../hooks";
import { Badge, Button, Card, Empty, ErrorText, StatusBadge, fmtTime, inputCls } from "../ui";

const EXPORTS: Record<string, string[]> = {
  markdown: ["md", "docx", "json", "txt"], json: ["json", "txt"], csv: ["csv", "json", "txt"], text: ["txt", "json", "docx"], code: ["txt", "json"],
};

export function DeliverablesPage({ pid }: { pid: string }) {
  const qc = useQueryClient();
  const st = useProjectState(pid);
  const arts = useQuery({ queryKey: ["artifacts", pid], queryFn: () => api.get<Artifact[]>(`/projects/${pid}/artifacts`) });
  const findings = useQuery({ queryKey: ["findings", pid], queryFn: () => api.get<Finding[]>(`/projects/${pid}/findings`) });
  const [sel, setSel] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const detail = useQuery({ queryKey: ["artifacts", "detail", sel, version], enabled: !!sel,
    queryFn: () => api.get<Artifact>(`/artifacts/${sel}${version ? `?version=${version}` : ""}`) });
  const accept = useMutation({ mutationFn: (status: string) => api.post(`/artifacts/${sel}/acceptance`, { status, comment }),
    onSuccess: () => { setComment(""); qc.invalidateQueries({ queryKey: ["artifacts"] }); } });
  const agentName = (id: string | null) => st.data?.agents.find((a) => a.id === id)?.display_name ?? "—";
  const groups = ["deliverable", "summary", "plan", "working"];
  const a = detail.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Deliverables</h1><ProjectSwitcher pid={pid} base="/deliverables" /></div>
        <a href={`/api/projects/${pid}/export`} className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accentInk" download>Export all (.zip)</a>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <Card title="Files">
          {!arts.data?.length ? <Empty>No deliverables yet.</Empty> : groups.map((g) => {
            const xs = arts.data!.filter((x) => x.category === g);
            if (!xs.length) return null;
            return (
              <div key={g} className="mb-3">
                <h3 className="mb-1 text-xs font-semibold uppercase text-muted">{g === "plan" ? "Plans" : g === "summary" ? "Summaries" : g === "working" ? "Working files" : "Deliverables"}</h3>
                <ul className="space-y-1">{xs.map((x) => (
                  <li key={x.id}><button onClick={() => { setSel(x.id); setVersion(null); }} aria-pressed={sel === x.id}
                    className={`w-full rounded-md px-2 py-1.5 text-left text-sm ${sel === x.id ? "bg-accent/15" : "hover:bg-panel2"}`}>
                    <div className="truncate font-medium">{x.name}</div>
                    <div className="flex flex-wrap gap-1 text-xs text-muted">v{x.current_version} · {x.artifact_type} · {agentName(x.owner_agent_id)}
                      <StatusBadge status={x.acceptance_status} />{x.stale && <Badge tone="warn" title={x.stale_reason || "Affected by a later requirement change"}>stale</Badge>}</div>
                  </button></li>
                ))}</ul>
              </div>
            );
          })}
        </Card>
        <div className="min-w-0 space-y-4">
          {!a ? <Empty>Select a deliverable to read it.</Empty> : (
            <Card title={a.name} actions={
              <>
                <select aria-label="Version" className={`${inputCls} w-auto`} value={a.viewing_version} onChange={(e) => setVersion(Number(e.target.value))}>
                  {a.versions?.map((v) => <option key={v.version} value={v.version}>v{v.version} · {fmtTime(v.created_at)}</option>)}
                </select>
                {EXPORTS[a.artifact_type]?.map((f) => <a key={f} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-panel2" href={`/api/artifacts/${a.id}/export?format=${f}`} download>.{f}</a>)}
              </>}>
              <p className="mb-2 text-sm text-muted">{a.versions?.find((v) => v.version === a.viewing_version)?.summary}</p>
              {a.stale && <p role="status" className="mb-2 rounded-md bg-warn/10 p-2 text-sm text-warn">Not current: {a.stale_reason}</p>}
              {(() => { const v = a.versions?.find((x) => x.version === a.viewing_version); return v && (
                <p className="mb-2 text-xs text-muted">Implements: {v.requirement_refs?.join(", ") || "—"}{v.inputs?.length ? ` · derived from: ${v.inputs.join(", ")}` : ""}</p>); })()}
              {!!a.source_refs?.length && <p className="mb-2 text-xs text-muted">Sources: {a.source_refs.join(" · ")}</p>}
              <pre className="prose-doc max-h-[60vh] overflow-auto rounded-md border border-line bg-bg p-3">{a.content}</pre>
              <div className="mt-3 space-y-2 border-t border-line pt-3">
                <textarea aria-label="Comment" className={`${inputCls} h-14`} placeholder="Comment (used as revision feedback)" value={comment} onChange={(e) => setComment(e.target.value)} />
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" onClick={() => accept.mutate("accepted")}>Accept</Button>
                  <Button disabled={!comment} onClick={() => accept.mutate("revision_requested")}>Request changes</Button>
                </div>
                <ErrorText error={accept.error} />
              </div>
            </Card>
          )}
          <Card title="QA findings">
            {!findings.data?.length ? <p className="text-sm text-muted">No findings recorded. (A QA approval is a review opinion, not proof of correctness.)</p> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-sm">
                  <thead className="text-xs text-muted"><tr><th className="py-1">ID</th><th>Severity</th><th>Deliverable</th><th>Requirement</th><th>Evidence → recommendation</th><th>Status</th></tr></thead>
                  <tbody>{findings.data.map((f) => (
                    <tr key={f.id} className="border-t border-line align-top">
                      <td className="py-1.5 font-mono text-xs">{f.finding_key}</td><td><StatusBadge status={f.severity} /></td>
                      <td className="text-xs">{arts.data?.find((x) => x.id === f.artifact_id)?.name ?? "—"}</td>
                      <td className="text-xs">{f.requirement_ref}</td>
                      <td className="text-xs">{f.evidence}<br /><span className="text-muted">→ {f.recommendation}</span></td>
                      <td><StatusBadge status={f.status} /></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
