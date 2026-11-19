import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, type Project, type Template } from "../api";
import { FilesPanel } from "../components/FilesPanel";
import { TeamEditor } from "../components/TeamEditor";
import { useBootstrap, useProjectState } from "../hooks";
import { Button, Card, ErrorText, Field, inputCls } from "../ui";

export function NewProjectPage() {
  const [params] = useSearchParams();
  const boot = useBootstrap();
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  const [project, setProject] = useState<Project | null>(null);
  const [tpl, setTpl] = useState<string>(params.get("template") ?? "product_requirements");
  const template = boot.data?.templates.find((t) => t.key === tpl);
  const [f, setF] = useState({ name: "", objective: "", description: "", deliverables: "", constraints: "", success_criteria: "", deadline: "", budget_usd: "" });

  const pickTemplate = (t: Template) => {
    setTpl(t.key);
    setF((x) => ({ ...x, deliverables: t.deliverables.join("\n"), objective: x.objective || "" }));
  };
  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", {
      name: f.name, objective: f.objective, description: f.description, constraints: f.constraints,
      success_criteria: f.success_criteria, deadline: f.deadline || null, template_key: tpl,
      deliverables: f.deliverables.split("\n").map((s) => s.trim()).filter(Boolean),
      budget_usd: f.budget_usd === "" ? null : Number(f.budget_usd),
    }),
    onSuccess: (p) => { setProject(p); setStep(2); },
  });
  const hints = useQuery({ queryKey: ["intake", project?.id], enabled: !!project,
    queryFn: () => api.get<{ hints: { field: string; question: string }[]; note: string }>(`/projects/${project!.id}/intake-check`) });
  const state = useProjectState(project?.id);

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Start a new project</h1>
        <ol className="mt-2 flex gap-4 text-sm" aria-label="Steps">
          {["Brief", "Reference material", "Recruit the team"].map((s, i) => (
            <li key={s} aria-current={step === i + 1 ? "step" : undefined} className={step === i + 1 ? "font-semibold text-accent" : "text-muted"}>{i + 1}. {s}</li>
          ))}
        </ol>
      </div>

      {step === 1 && (
        <>
          <Card title="Choose a starting point">
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {boot.data?.templates.map((t) => (
                <button key={t.key} onClick={() => pickTemplate(t)} aria-pressed={tpl === t.key}
                  className={`rounded-md border p-3 text-left text-sm ${tpl === t.key ? "border-accent bg-accent/10" : "border-line hover:bg-panel2"}`}>
                  <div className="font-medium">{t.name}</div><div className="text-xs text-muted">{t.description}</div>
                </button>
              ))}
            </div>
          </Card>
          <Card title="Describe the outcome you want">
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
              <Field label="Project name"><input required className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
              <Field label="Objective" hint={template?.example_objective ? `Example: ${template.example_objective}` : "What should the team achieve?"}>
                <textarea required className={`${inputCls} h-24`} value={f.objective} onChange={(e) => setF({ ...f, objective: e.target.value })} />
              </Field>
              <Field label="Background (optional)"><textarea className={`${inputCls} h-16`} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Desired deliverables" hint="One per line"><textarea className={`${inputCls} h-24`} value={f.deliverables} onChange={(e) => setF({ ...f, deliverables: e.target.value })} /></Field>
                <Field label="Success criteria"><textarea className={`${inputCls} h-24`} value={f.success_criteria} onChange={(e) => setF({ ...f, success_criteria: e.target.value })} /></Field>
              </div>
              <Field label="Constraints"><textarea className={`${inputCls} h-16`} value={f.constraints} onChange={(e) => setF({ ...f, constraints: e.target.value })} /></Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Deadline (optional)"><input type="date" className={inputCls} value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
                <Field label="Budget in USD (optional)" hint="Enforced by AgentOffice from estimates; not a provider billing cap.">
                  <input inputMode="decimal" className={inputCls} value={f.budget_usd} onChange={(e) => setF({ ...f, budget_usd: e.target.value })} />
                </Field>
              </div>
              <ErrorText error={create.error} />
              <div className="flex justify-end"><Button variant="primary" disabled={create.isPending}>Continue</Button></div>
            </form>
          </Card>
        </>
      )}

      {step === 2 && project && (
        <>
          <FilesPanel pid={project.id} />
          {!!hints.data?.hints.length && (
            <Card title="Anything missing?">
              <p className="mb-2 text-sm text-muted">{hints.data.note}</p>
              <ul className="list-disc space-y-1 pl-5 text-sm">{hints.data.hints.map((h) => <li key={h.field}>{h.question}</li>)}</ul>
              <p className="mt-2 text-xs text-muted">You can edit these on the project page at any time.</p>
            </Card>
          )}
          <div className="flex justify-end"><Button variant="primary" onClick={() => setStep(3)}>Continue to team</Button></div>
        </>
      )}

      {step === 3 && project && (
        <>
          <TeamEditor pid={project.id} agents={state.data?.agents ?? []} />
          <div className="flex justify-end">
            <Button variant="primary" disabled={!state.data?.agents.some((a) => a.is_orchestrator)} onClick={() => nav(`/projects/${project.id}`)}>
              Go to project
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
