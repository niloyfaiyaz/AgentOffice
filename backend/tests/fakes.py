"""Programmable fake provider for MOCKED-PROVIDER tests."""
import asyncio
import json
import re
import uuid
from typing import Callable

from app.providers.base import CompletionResult, ModelInfo, Provider, ProviderError, ToolCall, Usage


def call(_tool, **args):
    return ToolCall(f"call_{uuid.uuid4().hex[:10]}", _tool, args)


class FakeProvider(Provider):
    name = "scripted-test"
    is_test_provider = True

    def __init__(self, policy: Callable, *, test_provider=True, delay: float = 0.0):
        self.policy = policy
        self.is_test_provider = test_provider
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def list_models(self):
        return [ModelInfo("scripted-v1", "fake")]

    async def complete(self, *, model, system, messages, tools, max_tokens, effort=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            first = next(b["text"] for b in messages[0]["content"] if b["type"] == "text")
            done = [b["name"] for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_call"]
            results = [b for m in messages if m["role"] == "user" for b in m["content"] if b["type"] == "tool_result"]
            ctx = {"system": system, "brief": first, "done": done, "results": results,
                   "tools": {t.name for t in tools}, "title": (re.search(r"^# Your task: (.+)$", first, re.M) or [None, ""])[1]}
            self.calls.append(ctx)
            out = self.policy(ctx)
            if isinstance(out, ProviderError):
                raise out
            calls = out if isinstance(out, list) else []
            text = out if isinstance(out, str) else ""
            neutral = ([{"type": "text", "text": text}] if text else []) + [
                {"type": "tool_call", "id": c.id, "name": c.name, "input": c.input} for c in calls]
            return CompletionResult(text=text, tool_calls=calls, stop_reason="tool_use" if calls else "end",
                                    usage=Usage(input_tokens=1000, output_tokens=200),
                                    assistant_message={"role": "assistant", "content": neutral,
                                                       "raw": {"provider": self.name, "model": model}},
                                    served_model=model)
        finally:
            self.active -= 1


def plan_call(tasks, tool_requirements=()):
    return call("submit_work_plan", summary="s", scope="scope", deliverables=["d"], tasks=tasks,
                acceptance_criteria=["ok"], tool_requirements=list(tool_requirements))


def simple_worker(ctx):
    """Write one artifact then complete."""
    if "write_artifact" in ctx["tools"] and "write_artifact" not in ctx["done"]:
        return [call("write_artifact", name=ctx["title"] or "out", artifact_type="markdown", content=f"# {ctx['title']}",
                     summary="done")]
    if "submit_review" in ctx["tools"] and "submit_review" not in ctx["done"]:
        return [call("submit_review", verdict="pass", summary="fine", findings=[])]
    return [call("complete_task", summary=f"finished {ctx['title']}")]
