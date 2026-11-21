"""Deterministic single-agent vs multi-agent comparison from acceptance-run evidence.

Usage: python compare.py <single-dir> <multi-dir> > comparison.json
Every metric here is computed from recorded application data (usage records, tasks, events,
artifacts) - no model judgement. Subjective quality is assessed separately (blind rubric).
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def metrics(d: Path) -> dict:
    ev = json.loads((d / "evidence.json").read_text())
    subprocess.run([sys.executable, str(HERE / "check_deliverables.py"), str(d)], capture_output=True, check=False)
    chk = json.loads((d / "checklist.json").read_text())
    recs = ev["costs"]["records"]
    cr_t = ev["timing"].get("cr", 0) / 1000
    after = [r for r in recs if ts(r["created_at"]) >= cr_t] if cr_t else []
    tasks = ev["state"]["tasks"]
    latest = {}
    for v in ev["artifact_versions"]:
        if v["category"] != "plan" and (v["name"] not in latest or v["version"] > latest[v["name"]]["version"]):
            latest[v["name"]] = v
    corpus = "\n".join((d / v["file"]).read_text() for v in latest.values())
    ac = len(re.findall(r"(?im)^\s*[-*]?\s*(?:\*\*)?(given|scenario|ac[- ]?\d+)\b", corpus))
    gw = len(re.findall(r"(?is)\bgiven\b.{0,300}?\bwhen\b.{0,300}?\bthen\b", corpus))
    phone_ac = len(re.findall(r"(?is)\bgiven\b[^\n]{0,400}?phone", corpus))
    return {
        "config": ev["config"]["TEAM"],
        "agents": [f'{a["name"]} ({a["role"]}, {a["model"]})' for a in ev["team"]],
        "run_status": ev["state"]["current_run"]["status"],
        "deterministic_checks": f'{chk["passed"]}/{chk["total"]}',
        "failed_checks": [k for k, r in chk["results"].items() if not r["pass"]],
        "documents": {n: f'v{v["version"]}' for n, v in latest.items()},
        "words_delivered": len(corpus.split()),
        "acceptance_criteria_markers": ac,
        "given_when_then_scenarios": gw,
        "scenarios_covering_phone": phone_ac,
        "qa_findings": [(f["finding_key"], f["severity"], f["status"]) for f in ev["findings"]],
        "tasks": [(t["kind"], t["status"], t["title"]) for t in tasks],
        "model_calls": len(recs),
        "input_tokens": sum(r["input_tokens"] for r in recs),
        "output_tokens": sum(r["output_tokens"] for r in recs),
        "estimated_cost_usd": round(sum(r["estimated_cost_usd"] or 0 for r in recs), 4),
        "wall_time_s": round((ev["timing"]["end"] - ev["timing"]["start"]) / 1000, 1),
        "human_interventions": ev["interventions"],
        "change": {
            "calls_after_change": len(after),
            "tokens_after_change": [sum(r["input_tokens"] for r in after), sum(r["output_tokens"] for r in after)],
            "cost_after_change_usd": round(sum(r["estimated_cost_usd"] or 0 for r in after), 4),
            "impact_analysis_calls": sum(1 for r in recs if r["purpose"] == "impact_analysis"),
            "tasks_reworked": [t["title"] for t in tasks if t["kind"] == "rework" and t["title"].startswith("Rework: ")
                               and "QA findings" not in t["title"]],
            "impact_proposal": ev["cr"].get("approval", {}).get("listed"),
            "kept": ev["cr"].get("impact", {}).get("preserved"),
            "superseded": ev["cr"].get("approval", {}).get("superseded_after"),
            "delivery_gate": ev.get("gate"),
        },
    }


if __name__ == "__main__":
    out = {"single_agent": metrics(Path(sys.argv[1])), "multi_agent": metrics(Path(sys.argv[2]))}
    print(json.dumps(out, indent=2))
