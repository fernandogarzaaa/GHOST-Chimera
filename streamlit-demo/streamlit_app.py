"""Ghost Chimera hackathon landing app.

Deploy target: Streamlit Community Cloud.
This safe judge-facing demo explains and simulates the Ghost-path workflow
without exposing a local machine, shell, email, desktop, or private repository.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class GhostPath:
    name: str
    description: str
    learns_from: tuple[str, ...]
    operates: tuple[str, ...]
    outcomes: tuple[str, ...]
    evals: tuple[str, ...]


PATHS = {
    "Manager Operator": GhostPath(
        name="Manager Operator",
        description="Coordinates decisions, follow-ups, summaries, plans, and team operations.",
        learns_from=("email exports", "calendar exports", "team docs", "meeting notes"),
        operates=("team coordination", "planning", "communication", "task follow-up"),
        outcomes=("meeting briefs", "follow-up plans", "status summaries", "decision logs"),
        evals=("personal-context", "safety", "redteam"),
    ),
    "Virtual Assistant": GhostPath(
        name="Virtual Assistant",
        description="Handles consented admin, scheduling, inbox triage, reminders, and personal workflows.",
        learns_from=("email exports", "schedule exports", "local documents", "assistant preferences"),
        operates=("personal admin", "calendar", "communication", "local file workflows"),
        outcomes=("inbox triage", "schedule prep", "reminders", "personal task execution"),
        evals=("personal-context", "safety", "redteam"),
    ),
    "AI Engineer Proxy": GhostPath(
        name="AI Engineer Proxy",
        description="Learns engineering preferences and acts as an authorized code/review/operator proxy.",
        learns_from=("local machine", "private repos", "public repos", "coding standards"),
        operates=("code execution", "GitHub", "MCP tools", "review workflows"),
        outcomes=("tested code changes", "code reviews", "implementation plans", "release checks"),
        evals=("github-connected", "personal-context", "redteam", "safety"),
    ),
    "Marketing Specialist": GhostPath(
        name="Marketing Specialist",
        description="Learns brand, audience, campaigns, and approved assets for marketing work.",
        learns_from=("campaign assets", "brand guidelines", "audience research", "content history"),
        operates=("content operations", "research", "asset review", "publishing workflow"),
        outcomes=("campaign briefs", "content drafts", "audience research", "brand reviews"),
        evals=("personal-context", "safety"),
    ),
    "Research Analyst": GhostPath(
        name="Research Analyst",
        description="Builds sourced research briefs from approved documents, repos, and public sources.",
        learns_from=("local documents", "approved public sources", "research preferences"),
        operates=("research", "browser", "citation review"),
        outcomes=("sourced briefs", "evidence maps", "research summaries"),
        evals=("smoke", "safety"),
    ),
}

BOB_FINDINGS = (
    "Developer onboarding friction",
    "Test coverage visibility gaps",
    "Scattered documentation across 20+ files",
    "Manual repetitive release and changelog work",
    "Missing integration tests for critical workflows",
)

BOB_BACKLOG = {
    "Developer Experience": (
        "Interactive onboarding tool",
        "Automated test coverage reporter",
        "Architecture Decision Records",
        "Code example library",
    ),
    "Testing and Quality": (
        "Integration test suite",
        "Automated dependency audit",
        "Performance regression tests",
    ),
    "Repo-Aware Automation": (
        "Intelligent test generator",
        "Automated changelog generator",
        "Dependency graph visualizer",
        "Debug logging analyzer",
    ),
}

BOB_BUILT_TOOLS = {
    "scripts/bob_accelerator.py": "Generates a developer productivity report from Bob's backlog.",
    "scripts/coverage_report.py": "Maps source modules to direct test signals and recommends next targets.",
    "scripts/bob_delivery_package.py": "Creates a PR-ready delivery package for judges with Bob findings.",
    "docs/adr/": "Captures architectural decisions so new developers can understand rationale faster.",
    "docs/IBM_BOB_WORKFLOW.md": "Preserves Bob's analysis, completed sprint work, and scaffolded roadmap.",
}


def bullet_list(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items)


def build_blueprint(path: GhostPath, training_mode: str, approval_level: str) -> dict[str, object]:
    training_pipeline = ["local memory RAG", "operator preference capture"]
    if training_mode == "Dataset generation":
        training_pipeline.append("MiniMind dataset generation")
    elif training_mode == "Local fine-tuning handoff":
        training_pipeline.extend(["MiniMind dataset generation", "local fine-tuning handoff"])

    sensitive_sources = " ".join(path.learns_from).lower()
    sensitive = any(term in sensitive_sources for term in ("email", "machine", "calendar", "private"))

    return {
        "concept": "personalized AI operator proxy",
        "role": path.name,
        "approved_learning_sources": path.learns_from,
        "tool_domains": path.operates,
        "operator_outcomes": path.outcomes,
        "training_pipeline": training_pipeline,
        "approval_policy": approval_level.lower(),
        "admin_controls_required": sensitive,
        "disclosure_boundary": {
            "allowed_claim": "authorized Ghost Chimera operator proxy",
            "blocked_claim": "undisclosed human impersonation",
        },
        "eval_suites": path.evals,
    }


def build_bob_delivery_package(priority_area: str) -> dict[str, object]:
    backlog_items = BOB_BACKLOG[priority_area]
    return {
        "source": "IBM Bob repository analysis",
        "workflow": "Bob-to-Ghost Delivery Package",
        "priority_area": priority_area,
        "bob_findings_used": BOB_FINDINGS,
        "selected_backlog": backlog_items,
        "ghost_actions": (
            "Convert Bob findings into implementation objectives",
            "Generate test and documentation targets",
            "Run governed readiness and safety checks",
            "Package PR-ready evidence for developers",
        ),
        "verification_gates": (
            "targeted pytest",
            "full pytest",
            "ghostchimera doctor --production",
            "README and artifact discoverability check",
        ),
        "expected_impact": {
            "onboarding_time": "2 hours to 10 minutes",
            "release_time": "2 hours to 30 minutes",
            "coverage_visibility": "unknown to explicit",
        },
    }


st.set_page_config(page_title="Ghost Chimera Demo", page_icon="GC", layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #08111F; color: #F8FBFF; }
    div[data-testid="stMetric"] {
        background: #111F33;
        border: 1px solid #2B3D59;
        padding: 14px 16px;
        border-radius: 8px;
    }
    div[data-testid="stMetric"] label { color: #B8C7D9 !important; }
    div[data-testid="stMetricValue"] { color: #35D6BD !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Ghost Chimera")
st.subheader("Bob-to-Ghost delivery accelerator for faster software development")
st.write(
    "For the IBM Bob Hackathon, Ghost Chimera uses IBM Bob as the codebase-aware "
    "development partner. Bob analyzes the repository and produces a prioritized backlog; "
    "Ghost Chimera converts that output into governed implementation, test, documentation, "
    "and readiness workflows."
)

metric_cols = st.columns(4)
metric_cols[0].metric("Ghost paths", "5")
metric_cols[1].metric("Capabilities", "13/13")
metric_cols[2].metric("Provider routes", "28")
metric_cols[3].metric("Verified tests", "1216")

st.divider()

tab_bob, tab_ghost, tab_vultr = st.tabs(("IBM Bob Workflow", "Ghost Blueprint", "Vultr Alignment"))

with tab_bob:
    st.header("IBM Bob Repository Analysis")
    st.write(
        "Bob completed a comprehensive analysis of the Ghost Chimera repository, "
        "identified strengths and bottlenecks, and produced a prioritized improvement backlog."
    )

    bob_cols = st.columns(2)
    with bob_cols[0]:
        st.subheader("Bob Findings")
        st.markdown(bullet_list(BOB_FINDINGS))
    with bob_cols[1]:
        st.subheader("Developer Impact Targets")
        st.markdown(
            bullet_list(
                (
                    "Onboarding time: 2 hours to 10 minutes",
                    "Coverage visibility: unknown to explicit",
                    "Release time: 2 hours to 30 minutes",
                    "Documentation discoverability: materially improved",
                )
            )
        )

    priority_area = st.selectbox("Choose Bob backlog area", list(BOB_BACKLOG))
    st.subheader("Bob-Suggested Backlog")
    st.markdown(bullet_list(BOB_BACKLOG[priority_area]))

    st.subheader("Bob-to-Ghost Delivery Package")
    st.json(build_bob_delivery_package(priority_area))

    st.subheader("Bob-Built Tools")
    for path, description in BOB_BUILT_TOOLS.items():
        st.markdown(f"- `{path}` - {description}")

    st.info(
        "Meaningful Bob use: Bob supplies repository understanding, findings, and backlog. "
        "Ghost Chimera adds execution discipline, policy gates, verification, and PR-ready packaging."
    )

with tab_ghost:
    left, right = st.columns([0.38, 0.62])

    with left:
        st.header("Create a Ghost")
        role = st.selectbox("Choose a Ghost path", list(PATHS))
        training_mode = st.radio(
            "Training mode",
            ("RAG-first", "Dataset generation", "Local fine-tuning handoff"),
        )
        approval_level = st.select_slider(
            "Approval level",
            options=("Assist", "Supervised", "Autonomous"),
            value="Supervised",
        )
        path = PATHS[role]

    with right:
        st.header(path.name)
        st.write(path.description)

        a, b, c = st.columns(3)
        with a:
            st.markdown("**Learns from**")
            st.markdown(bullet_list(path.learns_from))
        with b:
            st.markdown("**Can operate**")
            st.markdown(bullet_list(path.operates))
        with c:
            st.markdown("**Outcomes**")
            st.markdown(bullet_list(path.outcomes))

    st.header("Generated Ghost Blueprint")
    st.caption("This is the contract a real Ghost path emits before a user grants tools, data, or autonomy.")
    st.json(build_blueprint(path, training_mode, approval_level))

with tab_vultr:
    st.header("Vultr Alignment")
    st.write(
        "The repository includes a Vultr VM Docker Compose deployment package, production guardrails, "
        "and an optional Vultr Serverless Inference provider. In the full deployment, Vultr is the "
        "backend and system of record for the Ghost Console state, schedules, planning, memory status, "
        "and audit posture."
    )

    st.header("Demo Commands")
    st.code(
        """python scripts/bob_accelerator.py
python scripts/bob_accelerator.py --section test_coverage
python scripts/coverage_report.py --format markdown
python scripts/bob_delivery_package.py
python -m pytest tests/test_bob_accelerator.py tests/test_bob_delivery_package.py -q""",
        language="bash",
    )

    st.code(
        f"""ghostchimera path set --profile "{list(PATHS)[0].lower().replace(" ", "-")}" \\
  --training-mode "{training_mode}" \\
  --approval-level "{approval_level.lower()}"

ghostchimera minimind personal-status
ghostchimera capabilities --format json""",
        language="bash",
    )

st.divider()
st.info(
    "Boundary: this hosted demo intentionally does not access your machine, email, shell, "
    "desktop, or private repositories. The production Ghost runtime keeps those capabilities "
    "behind local consent, admin controls, and policy gates."
)
