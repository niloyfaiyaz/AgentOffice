import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type DiscoveryView } from "../api";
import { useBootstrap } from "../hooks";
import { Button, ErrorText } from "../ui";

/** Step 1: "What would you like your team to work on?" - free text, optional files and template. */
export function NewProjectPage() {
  const boot = useBootstrap();
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [tpl, setTpl] = useState<string | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [stage, setStage] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const providers = (boot.data?.providers ?? []).filter((p) => p.status === "valid");
  const realAI = providers.some((p) => p.provider !== "scripted-test");
  const start = useMutation({
    mutationFn: async () => {
      setStage("Creating your project…");
      const v = await api.post<DiscoveryView>("/discovery", { text: text.trim(), template_key: tpl });
      for (const f of files) {
        setStage(`Uploading ${f.name}…`);
        await api.upload(`/projects/${v.project.id}/files`, f);
      }
      setStage(`${v.pm?.display_name ?? "Your project manager"} is reading your idea…`);
      await api.post(`/projects/${v.project.id}/discovery/turn`, {});
      return v.project.id;
    },
    onSuccess: (pid) => nav(`/new/${pid}`),
    onSettled: () => setStage(""),
  });
  const templates = (boot.data?.templates ?? []).filter((t) => t.key !== "custom");
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-3xl flex-col justify-center gap-5 py-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold sm:text-3xl">What would you like your team to work on?</h1>
        <p className="mt-2 text-sm text-muted">Describe it in your own words. Your project manager will ask only what matters,
          then propose a brief, a team and a plan for you to approve. Nothing runs until you approve.</p>
      </div>
      {!realAI && (
        <div role="status" className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">
          No AI provider is connected yet, so the project manager can't ask clarifying questions. You can still start: the brief
          will be prefilled from your text (not by AI) for you to complete. <Link to="/settings" className="font-medium text-accent underline">Connect Anthropic or OpenAI</Link>.
          {boot.data?.test_provider_enabled && " (A scripted test provider is enabled for automated tests; it is not AI.)"}
        </div>
      )}
      <form className="rounded-xl border border-line bg-panel p-3 shadow-sm focus-within:outline focus-within:outline-2 focus-within:outline-accent"
        onSubmit={(e) => { e.preventDefault(); if (text.trim().length >= 3) start.mutate(); }}>
        <label htmlFor="idea" className="sr-only">Describe your project</label>
        <textarea id="idea" autoFocus value={text} onChange={(e) => setText(e.target.value)} rows={6}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && text.trim().length >= 3) start.mutate(); }}
          placeholder="e.g. Build a simple travel planning web app where friends can suggest activities, vote, and generate a shared itinerary."
          className="w-full resize-y bg-transparent p-2 text-base text-ink outline-none placeholder:text-muted" />
        {files.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-2 px-2 text-xs" aria-label="Attached files">
            {files.map((f) => (
              <li key={f.name} className="flex items-center gap-1 rounded-full border border-line bg-panel2 px-2 py-0.5">
                {f.name}<button type="button" aria-label={`Remove ${f.name}`} className="text-muted hover:text-ink" onClick={() => setFiles(files.filter((x) => x !== f))}>✕</button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-1 pt-2">
          <div className="flex items-center gap-2">
            <input ref={fileRef} type="file" multiple className="hidden" aria-label="Attach files"
              accept=".txt,.md,.pdf,.docx,.csv,.json,.py,.js,.ts,.tsx,.html,.css"
              onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])]); e.target.value = ""; }} />
            <Button type="button" variant="ghost" onClick={() => fileRef.current?.click()}>📎 Attach files</Button>
            <span className="hidden text-xs text-muted sm:inline">Optional: briefs, notes, data</span>
          </div>
          <Button variant="primary" disabled={start.isPending || text.trim().length < 3}>{start.isPending ? "Starting…" : "Start project"}</Button>
        </div>
      </form>
      {stage && <p role="status" className="text-center text-sm text-muted">{stage}</p>}
      <ErrorText error={start.error} />
      <div>
        <p className="mb-2 text-center text-xs text-muted">Or start from a template (optional)</p>
        <div className="flex flex-wrap justify-center gap-2">
          {templates.map((t) => (
            <button key={t.key} type="button" aria-pressed={tpl === t.key} title={t.description}
              onClick={() => { setTpl(tpl === t.key ? null : t.key); if (!text.trim() && t.example_objective) setText(t.example_objective); }}
              className={`rounded-full border px-3 py-1 text-sm ${tpl === t.key ? "border-accent bg-accent/10" : "border-line hover:bg-panel2"}`}>
              {t.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
