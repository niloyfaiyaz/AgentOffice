import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type Project } from "../api";
import { Button, Card, Empty, StatusBadge, fmtTime } from "../ui";

export function ProjectsPage() {
  const [archived, setArchived] = useState(false);
  const q = useQuery({ queryKey: ["projects", archived], queryFn: () => api.get<Project[]>(`/projects?archived=${archived}`) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <div className="flex gap-2">
          <Button onClick={() => setArchived(!archived)} aria-pressed={archived}>{archived ? "Show active" : "Show archived"}</Button>
          <Link to="/projects/new" className="rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accentInk">New project</Link>
        </div>
      </div>
      <Card>
        {!q.data ? <p className="text-sm text-muted">Loading…</p> : q.data.length === 0 ? <Empty>{archived ? "No archived projects." : "No projects yet."}</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="text-xs text-muted"><tr><th className="py-2">Project</th><th>Status</th><th>Est. spend</th><th>Updated</th><th></th></tr></thead>
              <tbody>
                {q.data.map((p) => (
                  <tr key={p.id} className="border-t border-line">
                    <td className="py-2"><Link to={`/projects/${p.id}`} className="font-medium hover:underline">{p.name}</Link>
                      <div className="max-w-md truncate text-xs text-muted">{p.objective}</div></td>
                    <td><StatusBadge status={p.status} /></td>
                    <td>{money(p.estimated_spend_usd)}</td>
                    <td className="text-xs text-muted">{fmtTime(p.updated_at)}</td>
                    <td className="space-x-3 text-right"><Link to={`/office/${p.id}`} className="text-accent hover:underline">Office</Link>
                      <Link to={`/deliverables/${p.id}`} className="text-accent hover:underline">Deliverables</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
