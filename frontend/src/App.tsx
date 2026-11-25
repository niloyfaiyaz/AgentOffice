import { useQuery } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { api } from "./api";
import { useBootstrap } from "./hooks";
import { HomePage } from "./pages/Home";
import { InboxPage, useInbox } from "./pages/Inbox";
import { NewProjectPage } from "./pages/NewProject";
import { SettingsPage } from "./pages/Settings";
import { SetupPage } from "./pages/Setup";
import { TeamPage } from "./pages/Team";
import { Workspace } from "./pages/Workspace";

function Sidebar() {
  const boot = useBootstrap();
  const inbox = useInbox();
  const n = inbox.data?.actions.length ?? 0;
  const providers = boot.data?.providers ?? [];
  const configured = providers.filter((p) => p.provider !== "scripted-test" && p.status === "valid");
  const NAV = [
    { to: "/", label: "My projects", end: true }, { to: "/new", label: "+ New project", end: true },
    { to: "/inbox", label: "Inbox", badge: n }, { to: "/settings", label: "Settings" },
  ];
  return (
    <nav aria-label="Main" className="flex shrink-0 flex-col gap-1 border-b border-line bg-panel p-3 md:w-52 md:border-b-0 md:border-r">
      <div className="mb-2 flex items-center gap-2 px-2">
        <img src="/favicon.svg" alt="" className="h-6 w-6 [image-rendering:pixelated]" />
        <span className="font-semibold tracking-tight">AgentOffice</span>
      </div>
      <div className="flex flex-wrap gap-1 md:flex-col">
        {NAV.map((x) => (
          <NavLink key={x.to} to={x.to} end={x.end}
            className={({ isActive }) => `flex items-center justify-between rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-accent text-accentInk" : "text-ink hover:bg-panel2"}`}>
            {x.label}
            {!!x.badge && <span aria-label={`${x.badge} items need you`} className="ml-2 rounded-full bg-warn px-1.5 text-xs font-semibold text-black">{x.badge}</span>}
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

/** Old feature-first URLs keep working. */
function Legacy({ to }: { to: string }) {
  const { pid } = useParams();
  return <Navigate to={pid ? `/p/${pid}${to}` : "/"} replace />;
}

function SetupRoute() {
  const { pid } = useParams();
  return pid ? <SetupPage key={pid} pid={pid} /> : <Navigate to="/new" replace />;
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
          <Route path="/" element={<HomePage />} />
          <Route path="/new" element={<NewProjectPage />} />
          <Route path="/new/:pid" element={<SetupRoute />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/p/:pid/*" element={<Workspace />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/settings/agents" element={<TeamPage />} />
          <Route path="/projects" element={<Navigate to="/" replace />} />
          <Route path="/projects/new" element={<Navigate to="/new" replace />} />
          <Route path="/projects/:pid" element={<Legacy to="" />} />
          <Route path="/office/:pid?" element={<Legacy to="" />} />
          <Route path="/deliverables/:pid?" element={<Legacy to="/deliverables" />} />
          <Route path="/activity/:pid?" element={<Legacy to="/activity" />} />
          <Route path="/costs/:pid?" element={<Legacy to="/team" />} />
          <Route path="/team" element={<Navigate to="/settings/agents" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
