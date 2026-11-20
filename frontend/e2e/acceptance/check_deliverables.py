"""Deterministic acceptance checklist for the CSV Import Assistant deliverables.

Reads evidence.json + artifacts/ written by run-acceptance.mjs and checks the LATEST version of
every final deliverable (independently of the QA agent's opinion). Writes checklist.json.
Usage: python check_deliverables.py <acceptance-dir>
"""
import json
import re
import sys
from pathlib import Path

out = Path(sys.argv[1])
ev = json.loads((out / "evidence.json").read_text())

latest: dict[str, dict] = {}
for v in ev["artifact_versions"]:
    if v["category"] == "plan":
        continue
    if v["name"] not in latest or v["version"] > latest[v["name"]]["version"]:
        latest[v["name"]] = v
docs = {n: (out / v["file"]).read_text() for n, v in latest.items()}
corpus = "\n\n".join(docs.values()).lower()

CHECKS = {
    "CSV upload requirements": [r"upload", r"csv"],
    "Record preview behavior": [r"preview"],
    "Duplicate handling": [r"duplicat"],
    "Row-specific error messaging": [r"row[- ]?(level|specific|number)|per[- ]row|row \d|row-by-row|each row"],
    "Import confirmation behavior": [r"confirm"],
    "Import summary behavior": [r"summary"],
    "Updated email-or-phone validation": [r"phone"],
    "Rejection only when both contact methods absent/invalid": [r"(both|neither|either)[^.\n]{0,80}(email|phone)|(email|phone)[^.\n]{0,80}(both|neither|either)"],
    "User stories present": [r"as an? (admin|administrator)"],
    "Acceptance criteria (given/when/then or criteria lists)": [r"acceptance criteria|given .{0,80} when .{0,80} then"],
    "Valid and invalid record coverage": [r"invalid", r"valid"],
    "Technical assumptions": [r"assum"],
    "Open questions": [r"open question"],
    "Traceable QA findings (F-xxx ids)": [r"\bf-\d{3}\b"],
}
results = {}
for name, pats in CHECKS.items():
    ok = all(re.search(p, corpus) for p in pats)
    where = [n for n, d in docs.items() if all(re.search(p, d.lower()) for p in pats)]
    results[name] = {"pass": ok, "found_in": where}

# Stale-requirement check: statements that email is always mandatory, per sentence/line.
STALE = re.compile(r"(every|each|all)\s+(contact|row|record)s?[^.\n]{0,40}\b(must|shall|needs? to|is required to)\b[^.\n]{0,30}\bemail"
                   r"|email[^.\n]{0,25}\b(is|are)\s+(always\s+)?(mandatory|required)\b"
                   r"|rows? (with|that have) (a )?(missing|invalid) email[^.\n]{0,30}(must be|are|will be) rejected", re.I)
stale_hits = []
for n, d in docs.items():
    for line in re.split(r"(?<=[.\n])", d):
        if STALE.search(line):
            ctx = line.strip()
            # A line that mentions phone as the alternative is consistent with CR-001.
            if "phone" in ctx.lower():
                continue
            stale_hits.append({"artifact": n, "text": ctx[:300]})
results["No deliverable claims email is always mandatory"] = {"pass": not stale_hits, "violations": stale_hits}

summary = {"documents_checked": {n: f'v{v["version"]}' for n, v in latest.items()},
           "passed": sum(r["pass"] for r in results.values()), "total": len(results), "results": results}
(out / "checklist.json").write_text(json.dumps(summary, indent=2))
for k, r in results.items():
    print(("PASS " if r["pass"] else "FAIL ") + k + ("" if r["pass"] else f"  -> {r.get('violations') or 'not found'}"))
print(f"{summary['passed']}/{summary['total']} checks passed on {len(docs)} final documents")
