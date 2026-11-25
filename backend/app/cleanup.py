"""Safe identification and cleanup of synthetic test projects.

    python -m app.cleanup              # dry run: classify every project, change nothing
    python -m app.cleanup --mark       # flag CONFIRMED synthetic projects (hides them from the project list; reversible)
    python -m app.cleanup --delete --yes   # permanently delete projects already flagged AND confirmed synthetic

A project is classified as synthetic only on evidence, never on its name alone:

* ``acceptance_test`` - its id appears in the committed acceptance-test evidence under ``docs/``
  (the evidence files themselves are never touched);
* ``scripted_test``  - every agent used the scripted test provider and no real model call was recorded.

Everything else stays ``user``. Ambiguous projects are reported and left alone.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from sqlalchemy import func, select

from .config import REPO_ROOT, settings
from .db import SessionLocal
from .models import Project, ProjectAgent, UsageRecord

UUID_RX = re.compile(r'"(?:project_id|pid)"\s*:\s*"([0-9a-f-]{36})"')


def evidence_ids(root: Path = REPO_ROOT / "docs") -> dict[str, str]:
    """project id -> evidence file that references it (committed acceptance evidence)."""
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*.json")):
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for pid in UUID_RX.findall(text):
            out.setdefault(pid, str(f.relative_to(REPO_ROOT)))
    return out


def classify(db, evidence: dict[str, str]) -> list[dict]:
    rows = []
    for p in db.scalars(select(Project).order_by(Project.created_at)):
        agents = list(db.scalars(select(ProjectAgent).where(ProjectAgent.project_id == p.id)))
        real_calls = db.scalar(select(func.count()).where(UsageRecord.project_id == p.id,
                                                          UsageRecord.is_test_provider.is_(False))) or 0
        if str(p.id) in evidence:
            kind, why = "acceptance_test", f"referenced by committed evidence {evidence[str(p.id)]}"
        elif agents and all(a.provider == "scripted-test" for a in agents) and real_calls == 0:
            kind, why = "scripted_test", "every agent used the scripted test provider; no real model calls"
        elif p.origin != "user":
            kind, why = p.origin, "already flagged"
        else:
            kind, why = "user", "no evidence that this is test data"
        rows.append({"id": str(p.id), "name": p.name, "origin": p.origin, "classified": kind, "why": why,
                     "real_calls": int(real_calls), "created": p.created_at.date().isoformat()})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mark", action="store_true", help="flag confirmed synthetic projects (reversible)")
    ap.add_argument("--delete", action="store_true", help="permanently delete flagged + confirmed synthetic projects")
    ap.add_argument("--yes", action="store_true", help="required with --delete")
    args = ap.parse_args(argv)
    from . import services

    with SessionLocal() as db:
        rows = classify(db, evidence_ids())
        for r in rows:
            print(f"{r['classified']:16} {r['id']}  {r['created']}  {r['name'][:40]:40}  ({r['why']})")
        synthetic = [r for r in rows if r["classified"] != "user"]
        if args.mark:
            for r in synthetic:
                p = db.get(Project, __import__("uuid").UUID(r["id"]))
                p.origin = r["classified"]
            db.commit()
            print(f"Flagged {len(synthetic)} synthetic project(s); they are hidden from the project list.")
        if args.delete:
            if not args.yes:
                print("Refusing to delete without --yes (deletion is permanent).", file=sys.stderr)
                return 2
            doomed = [r for r in synthetic if r["origin"] == r["classified"] != "user"]
            for r in doomed:
                p = db.get(Project, __import__("uuid").UUID(r["id"]))
                services.purge_project(db, p)
            db.commit()
            for r in doomed:
                for d in (settings.uploads_dir / r["id"], settings.exports_dir / r["id"]):
                    shutil.rmtree(d, ignore_errors=True)
            print(f"Deleted {len(doomed)} flagged synthetic project(s). Committed evidence under docs/ is untouched.")
        if not (args.mark or args.delete):
            print(f"\nDry run: {len(synthetic)} synthetic, {len(rows) - len(synthetic)} user project(s). Nothing changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
