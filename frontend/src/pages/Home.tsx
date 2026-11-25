import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type Project } from "../api";
import { projectStatus } from "../components/ProjectSwitcher";
import { useBootstrap } from "../hooks";
import { Badge, Button, Card, Empty, inputCls } from "../ui";

export function projectHref(p: Project): string {
  // No run yet: still in setup. Otherwise the workspace (which itself returns to setup while the
  // first plan awaits approval).
  return p.run_status ? `/p/${p.id}` : `/new/${p.id}`;
}

/** Home / My Projects: find, resume or start projects; see which need attention. */
export function HomePage() {
  const boot = useBootstrap();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const list = useQuery({
    queryKey: ["projects", "home", archived], refetchInterval: 10_000,
    queryFn: () => api.get<Project[]>(`/projects${archived ? "?archived=true" : ""}`),
  });
  const real = (boot.data?.providers ?? []).filter((p) => p.provider !== "scripted-test" && p.status === "valid");
  const projects = (list.data ?? []).filter((p) => p.name.toLowerCase().includes(q.trim().toLowerCase()));
  const attention = projects.filter((p) => (p.needs_input ?? 0) > 0);
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">My projects</h1>
          <p className="text-sm text-muted">Your AI project teams. Describe an idea to start a new one.</p>
        </div>
        <Link to="/new" className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accentInk hover:brightness-110">+ New project</Link>
      </div>
      {!real.length && (
        <div role="status" className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
          No AI provider connected. You can set projects up now; to run real agents, <Link to="/settings" className="font-medium text-accent underline">connect Anthropic or OpenAI in Settings</Link>.
          {boot.data?.test_provider_enabled && " A scripted test provider is enabled for automated tests; it is not AI."}
        </div>
      )}
      {attention.length > 0 && !archived && (
        <Card title={`Needs your attention (${attention.length})`} actions={<Link to="/inbox" className="text-sm text-accent hover:underline">Open inbox</Link>}>
          <ul className="divide-y divide-line">{attention.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
              <Link to={projectHref(p)} className="font-medium hover:underline">{p.name}</Link>
              <Badge tone="warn">{p.needs_input} to do</Badge>
            </li>))}</ul>
        </Card>
      )}
      <Card title={archived ? "Archived projects" : "All projects"} actions={
        <div className="flex items-center gap-2">
          <input aria-label="Search projects" placeholder="Search…" className={`${inputCls} w-44`} value={q} onChange={(e) => setQ(e.target.value)} />
          <Button variant="ghost" onClick={() => setArchived(!archived)} aria-pressed={archived}>{archived ? "Show active" : "Show archived"}</Button>
        </div>}>
        {!list.data ? <p className="text-sm text-muted">Loading…</p> : projects.length === 0 ? (
          q ? <Empty>No project matches “{q}”.</Empty> : archived ? <Empty>No archived projects.</Empty> : (
            <div className="py-6 text-center">
              <p className="text-sm text-muted">No projects yet.</p>
              <Link to="/new" className="mt-3 inline-block rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accentInk">Describe your first project</Link>
            </div>)
        ) : (
          <ul className="divide-y divide-line" aria-label="Projects">
            {projects.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <Link to={projectHref(p)} className="font-medium hover:underline">{p.name}</Link>
                  <p className="truncate text-xs text-muted">{p.objective}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  {!!p.needs_input && <Badge tone="warn">{p.needs_input} to do</Badge>}
                  <span className="text-muted">{p.agents} agents · est. {money(p.estimated_spend_usd)} · updated {new Date(p.updated_at).toLocaleDateString()}</span>
                  <Badge>{projectStatus(p)}</Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
