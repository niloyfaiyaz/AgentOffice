"""Built-in catalog: default agent roles, project templates, tool permissions and model list."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentDefinition, ModelConfiguration, ProjectTemplate, ToolPermission

DEFAULT_MODEL = ("anthropic", "claude-opus-5-5")

# Permission keys shown to users as "authorized responsibilities".
TOOL_PERMISSIONS: dict[str, dict] = {
    "file_read": {"label": "Read project reference files", "consequential": False},
    "artifact_read": {"label": "Read team deliverables", "consequential": False},
    "artifact_write": {"label": "Write deliverables", "consequential": False},
    "data_analysis": {"label": "Analyze structured data (CSV/JSON)", "consequential": False},
    "delegation": {"label": "Delegate work to teammates", "consequential": False},
    "client_questions": {"label": "Ask the client questions", "consequential": False},
    "code_execution": {"label": "Run code in the sandbox", "consequential": True},
    "test_execution": {"label": "Run automated tests in the sandbox", "consequential": True},
    "web_research": {"label": "Search the web (Anthropic models only)", "consequential": True},
}

BASE = ["file_read", "artifact_read", "artifact_write", "client_questions"]

DEFAULT_ROLES: list[dict] = [
    {
        "role_key": "project_manager", "name": "Pat", "role": "Project Manager",
        "description": "Scopes the work, plans tasks, delegates to specialists and consolidates the final delivery.",
        "instructions": (
            "You are the project manager of an AI consulting team. You turn the client's objective into a clear, "
            "minimal work plan, assign each task to the teammate whose specialty fits, and consolidate results. "
            "Never expand the approved scope. Prefer fewer, well-defined tasks over many small ones."
        ),
        "tools": BASE + ["delegation"],
        "avatar": {"skin": "#f1c27d", "hair": "#3b2a1a", "shirt": "#2f6fdf", "pants": "#2b2d42", "accent": "#ffd166"},
    },
    {
        "role_key": "business_analyst", "name": "Bea", "role": "Product Manager / Business Analyst",
        "description": "Elicits requirements, user needs and priorities; writes requirements, user stories and acceptance criteria.",
        "instructions": (
            "You are a senior product manager and business analyst. Write precise, testable requirements, user "
            "stories with acceptance criteria, and explicit assumptions and open questions. Separate facts given by "
            "the client from your own assumptions."
        ),
        "tools": BASE + ["data_analysis", "delegation"],
        "avatar": {"skin": "#e0ac69", "hair": "#a0522d", "shirt": "#2a9d8f", "pants": "#264653", "accent": "#e9c46a"},
    },
    {
        "role_key": "research_analyst", "name": "Rhea", "role": "Research Analyst",
        "description": "Researches topics and synthesizes evidence from supplied documents (and the web when authorized).",
        "instructions": (
            "You are a research analyst. Synthesize evidence carefully. Always distinguish evidence (with a source "
            "reference: file name, artifact, or URL) from inference. Flag claims you cannot support. If no web tool "
            "is available, say so instead of implying live research."
        ),
        "tools": BASE + ["data_analysis", "web_research"],
        "avatar": {"skin": "#c68642", "hair": "#111111", "shirt": "#8d5cf6", "pants": "#3a2e5c", "accent": "#f4a261"},
    },
    {
        "role_key": "software_architect", "name": "Archie", "role": "Software Architect",
        "description": "Produces technical designs, constraints, interfaces and implementation plans.",
        "instructions": (
            "You are a pragmatic software architect. Produce clear architecture: components, data flow, interfaces, "
            "technology choices with rationale, risks and constraints. Avoid unnecessary complexity."
        ),
        "tools": BASE + ["delegation"],
        "avatar": {"skin": "#ffdbac", "hair": "#6b4423", "shirt": "#e76f51", "pants": "#3d405b", "accent": "#81b29a"},
    },
    {
        "role_key": "developer", "name": "Dev", "role": "Developer",
        "description": "Implements source code and technical deliverables, with tests.",
        "instructions": (
            "You are a careful software developer. Write complete, runnable code as code artifacts with file paths "
            "(e.g. src/app.py, tests/test_app.py). Include tests. When the sandbox is available, run your tests and "
            "report the real results; never claim tests passed without running them."
        ),
        "tools": BASE + ["code_execution", "test_execution"],
        "avatar": {"skin": "#8d5524", "hair": "#222222", "shirt": "#3a86ff", "pants": "#1d3557", "accent": "#06d6a0"},
    },
    {
        "role_key": "qa_reviewer", "name": "Quinn", "role": "QA Reviewer",
        "description": "Reviews deliverables against acceptance criteria, records findings and requests targeted rework.",
        "instructions": (
            "You are a rigorous QA reviewer. Check each deliverable against the approved acceptance criteria and "
            "requirements. Record specific findings with evidence (quote or locate the problem) and a recommended "
            "correction. Do not nitpick: request rework only for issues that matter. Your approval is a review "
            "opinion, not proof of correctness."
        ),
        "tools": ["file_read", "artifact_read", "test_execution", "client_questions"],
        "avatar": {"skin": "#f1c27d", "hair": "#d4a017", "shirt": "#ef476f", "pants": "#2b2d42", "accent": "#118ab2"},
    },
    {
        "role_key": "technical_writer", "name": "Tess", "role": "Technical Writer",
        "description": "Turns team output into clear documentation and reports.",
        "instructions": (
            "You are a technical writer. Produce well-structured, readable documents with headings, summaries and "
            "consistent terminology. Do not introduce facts that are not in your inputs."
        ),
        "tools": BASE,
        "avatar": {"skin": "#e0ac69", "hair": "#5a3825", "shirt": "#ffb703", "pants": "#023047", "accent": "#fb8500"},
    },
    {
        "role_key": "data_analyst", "name": "Dana", "role": "Data Analyst",
        "description": "Interprets structured data and produces analyses with clearly stated methods.",
        "instructions": (
            "You are a data analyst. Use the data analysis tool to compute figures rather than estimating them. "
            "State methods, assumptions and limitations."
        ),
        "tools": BASE + ["data_analysis", "code_execution"],
        "avatar": {"skin": "#c68642", "hair": "#2e1a0f", "shirt": "#06d6a0", "pants": "#073b4c", "accent": "#ffd166"},
    },
]

TEMPLATES: list[dict] = [
    {
        "key": "product_requirements", "name": "Product Requirements",
        "description": "A product requirements document with user stories, acceptance criteria and dependencies.",
        "recommended_roles": ["project_manager", "business_analyst", "software_architect", "qa_reviewer"],
        "deliverables": ["Product requirements document", "User stories", "Acceptance criteria", "Dependencies", "Open questions"],
        "example_objective": "Build a product requirements document and implementation plan for an AI-powered customer onboarding assistant.",
    },
    {
        "key": "competitive_analysis", "name": "Competitive Analysis",
        "description": "Competitor comparison with an evidence matrix, differentiation opportunities and risks.",
        "recommended_roles": ["project_manager", "research_analyst", "business_analyst", "qa_reviewer"],
        "deliverables": ["Competitor comparison", "Evidence matrix", "Differentiation opportunities", "Risks and recommendations"],
        "example_objective": "Compare the leading meeting-notes AI tools and identify where a new entrant could differentiate.",
    },
    {
        "key": "software_prototype", "name": "Software Prototype",
        "description": "Architecture, source code, tests, setup instructions and known limitations.",
        "recommended_roles": ["project_manager", "software_architect", "developer", "qa_reviewer"],
        "deliverables": ["Architecture", "Source code", "Tests", "Setup instructions", "Known limitations"],
        "example_objective": "Build a small Python command-line tool that converts CSV files to Markdown tables, with tests.",
    },
    {
        "key": "business_process", "name": "Business Process Analysis",
        "description": "Current-state analysis, proposed future state, requirements, risks and implementation considerations.",
        "recommended_roles": ["project_manager", "business_analyst", "research_analyst", "technical_writer"],
        "deliverables": ["Current-state analysis", "Proposed future state", "Requirements", "Risks", "Implementation considerations"],
        "example_objective": "Analyze our invoice approval process and propose an improved future state.",
    },
    {
        "key": "custom", "name": "Custom Project",
        "description": "Describe any objective. The Project Manager proposes a team, tasks and deliverables.",
        "recommended_roles": ["project_manager"],
        "deliverables": [],
        "example_objective": "",
    },
]

ANTHROPIC_PRICING_SOURCE = "Anthropic published list price (cached 2026-11-03). Verify at anthropic.com/pricing."
# (model_id, display, input, output, cache_read, context, max_output)
ANTHROPIC_MODELS = [
    ("claude-opus-5-5", "Claude Opus 5.5", "4.00", "20.00", "0.20", 1_000_000, 128_000),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "2.00", "10.00", "0.10", 1_000_000, 128_000),
    ("claude-haiku-5-5", "Claude Haiku 5.5", "0.10", "0.50", None, 1_000_000, 128_000),
    ("claude-fable-5-2", "Claude Fable 5.2", "8.00", "40.00", "0.20", 1_000_000, 128_000),
    ("claude-opus-5", "Claude Opus 5", "5.00", "25.00", None, 1_000_000, 128_000),
    ("claude-sonnet-5", "Claude Sonnet 5", "2.00", "10.00", None, 1_000_000, 128_000),
    ("claude-haiku-4-5", "Claude Haiku 4.5", "1.00", "5.00", None, 200_000, 64_000),
]
OPENAI_PRICING_SOURCE = ("OpenAI published standard price (developers.openai.com/api/docs/pricing, checked 2026-11-19). "
                         "Verify before relying on it.")
# (model_id, display, input, cached input, output) - verified on the date above. Other OpenAI
# models are discovered from the user's key and left unpriced until the user enters prices.
OPENAI_MODELS = [
    ("gpt-5.5", "GPT-5.5", "5.00", "0.50", "30.00"),
    ("gpt-5.4", "GPT-5.4", "2.50", "0.25", "15.00"),
    ("gpt-5.4-mini", "GPT-5.4 mini", "0.75", "0.075", "4.50"),
    ("gpt-5.4-nano", "GPT-5.4 nano", "0.20", "0.02", "1.25"),
    ("gpt-5", "GPT-5", "1.25", "0.125", "10.00"),
    ("gpt-5-mini", "GPT-5 mini", "0.25", "0.025", "2.00"),
]

# Heuristic labels (NOT benchmarks): relative price tier derived only from configured prices.
def cost_tier(input_price: Decimal | None, output_price: Decimal | None) -> str:
    if input_price is None or output_price is None:
        return "unpriced"
    blended = input_price + output_price
    if blended < 3:
        return "$"
    if blended < 15:
        return "$$"
    if blended < 30:
        return "$$$"
    return "$$$$"


def seed(db: Session) -> None:
    """Idempotently insert the built-in catalog."""
    for t in TEMPLATES:
        existing = db.scalar(select(ProjectTemplate).where(ProjectTemplate.key == t["key"]))
        if existing is None:
            db.add(ProjectTemplate(is_builtin=True, **t))
    for (mid, disp, i, o, cr, ctx, mx) in ANTHROPIC_MODELS:
        if db.scalar(select(ModelConfiguration).where(ModelConfiguration.provider == "anthropic",
                                                      ModelConfiguration.model_id == mid)) is None:
            db.add(ModelConfiguration(
                provider="anthropic", model_id=mid, display_name=disp,
                input_price_per_mtok=Decimal(i), output_price_per_mtok=Decimal(o),
                cache_read_price_per_mtok=Decimal(cr) if cr else None,
                pricing_source=ANTHROPIC_PRICING_SOURCE, context_window=ctx, max_output_tokens=mx,
            ))
    for (mid, disp, i, cr, o) in OPENAI_MODELS:
        mc = db.scalar(select(ModelConfiguration).where(ModelConfiguration.provider == "openai",
                                                        ModelConfiguration.model_id == mid))
        if mc is None:
            mc = ModelConfiguration(provider="openai", model_id=mid, display_name=disp)
            db.add(mc)
        if mc.input_price_per_mtok is None:  # never overwrite prices the user entered
            mc.display_name = disp
            mc.input_price_per_mtok, mc.cache_read_price_per_mtok = Decimal(i), Decimal(cr)
            mc.output_price_per_mtok, mc.pricing_source = Decimal(o), OPENAI_PRICING_SOURCE
    for r in DEFAULT_ROLES:
        if db.scalar(select(AgentDefinition).where(AgentDefinition.is_builtin.is_(True),
                                                   AgentDefinition.role_key == r["role_key"])) is None:
            d = AgentDefinition(
                name=r["name"], role=r["role"], role_key=r["role_key"], description=r["description"],
                instructions=r["instructions"], avatar=r["avatar"], provider=DEFAULT_MODEL[0],
                model_id=DEFAULT_MODEL[1], is_builtin=True,
            )
            db.add(d)
            db.flush()
            for key in r["tools"]:
                db.add(ToolPermission(agent_definition_id=d.id, tool_key=key, allowed=True))
    db.flush()
