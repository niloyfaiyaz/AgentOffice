import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ProviderStatus } from "../api";
import { ModelPricing } from "../components/ModelPricing";
import { useBootstrap, useReducedMotion } from "../hooks";
import { Badge, Button, Card, ErrorText, Field, StatusBadge, fmtTime, inputCls } from "../ui";

function ProviderCard({ p }: { p: ProviderStatus }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ ok: boolean; models?: string[]; error?: string; note?: string } | null>(null);
  const done = () => { qc.invalidateQueries({ queryKey: ["bootstrap"] }); qc.invalidateQueries({ queryKey: ["models"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const save = useMutation({ mutationFn: () => api.put<any>(`/providers/${p.provider}/credential`, { api_key: key }), onSuccess: (r) => { setKey(""); setResult(r); done(); } });
  const test = useMutation({ mutationFn: () => api.post<any>(`/providers/${p.provider}/test`), onSuccess: (r) => { setResult(r); done(); } });
  const del = useMutation({ mutationFn: () => api.del(`/providers/${p.provider}/credential`), onSuccess: () => { setResult(null); done(); } });
  return (
    <Card title={<span className="capitalize">{p.provider}</span>} actions={<StatusBadge status={p.configured ? p.status : "not connected"} />}>
      {p.configured && (
        <p className="mb-2 text-sm text-muted">Key {p.key_hint} stored in {p.storage_backend === "keyring" ? "your operating system's keychain" : p.storage_backend}.
          {p.last_validated_at && ` Last checked ${fmtTime(p.last_validated_at)}.`}</p>
      )}
      {p.last_error && <p className="mb-2 text-sm text-bad">{p.last_error}</p>}
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <div className="min-w-[240px] flex-1">
          <Field label={p.configured ? "Replace API key" : "API key"} hint="Sent only to this local app, stored in your keychain, never shown again.">
            <input type="password" autoComplete="off" className={inputCls} value={key} onChange={(e) => setKey(e.target.value)} placeholder={p.provider === "anthropic" ? "sk-ant-…" : "sk-…"} />
          </Field>
        </div>
        <Button variant="primary" disabled={key.length < 8 || save.isPending}>{save.isPending ? "Saving…" : "Save & test"}</Button>
        {p.configured && <Button type="button" disabled={test.isPending} onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test connection"}</Button>}
        {p.configured && <Button type="button" variant="danger" onClick={() => del.mutate()}>Remove key</Button>}
      </form>
      <ErrorText error={save.error || test.error || del.error} />
      {result && (
        <div role="status" className={`mt-2 rounded-md p-2 text-sm ${result.ok ? "bg-ok/10" : "bg-bad/10"}`}>
          {result.ok ? <>Connected. {result.models?.length ?? 0} models visible to this key. <span className="text-muted">{result.note}</span></> : result.error}
        </div>
      )}
      <p className="mt-2 text-xs text-muted">A Claude Pro or ChatGPT subscription does not include API credits; use a key from the provider's developer console.</p>
    </Card>
  );
}

export function SettingsPage() {
  const boot = useBootstrap();
  const [reduced, setReduced] = useReducedMotion();
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem("ao.theme") ?? "system"; } catch { return "system"; } });
  const applyTheme = (t: string) => {
    setTheme(t);
    try { localStorage.setItem("ao.theme", t); } catch { /* ignore */ }
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
  };
  const b = boot.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h1 className="text-2xl font-semibold">Settings</h1>
        <a href="/settings/agents" className="text-sm text-accent underline">Agent library (reusable agent profiles)</a></div>
      <div className="grid gap-4 lg:grid-cols-2">
        {b?.providers.filter((p) => p.provider !== "scripted-test").map((p) => <ProviderCard key={p.provider} p={p} />)}
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Security & storage">
          <ul className="space-y-2 text-sm">
            <li>Credential storage: <Badge tone={b?.credential_backend === "keyring" ? "ok" : "warn"}>{b?.credential_backend === "keyring" ? "OS keychain" : b?.credential_backend}</Badge></li>
            <li>Code sandbox: {b?.sandbox.available ? <Badge tone="ok">Docker sandbox ready</Badge> : <><Badge tone="warn">unavailable</Badge> <span className="text-muted">{b?.sandbox.reason} Code execution tools are disabled.</span></>}</li>
            <li>Web research: only with Anthropic models, when you grant the permission and approve it for a run.</li>
            <li>Network: the app listens on 127.0.0.1 only.</li>
            {b?.test_provider_enabled && <li><Badge tone="warn">Scripted test provider enabled</Badge> <span className="text-muted">A deterministic non-AI provider for automated tests.</span></li>}
          </ul>
        </Card>
        <Card title="Privacy">
          <p className="text-sm text-muted">{b?.privacy_notice}</p>
          <p className="mt-2 text-sm text-muted">To delete data, delete a project (removes its history, files and exports) or remove an API key above.</p>
        </Card>
        <Card title="Appearance & accessibility">
          <div className="space-y-3 text-sm">
            <Field label="Theme"><select className={`${inputCls} w-auto`} value={theme} onChange={(e) => applyTheme(e.target.value)}>
              <option value="system">Match system</option><option value="light">Light</option><option value="dark">Dark</option></select></Field>
            <label className="flex items-center gap-2"><input type="checkbox" checked={reduced} onChange={(e) => setReduced(e.target.checked)} />Reduce motion in the office</label>
          </div>
        </Card>
      </div>
      <ModelPricing />
    </div>
  );
}
