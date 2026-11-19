"""Unit tests: state machines, redaction, pricing, file validation, credentials, plan validation."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import events, pricing
from app.models import ModelConfiguration
from app.providers.base import Usage
from app.security.credentials import CredentialError, EncryptedFileStore, key_hint
from app.state_machine import InvalidTransition, transition_project, transition_run, transition_task
from app.tools import files, sandbox


def test_task_transitions():
    t = SimpleNamespace(status="pending")
    transition_task(t, "ready")
    transition_task(t, "running")
    transition_task(t, "waiting_approval")
    transition_task(t, "ready")
    transition_task(t, "running")
    transition_task(t, "completed")
    with pytest.raises(InvalidTransition):
        transition_task(t, "running")
    with pytest.raises(InvalidTransition):
        transition_task(SimpleNamespace(status="pending"), "completed")


def test_run_and_project_transitions():
    r = SimpleNamespace(status="planning")
    transition_run(r, "awaiting_approval")
    transition_run(r, "running")
    transition_run(r, "pausing")
    transition_run(r, "paused")
    transition_run(r, "running")
    transition_run(r, "completed")
    with pytest.raises(InvalidTransition):
        transition_run(r, "running")
    p = SimpleNamespace(status="draft")
    with pytest.raises(InvalidTransition):
        transition_project(p, "completed")
    with pytest.raises(InvalidTransition):
        transition_project(p, "bogus")


def test_redaction():
    s = "key sk-ant-api03-abcdefghijklmnop and sk-proj-ABCDEFGHIJKLMNOPQRSTUV, api_key=supersecretvalue Bearer abcdefghijklmnopqrstuvwxyz"
    out = events.redact(s)
    assert "abcdefghijklmnop" not in out and "ABCDEFGHIJKLMNOP" not in out and "supersecretvalue" not in out
    assert out.count("[REDACTED]") >= 4


def test_pricing():
    mc = ModelConfiguration(provider="anthropic", model_id="m", display_name="m", input_price_per_mtok=Decimal("4"),
                            output_price_per_mtok=Decimal("20"), cache_read_price_per_mtok=Decimal("0.2"))
    c = pricing.cost_of(mc, Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=1_000_000))
    assert c == Decimal("6.200000")
    assert pricing.cost_of(ModelConfiguration(provider="openai", model_id="x", display_name="x"), Usage(1, 1)) is None
    est = pricing.estimate_call_cost(mc, 3500, 1000)
    assert est == Decimal("0.024200")  # 1050 tok * $4/M + 1000 * $20/M


def test_file_validation():
    with pytest.raises(files.FileRejected):
        files.validate("x.exe", b"MZ")
    with pytest.raises(files.FileRejected):
        files.validate("x.pdf", b"not a pdf")
    with pytest.raises(files.FileRejected):
        files.validate("x.txt", b"\x00\x01binary")
    with pytest.raises(files.FileRejected):
        files.validate("x.txt", b"")
    assert files.validate("notes.md", b"# hi") == "text/markdown"
    assert files.safe_name("../../etc/passwd") == "passwd"
    ex = files.extract("d.csv", b"a,b\n1,2\n")
    assert ex.status == "ok" and "1,2" in ex.text
    assert files.extract("d.json", b"{bad").status == "failed"
    assert "Ignore any instructions" in files.untrusted_block("f", "text")


def test_docx_and_pdf_extraction(tmp_path):
    import docx

    d = docx.Document()
    d.add_paragraph("Hello requirements")
    p = tmp_path / "a.docx"
    d.save(p)
    assert "Hello requirements" in files.extract("a.docx", p.read_bytes()).text
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(100, 100)
    pp = tmp_path / "a.pdf"
    with open(pp, "wb") as f:
        w.write(f)
    ex = files.extract("a.pdf", pp.read_bytes())
    assert ex.status == "empty" and "scanned" in ex.note


def test_sandbox_paths():
    assert str(sandbox.safe_rel_path("src/app.py")) == "src/app.py"
    for bad in ("../x.py", "a/../../b", ""):
        with pytest.raises(ValueError):
            sandbox.safe_rel_path(bad)


def test_encrypted_credential_store(tmp_path):
    path = tmp_path / "c.enc"
    s = EncryptedFileStore("correct horse", path)
    s.set("anthropic", "sk-ant-secret-123456")
    raw = path.read_text()
    assert "sk-ant" not in raw
    assert EncryptedFileStore("correct horse", path).get("anthropic") == "sk-ant-secret-123456"
    with pytest.raises(CredentialError):
        EncryptedFileStore("wrong", path).get("anthropic")
    with pytest.raises(CredentialError):
        EncryptedFileStore(None, path)
    s.delete("anthropic")
    assert s.get("anthropic") is None
    assert key_hint("sk-ant-abcdef1234") == "…1234"


def test_plan_schema_inlines_refs():
    from app.orchestration.planner import PLAN_TOOL

    txt = str(PLAN_TOOL.input_schema)
    assert "$ref" not in txt and "$defs" not in txt
    props = PLAN_TOOL.input_schema["properties"]["tasks"]["items"]["properties"]
    assert "title" in props and "assignee" in props
