"""Deterministic scripted provider for automated end-to-end tests ONLY.

This is NOT an AI model. It follows a fixed script driven by the tools offered and the
conversation so far, which lets the test-suite exercise the real orchestration engine
(planning, approvals, clarifications, handoffs, QA rework, consolidation, exports) without
provider credentials. It is available only when AGENTOFFICE_ENABLE_TEST_PROVIDER=1, every
usage record it produces is flagged ``is_test_provider`` and it never reports a cost.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from .base import CompletionResult, ModelInfo, Provider, ToolCall, Usage

TEAM_LINE = re.compile(r"^- (?P<name>[^—\n]+?) — (?P<role>[^(\n]+?) \(model", re.M)


def _called(messages: list[dict[str, Any]]) -> list[str]:
    names = []
    for m in messages:
        if m["role"] == "assistant":
            names += [b["name"] for b in m["content"] if b["type"] == "tool_call"]
    return names


def _first_text(messages) -> str:
    for b in messages[0]["content"]:
        if b["type"] == "text":
            return b["text"]
    return ""


def _results(messages) -> list[str]:
    out = []
    for m in messages:
        if m["role"] == "user":
            out += [b.get("content", "") for b in m["content"] if b["type"] == "tool_result"]
    return out


class ScriptedProvider(Provider):
    name = "scripted-test"
    is_test_provider = True

    async def list_models(self):
        return [ModelInfo("scripted-v1", "Scripted test model (not AI)")]

    async def complete(self, *, model, system, messages, tools, max_tokens, effort=None) -> CompletionResult:
        names = {t.name for t in tools}
        if "submit_work_plan" in names:
            calls = [self._plan(_first_text(messages))]
            text = "Here is the proposed plan."
        elif "update_project_brief" in names:
            calls = [self._brief(_first_text(messages))]
            text = ""
        elif "reply_to_client" in names:
            calls = [self._reply(_first_text(messages))]
            text = ""
        elif not names:
            text, calls = "Scripted reply (test provider, not AI): message received.", []
        else:
            text, calls = self._task_step(messages, names)
        in_chars = len(system) + len(json.dumps(messages))
        neutral = ([{"type": "text", "text": text}] if text else []) + [
            {"type": "tool_call", "id": c.id, "name": c.name, "input": c.input} for c in calls]
        return CompletionResult(
            text=text, tool_calls=calls, stop_reason="tool_use" if calls else "end",
            usage=Usage(input_tokens=in_chars // 4, output_tokens=max(len(json.dumps(neutral)) // 4, 1)),
            assistant_message={"role": "assistant", "content": neutral, "raw": {"provider": self.name, "model": model}},
            served_model=model,
        )

    @staticmethod
    def _id() -> str:
        return f"call_{uuid.uuid4().hex[:16]}"

    def _plan(self, brief: str) -> ToolCall:
        team = [(m["name"].strip(), m["role"].strip()) for m in TEAM_LINE.finditer(brief)]
        req_refs = re.findall(r"^- (R-\d{3}) \[", brief.split("NO LONGER VALID")[0], re.M) or ["R-001"]
        specialists = [(n, r) for n, r in team if "Project Manager" not in r and "QA" not in r][:3]
        if not specialists:
            specialists = team[:1]
        tasks = []
        for i, (n, r) in enumerate(specialists):
            key = f"T{i + 1}"
            title = (f"Discovery: requirements for the {r.lower()} work" if i == 0 else f"{r} deliverable")
            tasks.append({"key": key, "title": title, "objective": f"Produce the {r.lower()} contribution to the project.",
                          "assignee": n, "depends_on": [] if i == 0 else ["T1"], "expected_output_type": "markdown",
                          "acceptance_criteria": [f"Covers the {r.lower()} perspective", "States assumptions"],
                          "requirement_refs": req_refs if i == 0 else req_refs[:1]})
        plan = {"summary": "Scripted test plan.", "scope": "Deliver the requested documents.",
                "deliverables": [f"{r} document" for _, r in specialists],
                "tasks": tasks, "acceptance_criteria": ["Each deliverable addresses the objective"],
                "assumptions": ["Scripted test run"], "risks": ["None (test)"], "tool_requirements": [],
                "clarification_questions": []}
        return ToolCall(self._id(), "submit_work_plan", plan)

    def _brief(self, ctx: str) -> ToolCall:
        """Discovery: round 1 asks two scripted questions; round 2 (after an answer) is ready."""
        convo = ctx.split("Conversation so far:", 1)[-1].split("Current brief", 1)[0]
        client = [l[len("CLIENT: "):] for l in convo.splitlines() if l.startswith("CLIENT: ")]
        idea = client[0] if client else "a project"
        answered = len(client) > 1
        words = re.findall(r"[A-Za-z0-9]+", idea)
        software = bool(re.search(r"\b(app|web|website|software|prototype|api|tool|platform)\b", idea, re.I))
        team = ([{"role_key": "software_architect", "responsibility": "Architecture and technical design",
                  "reason": "The idea is a software product."},
                 {"role_key": "developer", "responsibility": "Build the prototype", "reason": "Working software is a deliverable."},
                 {"role_key": "qa_reviewer", "responsibility": "Review deliverables against acceptance criteria",
                  "reason": "Independent QA."}] if software else
                [{"role_key": "research_analyst", "responsibility": "Research and analysis", "reason": "Research-led project."},
                 {"role_key": "technical_writer", "responsibility": "Write the report", "reason": "A written deliverable."},
                 {"role_key": "qa_reviewer", "responsibility": "Review the report", "reason": "Independent review."}])
        out = {
            "message": ("Scripted test provider (not AI): " + ("Thanks, that's enough to draft the plan." if answered else
                        "I've drafted a brief from your description. Two questions before I plan.")),
            "name": " ".join(w.capitalize() for w in words[:4]) or "Scripted project",
            "project_type": "software" if software else "research",
            "objective": idea.split(".")[0][:300], "objective_basis": "client_stated",
            "audience": "Friends planning a trip together" if "friend" in idea.lower() else "General users",
            "audience_basis": "ai_proposed",
            "scope_in": [{"text": "Core user journey described by the client", "basis": "client_stated"}],
            "scope_out": [{"text": "Payments and bookings", "basis": "ai_proposed"}],
            "deliverables": [{"text": "Requirements document", "basis": "ai_proposed"},
                             {"text": "Technical design" if software else "Research report", "basis": "ai_proposed"}],
            "requirements": [{"text": s.strip(), "basis": "client_stated"} for s in re.split(r"[,.;]| and ", idea)
                             if len(s.strip().split()) >= 2][:4],
            "constraints": [], "success_criteria": [{"text": "The client can review every deliverable", "basis": "ai_proposed"}],
            "assumptions": ["Web first; mobile later"] if software else ["Public sources only"],
            "open_questions": [],
            "questions": [] if answered else [
                {"question": "Who will use it first?", "why": "Decides the intended audience and scope.",
                 "options": ["Just my friends", "Anyone", "I don't know"]},
                {"question": "Do you need a working prototype or only documents?", "why": "Changes the deliverables.",
                 "options": ["Prototype", "Documents only"]}],
            "recommended_team": team, "ready": answered,
        }
        if answered:
            out["requirements"].append({"text": f"Client answer: {client[-1][:200]}", "basis": "client_stated"})
        return ToolCall(self._id(), "update_project_brief", out)

    def _reply(self, ctx: str) -> ToolCall:
        msg = ctx.rsplit("Client message:", 1)[-1].strip().lower()
        intent = ("requirement_change" if re.search(r"\b(instead|no longer|change the requirement|must now)\b", msg)
                  else "scope_change" if re.search(r"\b(also add|add a new deliverable|expand)\b", msg)
                  else "question")
        return ToolCall(self._id(), "reply_to_client", {
            "reply": "Scripted reply (test provider, not AI): noted.", "detected_intent": intent,
            "rationale": "scripted keyword rule"})

    def _task_step(self, messages, names) -> tuple[str, list[ToolCall]]:
        brief = _first_text(messages)
        done = _called(messages)
        title = re.search(r"^# Your task: (.+)$", brief, re.M)
        title = title.group(1).strip() if title else "Task"
        results = _results(messages)
        # QA reviewer
        if "submit_review" in names:
            if "submit_review" not in done:
                earlier = re.findall(r"^- (F-\d{3}) \[", brief, re.M)
                first_art = re.search(r"^- “(.+?)” v\d+", brief.split("# Deliverables under review", 1)[-1], re.M)
                if earlier:
                    return "Re-review complete.", [ToolCall(self._id(), "submit_review", {
                        "verdict": "pass", "summary": "Earlier findings are fixed.", "findings": [],
                        "resolved_finding_keys": earlier})]
                return "Review complete.", [ToolCall(self._id(), "submit_review", {
                    "verdict": "revise", "summary": "One major gap.",
                    "findings": [{"severity": "major", "artifact": first_art.group(1) if first_art else "",
                                  "requirement": "Each deliverable addresses the objective",
                                  "evidence": "The document does not list open questions.",
                                  "recommendation": "Add an 'Open questions' section."}]})]
            return "", [ToolCall(self._id(), "complete_task", {"summary": "Review submitted."})]
        # Clarification on discovery tasks
        if "ask_client" in names and title.startswith("Discovery") and "ask_client" not in done:
            return "I need one decision.", [ToolCall(self._id(), "ask_client", {
                "question": "Which customer segment should we prioritize first?",
                "options": ["SMB", "Enterprise"], "context": "This changes the requirements scope."})]
        answer = next((r for r in results if r.startswith("Client answer:")), "")
        if "write_artifact" in names and "write_artifact" not in done:
            if title.startswith("Rework"):
                target = re.search(r"^- “(.+?)” v\d+", brief.split("# Deliverables to work on", 1)[-1], re.M)
                name = target.group(1) if target else title
                return "", [ToolCall(self._id(), "write_artifact", {
                    "name": name, "artifact_type": "markdown",
                    "content": f"# {name}\n\nRevised content.\n\n## Open questions\n- None remaining (scripted).\n",
                    "summary": "Revised to address QA findings."})]
            name = "Final Delivery Summary" if title.startswith("Consolidate") else title.replace("Discovery: ", "")
            body = f"# {name}\n\nScripted test content for: {title}.\n"
            if answer:
                body += f"\nClient decision: {answer.replace('Client answer: ', '')}\n"
            return "", [ToolCall(self._id(), "write_artifact", {"name": name, "artifact_type": "markdown",
                                                               "content": body, "summary": f"Scripted output for {title}."})]
        return "", [ToolCall(self._id(), "complete_task", {"summary": f"Finished {title} (scripted)."})]
