import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, type Project } from "./api";
import { lastProject, rememberProject, useBootstrap } from "./hooks";
import { ActivityPage } from "./pages/Activity";
import { CostsPage } from "./pages/Costs";
import { DashboardPage } from "./pages/Dashboard";
import { DeliverablesPage } from "./pages/Deliverables";
import { NewProjectPage } from "./pages/NewProject";
import { OfficePage } from "./pages/Office";
import { ProjectDetailPage } from "./pages/ProjectDetail";
import { ProjectsPage } from "./pages/Projects";
import { SettingsPage } from "./pages/Settings";
import { TeamPage } from "./pages/Team";
import { Empty, inputCls } from "./ui";

const NAV: { to: string; label: string; scoped?: boolean }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/office", label: "Virtual Office", scoped: true },
  { to: "/team", label: "Team" },
  { to: "/projects", label: "Projects" },
  { to: "/deliverables", label: "Deliverables", scoped: true },
  { to: "/activity", label: "Activity", scoped: true },
  { to: "/costs", label: "Costs", scoped: true },
  { to: "/settings", label: "Settings" },
];

function Sidebar() {
  const boot = useBootstrap();
  const providers = boot.data?.providers ?? [];
  const configured = providers.filter((p) => p.provider !== "scripted-test" && p.status === "valid");
  return (
    <nav aria-label="Main" className="flex shrink-0 flex-col gap-1 border-b border-line bg-panel p-3 md:w-56 md:border-b-0 md:border-r">
      <div className="mb-2 flex items-center gap-2 px-2">
        <img src="/favicon.svg" alt="" className="h-6 w-6 [image-rendering:pixelated]" />
        <span className="font-semibold tracking-tight">AgentOffice</span>
      </div>
      <div className="flex flex-wrap gap-1 md:flex-col">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"}
            className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-accent text-accentInk" : "text-ink hover:bg-panel2"}`}>
            {n.label}
          </NavLink>
        ))}
      </div>
      <div className="mt-auto hidden px-2 pt-4 text-xs text-muted md:block">
        {configured.length ? `AI providers: ${configured.map((p) => p.provider).join(", ")}` : "No AI provider connected yet"}
        {boot.data?.test_provider_enabled && <div className="mt-1 text-warn">Test provider enabled (not AI)</div>}
      </div>
    </nav>
  );
}

export function ProjectPicker({ base }: { base: string }) {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  const last = lastProject();
  if (last && q.data?.some((p) => p.id === last)) return <Navigate to={`${base}/${last}`} replace />;
  if (q.data && q.data.length === 0) return <Empty>No projects yet. Create one from the Dashboard.</Empty>;
  return (
    <div className="max-w-md">
      <label className="text-sm font-medium" htmlFor="pp">Choose a project</label>
      <select id="pp" className={`${inputCls} mt-1`} defaultValue="" onChange={(e) => e.target.value && nav(`${base}/${e.target.value}`)}>
        <option value="" disabled>Select…</option>
        {q.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </div>
  );
}

function Scoped({ base, render }: { base: string; render: (pid: string) => ReactNode }) {
  const { pid } = useParams();
  if (!pid) return <ProjectPicker base={base} />;
  rememberProject(pid);
  return <>{render(pid)}</>;
}

export function ProjectSwitcher({ pid, base }: { pid: string; base: string }) {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["projects"], queryFn: () => api.get<Project[]>("/projects") });
  return (
    <select aria-label="Project" className={`${inputCls} w-auto max-w-xs`} value={pid} onChange={(e) => nav(`${base}/${e.target.value}`)}>
      {q.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
    </select>
  );
}

function Locked() {
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="max-w-md rounded-lg border border-line bg-panel p-6 shadow-sm">
        <h1 className="text-lg font-semibold">AgentOffice is locked</h1>
        <p className="mt-2 text-sm text-muted">
          This browser isn't signed in to your local AgentOffice. To open it, run this in the AgentOffice folder:
        </p>
        <pre className="mt-3 rounded bg-panel2 p-2 text-sm">./agentoffice open</pre>
        <p className="mt-3 text-xs text-muted">
          The sign-in token stops other programs and users on this computer from using your API keys.
        </p>
      </div>
    </div>
  );
}

export default function App() {
  const auth = useQuery({ queryKey: ["auth"], queryFn: api.authCheck, retry: false, staleTime: Infinity });
  if (auth.isPending) return null;
  if (auth.isError) return <Locked />;
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <Sidebar />
      <main className="min-w-0 flex-1 p-4 md:p-6">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:pid" element={<Scoped base="/projects" render={(pid) => <ProjectDetailPage pid={pid} />} />} />
          <Route path="/office/:pid?" element={<Scoped base="/office" render={(pid) => <OfficePage pid={pid} />} />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/deliverables/:pid?" element={<Scoped base="/deliverables" render={(pid) => <DeliverablesPage pid={pid} />} />} />
          <Route path="/activity/:pid?" element={<Scoped base="/activity" render={(pid) => <ActivityPage pid={pid} />} />} />
          <Route path="/costs/:pid?" element={<Scoped base="/costs" render={(pid) => <CostsPage pid={pid} />} />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
