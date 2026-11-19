import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, money, type AgentEvent, type Project, type ProviderStatus } from "../api";
import { useBootstrap } from "../hooks";
import { Badge, Card, Empty, StatusBadge, fmtTime } from "../ui";

interface DashboardData {
  projects: (Project & { pending_approvals: number; estimated_spend_usd: number; agents: number })[];
  recent_activity: AgentEvent[];
  team_presets: { id: string; name: string; description: string; agent_definition_ids: string[] }[];
  providers: ProviderStatus[];
}

export function DashboardPage() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<DashboardData>("/dashboard"), refetchInterval: 10_000 });
  const boot = useBootstrap();
  const d = q.data;
  const realProviders = (d?.providers ?? []).filter((p) => p.provider !== "scripted-test");
  const anyValid = realProviders.some((p) => p.status === "valid");
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Your consulting office</h1>
          <p className="text-sm text-muted">Assemble an AI team, approve the plan, watch the work, review the deliverables.</p>
        </div>
        <Link to="/projects/new" className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accentInk hover:brightness-110">
          Start new project
        </Link>
      </div>

      {!anyValid && (
        <div role="status" className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
          You can explore and set up projects without an API key. To run real agents,{" "}
          <Link to="/settings" className="font-medium text-accent underline">connect Anthropic or OpenAI in Settings</Link>.
          {boot.data?.test_provider_enabled && " A scripted test provider is enabled for automated testing; it is not an AI model."}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Projects" className="lg:col-span-2">
          {!d ? <p className="text-sm text-muted">Loading…</p> : d.projects.length === 0 ? (
            <Empty>No projects yet. Start one to recruit your first team.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {d.projects.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link to={`/projects/${p.id}`} className="font-medium hover:underline">{p.name}</Link>
                    <p className="truncate text-xs text-muted">{p.objective}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {p.pending_approvals > 0 && <Badge tone="warn">{p.pending_approvals} decision{p.pending_approvals > 1 ? "s" : ""} needed</Badge>}
                    <span className="text-muted">{p.agents} agents · est. {money(p.estimated_spend_usd)}</span>
                    <StatusBadge status={p.status} />
                    <Link to={`/office/${p.id}`} className="text-accent hover:underline">Office →</Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-5">
          <Card title="AI providers" actions={<Link to="/settings" className="text-sm text-accent hover:underline">Manage</Link>}>
            <ul className="space-y-1.5 text-sm">
              {realProviders.map((p) => (
                <li key={p.provider} className="flex items-center justify-between">
                  <span className="capitalize">{p.provider}</span>
                  <StatusBadge status={p.configured ? p.status : "not connected"} />
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Saved teams" actions={<Link to="/team" className="text-sm text-accent hover:underline">Team library</Link>}>
            {d?.team_presets.length ? (
              <ul className="space-y-1 text-sm">{d.team_presets.map((t) => <li key={t.id}>{t.name} <span className="text-muted">· {t.agent_definition_ids.length} agents</span></li>)}</ul>
            ) : <p className="text-sm text-muted">Save a project's team to reuse it.</p>}
          </Card>
          <Card title="Templates">
            <ul className="space-y-1 text-sm">
              {boot.data?.templates.map((t) => (
                <li key={t.key}><Link to={`/projects/new?template=${t.key}`} className="hover:underline">{t.name}</Link></li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <Card title="Recent activity">
        {d?.recent_activity.length ? (
          <ol className="space-y-1 text-sm">
            {d.recent_activity.map((e) => (
              <li key={e.seq} className="flex flex-wrap gap-x-3">
                <time className="w-40 shrink-0 text-xs text-muted">{fmtTime(e.created_at)}</time>
                <span className="text-muted">{e.project_name}</span>
                <span className="min-w-0">{e.message}</span>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm text-muted">Nothing yet.</p>}
      </Card>
    </div>
  );
}
