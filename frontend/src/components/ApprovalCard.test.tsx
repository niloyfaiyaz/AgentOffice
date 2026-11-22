import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Agent, Approval } from "../api";
import { ApprovalCard } from "./ApprovalCard";

const agent = { id: "a1", display_name: "Bea", role: "BA", role_key: "business_analyst" } as Agent;
const base: Approval = { id: "ap1", project_id: "p1", run_id: "r1", task_id: "t1", agent_id: "a1", kind: "clarification",
  title: "Which segment first?", explanation: "Changes scope", payload: { options: ["SMB", "Enterprise"] },
  artifact_ids: [], status: "pending", created_at: "", resolved_at: null };

function renderCard(a: Approval) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}><MemoryRouter><ApprovalCard a={a} agents={[agent]} /></MemoryRouter></QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe("ApprovalCard", () => {
  it("answers a clarification with the chosen option and the CSRF header", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ ...base, status: "answered" }), { status: 200 }));
    renderCard(base);
    expect(screen.getByText("Question from the team")).toBeInTheDocument();
    expect(screen.getByText("from Bea")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "SMB" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/approvals/ap1/decide");
    expect((init.headers as Record<string, string>)["X-AgentOffice-Client"]).toBe("1");
    expect(JSON.parse(init.body as string)).toEqual({ decision: "answer", answer: "SMB" });
  });

  it("requires feedback before requesting a revision of the deliverables", () => {
    renderCard({ ...base, kind: "deliverable_acceptance", title: "Review", payload: { qa_performed: false, unresolved_findings: ["F-001"] } });
    expect(screen.getByText("No QA review")).toBeInTheDocument();
    expect(screen.getByText("1 unresolved finding(s)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Request revision" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Revision request"), { target: { value: "Shorter" } });
    expect(screen.getByRole("button", { name: "Request revision" })).toBeEnabled();
  });

  it("shows error feedback when the server rejects a decision", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "already resolved" }), { status: 400 }));
    renderCard(base);
    fireEvent.click(screen.getByRole("button", { name: "Enterprise" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already resolved");
  });

  it("pre-selects the proposed superseded requirements and lets the client override", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    renderCard({ ...base, kind: "requirement_change", title: "Confirm the impact of requirement change R-009", payload: {
      change_ref: "R-009", proposal_method: "project_manager", proposal_rationale: "Email no longer mandatory",
      candidates: [{ id: "c1", ref: "R-007", text: "Every contact must have a valid email address.", proposed: true },
                   { id: "c2", ref: "R-003", text: "Identify duplicate contacts.", proposed: false }],
      tasks: [{ id: "t1", title: "Draft PRD", status: "completed" }, { id: "t2", title: "Tech review", status: "running" }] } });
    expect(screen.getByText(/Pre-selected by the project manager/)).toBeInTheDocument();
    expect(screen.getByText("in progress — reworked after it finishes")).toBeInTheDocument();
    const r7 = screen.getByRole("checkbox", { name: /R-007/ });
    const r3 = screen.getByRole("checkbox", { name: /R-003/ });
    expect(r7).toBeChecked();
    expect(r3).not.toBeChecked();
    fireEvent.click(r3);
    fireEvent.click(screen.getByRole("checkbox", { name: /Rework “Draft PRD”/ }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ decision: "approve", task_ids: ["t1"], supersede_ids: ["c1", "c2"] });
  });

  it("defaults rework to the evidence and follows the client's supersession choice", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    renderCard({ ...base, kind: "requirement_change", title: "Confirm R-009", payload: {
      change_ref: "R-009", proposal_method: "project_manager",
      candidates: [{ id: "email", ref: "R-007", text: "Every contact must have an email.", proposed: true },
                   { id: "dup", ref: "R-003", text: "Identify duplicates.", proposed: false }],
      impact_by_candidate: { email: ["tA", "tB"], dup: ["tC"] },
      tasks: [{ id: "tA", title: "Validation rules", action: "rework", impact: "direct", reason: "implements R-007" },
              { id: "tB", title: "Import summary", action: "rework_after", impact: "downstream", reason: "uses output of “Validation rules”" },
              { id: "tC", title: "Duplicates", action: "if_selected", impact: "if_selected", reason: "only if you also replace R-003" },
              { id: "tU", title: "Legacy notes", action: "confirm", impact: "uncertain", reason: "no requirement links recorded" }],
      preserved_tasks: ["Glossary"], artifacts_at_risk: [{ id: "x", name: "rules.md", version: 1 }] } });
    expect(screen.getByRole("checkbox", { name: /^Rework “Validation rules”/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Rework “Import summary”/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Rework “Duplicates”/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^Rework “Legacy notes”/ })).not.toBeChecked();
    expect(screen.getByText("needs your confirmation")).toBeInTheDocument();
    expect(screen.getByText(/Unaffected \(kept\):/)).toBeInTheDocument();
    expect(screen.getByText(/rules.md v1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /R-003 Identify duplicates/ }));  // client also replaces R-003
    expect(screen.getByRole("checkbox", { name: /^Rework “Duplicates”/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body.task_ids.sort()).toEqual(["tA", "tB", "tC"]);
  });

  it("explains a blocked delivery and offers rework or confirmation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    renderCard({ ...base, kind: "stale_artifacts", title: "Delivery blocked: 1 deliverable(s) are not current", payload: {
      artifacts: [{ artifact_id: "a1", name: "prd.md", version: 2, reason: "implements superseded R-009 (replaced by R-021)" }] } });
    expect(screen.getByText("Delivery blocked")).toBeInTheDocument();
    expect(screen.getByText(/implements superseded R-009/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rework them" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({ decision: "approve", option: "rework" });
  });

  it("totals the estimated rework cost of the selected tasks and flags budget overrun", () => {
    const est = (usd: string | null, partial = false, basis = "current_model") => ({ usd, calls: 2, partial, basis });
    renderCard({ ...base, kind: "requirement_change", title: "Confirm the impact of R-010", payload: {
      change_ref: "R-010", candidates: [], budget_remaining_usd: "0.0500",
      tasks: [
        { id: "t1", title: "Validation rules", status: "completed", impact: "direct", action: "rework", reason: "implements R-009", estimate: est("0.0300") },
        { id: "t2", title: "Error report", status: "completed", impact: "downstream", action: "rework", reason: "uses output", estimate: est("0.0400") },
        { id: "t3", title: "Import UI", status: "running", impact: "direct", action: "rework_after", reason: "implements R-009", estimate: est(null, true, "no_usage") },
      ] } });
    const box = screen.getByLabelText("Estimated rework cost");
    // t1 + t2 + t3 are proposed; t3 has no usage yet, so the total is a lower bound and over budget.
    expect(box).toHaveTextContent("at least $0.0700 for 3 tasks");
    expect(box).toHaveTextContent("$0.0500 left in the project budget (the rework may need more budget)");
    expect(box).toHaveTextContent("1 selected task has no usable cost data");
    expect(screen.getByText(/est\. ~\$0\.0300/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Error report/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Import UI/ }));
    expect(box).toHaveTextContent("about $0.0300 for 1 task");
    expect(box).not.toHaveTextContent("may need more budget");
  });
});
