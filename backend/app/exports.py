"""Deliverable exports. An export is reported as successful only after the output file
exists on disk and passes a format-specific validation."""
from __future__ import annotations

import csv
import io
import json
import re
import uuid
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from . import services
from .config import settings
from .models import Artifact, Project, ReviewFinding

FORMATS = {"md", "json", "csv", "txt", "docx", "zip"}


class ExportError(RuntimeError):
    pass


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:80] or "export"


def _out(project: Project, name: str) -> Path:
    d = settings.exports_dir / str(project.id)
    d.mkdir(parents=True, exist_ok=True)
    return d / name


def markdown_to_docx(md: str, path: Path) -> None:
    import docx

    doc = docx.Document()
    for line in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            doc.add_heading(m.group(2), level=min(len(m.group(1)), 4))
        elif re.match(r"^\s*[-*]\s+", line):
            doc.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
        elif line.strip():
            doc.add_paragraph(line)
    doc.save(path)


def validate_file(path: Path, fmt: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise ExportError("Export file was not written")
    if fmt == "json":
        json.loads(path.read_text())
    elif fmt == "csv":
        list(csv.reader(io.StringIO(path.read_text())))
    elif fmt in ("zip", "docx"):
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            if bad:
                raise ExportError(f"Corrupt archive member {bad}")
        if fmt == "docx":
            import docx

            docx.Document(str(path))


def export_artifact(db: Session, art: Artifact, fmt: str) -> Path:
    if fmt not in FORMATS - {"zip"}:
        raise ExportError(f"Unsupported format {fmt}")
    project = db.get(Project, art.project_id)
    v = services.latest_version(db, art.id)
    if v is None:
        raise ExportError("Deliverable has no content")
    base = _slug(art.name.replace("/", "_"))
    path = _out(project, f"{base}-v{v.version}.{fmt}")
    if fmt == "docx":
        markdown_to_docx(v.content, path)
    elif fmt == "json":
        if art.artifact_type == "json":
            path.write_text(v.content)
        else:
            path.write_text(json.dumps({"name": art.name, "version": v.version, "type": art.artifact_type,
                                        "summary": v.summary, "content": v.content}, indent=2))
    elif fmt == "csv" and art.artifact_type != "csv":
        raise ExportError("Only CSV deliverables can be exported as CSV")
    else:
        path.write_text(v.content)
    validate_file(path, fmt)
    return path


def export_project(db: Session, project: Project) -> Path:
    arts = services.project_artifacts(db, project.id)
    if not arts:
        raise ExportError("There are no deliverables to export")
    path = _out(project, f"{_slug(project.name)}-deliverables-{uuid.uuid4().hex[:6]}.zip")
    manifest = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for a in arts:
            v = services.latest_version(db, a.id)
            if v is None:
                continue
            if a.artifact_type == "code":
                arc = f"source/{a.name}"
            else:
                ext = {"markdown": "md", "json": "json", "csv": "csv", "text": "txt"}[a.artifact_type]
                arc = f"{a.category}/{_slug(a.name)}.{ext}"
            z.writestr(arc, v.content)
            manifest.append({"name": a.name, "path": arc, "version": v.version, "type": a.artifact_type,
                             "acceptance": a.acceptance_status, "sha256": v.sha256, "stale": a.stale,
                             "stale_reason": a.stale_reason, "requirement_ids": v.requirement_ids,
                             "input_version_ids": v.input_version_ids})
        findings = db.query(ReviewFinding).filter(ReviewFinding.project_id == project.id).all()
        z.writestr("qa/findings.json", json.dumps([
            {"key": f.finding_key, "severity": f.severity, "status": f.status, "requirement": f.requirement_ref,
             "evidence": f.evidence, "recommendation": f.recommendation} for f in findings], indent=2))
        z.writestr("manifest.json", json.dumps({"project": project.name, "artifacts": manifest}, indent=2))
    validate_file(path, "zip")
    with zipfile.ZipFile(path) as z:
        if "manifest.json" not in z.namelist():
            raise ExportError("Manifest missing from archive")
    return path
