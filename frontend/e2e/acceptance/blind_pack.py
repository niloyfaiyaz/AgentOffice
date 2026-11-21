"""Build blinded evaluation packages from two acceptance runs.

Usage: python blind_pack.py <single-dir> <multi-dir> <out-dir> [seed]
Writes <out-dir>/package_X.md, package_Y.md (latest version of every final deliverable,
with agent names, role titles and configuration hints removed) and a SEALED mapping file
(mapping.sealed.json) that the evaluator must not read until scoring is complete.
"""
import json
import random
import re
import sys
from pathlib import Path

REDACT = [r"\bPat\b", r"\bBea\b", r"\bArchie\b", r"\bQuinn\b", r"Project Manager", r"Business Analyst",
          r"Technical Reviewer", r"QA Reviewer", r"Reviewer:.*", r"single[- ]agent", r"multi[- ]agent",
          r"\bmodel openai/[\w.-]+", r"QA Review Report", r"QA review", r"\bQA\b"]


def latest_docs(d: Path) -> dict[str, str]:
    """Current, model-written product documents only. Excluded because they reveal the configuration
    rather than its quality: stale/historical versions, system-generated summaries, and QA reports."""
    ev = json.loads((d / "evidence.json").read_text())
    stale = {a["name"] for a in ev["artifacts"] if a["stale"]}
    latest = {}
    for v in ev["artifact_versions"]:
        if v["category"] in ("plan", "summary") or v["name"] in stale or re.search(r"qa.review.report", v["name"], re.I):
            continue
        if v["name"] not in latest or v["version"] > latest[v["name"]]["version"]:
            latest[v["name"]] = v
    return {n: (d / v["file"]).read_text() for n, v in latest.items()}


def scrub(text: str) -> str:
    for p in REDACT:
        text = re.sub(p, "[redacted]", text, flags=re.I)
    return text


def package(docs: dict[str, str]) -> str:
    parts = []
    for i, (name, body) in enumerate(sorted(docs.items()), 1):
        parts.append(f"\n\n=== Document {i} ===\n\n{scrub(body)}")
    return "".join(parts)


if __name__ == "__main__":
    single, multi, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    rng = random.Random(int(sys.argv[4]) if len(sys.argv) > 4 else None)
    out.mkdir(parents=True, exist_ok=True)
    labels = ["X", "Y"]
    rng.shuffle(labels)
    mapping = {labels[0]: "single_agent", labels[1]: "multi_agent"}
    (out / f"package_{labels[0]}.md").write_text(package(latest_docs(single)))
    (out / f"package_{labels[1]}.md").write_text(package(latest_docs(multi)))
    sealed = Path(sys.argv[5]) if len(sys.argv) > 5 else out / "mapping.sealed.json"
    sealed.parent.mkdir(parents=True, exist_ok=True)
    sealed.write_text(json.dumps(mapping))
    print("packages written:", sorted(p.name for p in out.glob("package_*.md")))
