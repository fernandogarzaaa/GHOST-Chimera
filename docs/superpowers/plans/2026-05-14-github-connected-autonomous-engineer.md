# GitHub-Connected Autonomous Engineer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub-connected autonomous engineering the default public beta workflow for Ghost Chimera.

**Architecture:** Add a first-party GitHub integration layer that discovers repositories, tracks issues and pull requests, runs isolated task worktrees, posts review output back to GitHub, watches CI, and records audit evidence. Personal MiniMind feeds task context into GitHub work discovery, while the Enterprise Control Plane owns consent, permissions, policy simulation, and audit trails.

**Tech Stack:** Python stdlib-first integration, existing Ghost Chimera CLI and Gateway console, GitHub REST/CLI fallback, local git worktrees, existing autonomy queue, MiniMind personal context, existing release/eval gates, dashboard static HTML/CSS/JS.

---

## Product Contract

The public beta default should be: connect GitHub, choose a repository, select an issue or objective, approve the plan, let Ghost create a worktree, implement, test, review itself, open or update a PR, monitor CI, and repair failures under policy controls.

GitHub-connected mode must work without hosted Ghost infrastructure. The first beta implementation should support a local runner with either a configured GitHub App token, `gh` CLI authentication, or a personal access token supplied through environment variables. GitHub App remains the preferred public beta path because it scopes permissions cleanly for users and organizations.

Ghost Chimera must also be multi-purpose. The first-run UX should ask the user what kind of Ghost they want: autonomous engineer, AI engineer proxy, personal operations assistant, enterprise automation operator, research analyst, or custom role. The selected path should synthesize a role profile, source policy, tool policy, model plan, training/RAG strategy, dashboard layout, and release/eval gates.

For the AI engineer proxy path, Ghost should not impersonate the user deceptively. It should act as an authorized operator proxy with auditable disclosure, scoped permissions, and user-configurable approvals. External knowledge expansion must only ingest sources the user has permission to use or sources whose license and terms allow the intended dataset/training use. GitHub repository ingestion must record repository URL, commit SHA, license signal, and whether the content is used for RAG-only, dataset generation, or fine-tuning.

## File Structure

- Create: `ghostchimera/integrations/github_client.py`
  - Owns GitHub API models, auth detection, REST calls, and `gh` CLI fallback.
- Create: `ghostchimera/personalization/role_profiles.py`
  - Owns user-selectable Ghost paths such as AI engineer proxy, personal operations assistant, and enterprise operator.
- Create: `ghostchimera/personalization/path_synthesizer.py`
  - Converts a role profile plus user preferences into source, model, tool, dashboard, and eval configuration.
- Create: `ghostchimera/integrations/source_discovery.py`
  - Discovers external source candidates and records license/terms metadata before ingestion.
- Create: `ghostchimera/integrations/github_tasks.py`
  - Converts issues, PRs, and MiniMind discoveries into Ghost autonomy task specs.
- Create: `ghostchimera/integrations/github_worktree.py`
  - Creates and cleans isolated local worktrees for GitHub tasks.
- Create: `ghostchimera/integrations/github_ci.py`
  - Reads GitHub check runs/statuses and classifies failures for repair loops.
- Create: `ghostchimera/integrations/github_audit.py`
  - Records per-task prompts, approvals, commands, diffs, test results, PR links, and CI outcomes.
- Modify: `ghostchimera/chimera_pilot/pr_review.py`
  - Add a review-to-GitHub formatting contract without coupling the deterministic reviewer to network writes.
- Modify: `ghostchimera/control_plane/cli.py`
  - Add `github` command group for status, repos, issues, plan, run, review-post, ci-watch, and repair.
- Modify: `ghostchimera/control_plane/console.py`
  - Add `/api/console/github/*` routes for connection status, repository scan, issue-to-PR launch, CI watch, and audit records.
- Modify: `ghostchimera/control_plane/static/index.html`
  - Add a GitHub tab in the dashboard.
- Modify: `ghostchimera/control_plane/static/app.js`
  - Wire dashboard state and actions for GitHub-connected workflows.
- Modify: `ghostchimera/control_plane/static/styles.css`
  - Style compact GitHub workflow panels without nested cards.
- Modify: `ghostchimera/model_layer/minimind_personal_agent.py`
  - Add role-profile-aware handoff context for the selected Ghost path.
- Modify: `ghostchimera/chimera_pilot/capability_intelligence.py`
  - Add GitHub-connected autonomous engineering surfaces to the competitive capability matrix.
- Modify: `ghostchimera/evals/runner.py`
  - Add a `github-connected` eval suite with local mocked GitHub behavior.
- Create: `tests/test_github_client.py`
- Create: `tests/test_role_profiles.py`
- Create: `tests/test_path_synthesizer.py`
- Create: `tests/test_source_discovery.py`
- Create: `tests/test_github_tasks.py`
- Create: `tests/test_github_worktree.py`
- Create: `tests/test_github_ci.py`
- Create: `tests/test_github_audit.py`
- Modify: `tests/test_pr_review.py`
- Modify: `tests/test_console.py`
- Modify: `tests/test_capability_intelligence.py`
- Modify: `tests/test_evals.py`
- Modify: `docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md`
- Modify: `docs/COMPETITIVE_CAPABILITY_MATRIX.md`
- Modify: `docs/RELEASE_CHECKLIST.md`
- Modify: `README.md`

---

### Task 0: Multi-Purpose Path Synthesizer

**Files:**
- Create: `ghostchimera/personalization/role_profiles.py`
- Create: `ghostchimera/personalization/path_synthesizer.py`
- Create: `ghostchimera/integrations/source_discovery.py`
- Modify: `ghostchimera/control_plane/console.py`
- Modify: `ghostchimera/control_plane/static/index.html`
- Modify: `ghostchimera/control_plane/static/app.js`
- Test: `tests/test_role_profiles.py`
- Test: `tests/test_path_synthesizer.py`
- Test: `tests/test_source_discovery.py`
- Test: `tests/test_console.py`

- [ ] **Step 1: Write failing role profile tests**

```python
import unittest

from ghostchimera.personalization.role_profiles import get_role_profile, list_role_profiles


class RoleProfileTests(unittest.TestCase):
    def test_ai_engineer_proxy_profile_has_training_and_github_sources(self) -> None:
        profile = get_role_profile("ai-engineer-proxy")
        self.assertEqual(profile.id, "ai-engineer-proxy")
        self.assertIn("github_public_repositories", profile.source_scopes)
        self.assertIn("rag", profile.learning_modes)
        self.assertIn("dataset_generation", profile.learning_modes)
        self.assertTrue(profile.requires_disclosure)

    def test_list_role_profiles_includes_multi_purpose_paths(self) -> None:
        ids = {profile.id for profile in list_role_profiles()}
        self.assertIn("autonomous-engineer", ids)
        self.assertIn("ai-engineer-proxy", ids)
        self.assertIn("enterprise-operator", ids)
```

- [ ] **Step 2: Write failing synthesizer tests**

```python
import unittest

from ghostchimera.personalization.path_synthesizer import synthesize_path


class PathSynthesizerTests(unittest.TestCase):
    def test_ai_engineer_proxy_synthesis_enables_github_and_guarded_training(self) -> None:
        result = synthesize_path(
            "ai-engineer-proxy",
            preferences={"training_mode": "rag-first", "approval_level": "supervised"},
        )
        self.assertEqual(result["role"]["id"], "ai-engineer-proxy")
        self.assertIn("github", result["dashboard_tabs"])
        self.assertEqual(result["learning_strategy"]["default_mode"], "rag-first")
        self.assertIn("license_check_required", result["source_policy"])
        self.assertTrue(result["proxy_policy"]["disclosure_required"])
```

- [ ] **Step 3: Write failing source discovery tests**

```python
import unittest

from ghostchimera.integrations.source_discovery import SourceCandidate, filter_allowed_sources


class SourceDiscoveryTests(unittest.TestCase):
    def test_filter_allowed_sources_blocks_unknown_license_for_training(self) -> None:
        candidates = [
            SourceCandidate(url="https://github.com/example/mit", kind="github", license="MIT", commit="abc"),
            SourceCandidate(url="https://github.com/example/unknown", kind="github", license="", commit="def"),
        ]
        allowed = filter_allowed_sources(candidates, intended_use="fine_tuning")
        self.assertEqual([item.url for item in allowed], ["https://github.com/example/mit"])
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_role_profiles.py tests/test_path_synthesizer.py tests/test_source_discovery.py -q
```

Expected: FAIL because the new modules do not exist.

- [ ] **Step 5: Add role profile model**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoleProfile:
    id: str
    name: str
    description: str
    source_scopes: tuple[str, ...]
    learning_modes: tuple[str, ...]
    dashboard_tabs: tuple[str, ...]
    eval_suites: tuple[str, ...]
    requires_disclosure: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_scopes": list(self.source_scopes),
            "learning_modes": list(self.learning_modes),
            "dashboard_tabs": list(self.dashboard_tabs),
            "eval_suites": list(self.eval_suites),
            "requires_disclosure": self.requires_disclosure,
        }


_PROFILES = {
    "autonomous-engineer": RoleProfile(
        id="autonomous-engineer",
        name="Autonomous Engineer",
        description="Turns issues and objectives into tested code changes and pull requests.",
        source_scopes=("local_repository", "github_private_repositories", "project_docs"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("github", "review", "capabilities", "autonomy"),
        eval_suites=("github-connected", "competitive", "safety"),
    ),
    "ai-engineer-proxy": RoleProfile(
        id="ai-engineer-proxy",
        name="AI Engineer Proxy",
        description="Learns the user's AI engineering preferences and acts as an authorized engineering proxy.",
        source_scopes=("local_machine", "email", "github_private_repositories", "github_public_repositories", "license_allowed_external_sources"),
        learning_modes=("rag", "dataset_generation", "local_fine_tuning"),
        dashboard_tabs=("path", "minimind", "github", "training", "review", "audit"),
        eval_suites=("github-connected", "personal-context", "redteam", "safety"),
        requires_disclosure=True,
    ),
    "enterprise-operator": RoleProfile(
        id="enterprise-operator",
        name="Enterprise Operator",
        description="Runs governed automations with RBAC, policy simulation, audit trails, and approval workflows.",
        source_scopes=("organization_repositories", "approved_integrations", "policy_docs"),
        learning_modes=("rag", "workflow_memory"),
        dashboard_tabs=("policy", "github", "audit", "autonomy", "capabilities"),
        eval_suites=("safety", "redteam", "github-connected"),
    ),
}


def list_role_profiles() -> list[RoleProfile]:
    return list(_PROFILES.values())


def get_role_profile(profile_id: str) -> RoleProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown role profile: {profile_id}") from exc
```

- [ ] **Step 6: Add path synthesizer**

```python
from __future__ import annotations

from typing import Any

from .role_profiles import get_role_profile


def synthesize_path(profile_id: str, preferences: dict[str, Any] | None = None) -> dict[str, Any]:
    preferences = preferences or {}
    profile = get_role_profile(profile_id)
    training_mode = str(preferences.get("training_mode") or "rag-first")
    approval_level = str(preferences.get("approval_level") or "supervised")
    return {
        "role": profile.to_dict(),
        "dashboard_tabs": list(profile.dashboard_tabs),
        "learning_strategy": {
            "default_mode": training_mode,
            "allowed_modes": list(profile.learning_modes),
            "external_training_requires_license_metadata": True,
        },
        "source_policy": {
            "scopes": list(profile.source_scopes),
            "license_check_required": "github_public_repositories" in profile.source_scopes,
            "record_commit_sha": True,
            "rag_allowed_before_fine_tuning": True,
        },
        "tool_policy": {
            "approval_level": approval_level,
            "push_requires_approval": True,
            "destructive_actions_require_approval": True,
        },
        "proxy_policy": {
            "disclosure_required": profile.requires_disclosure,
            "allowed_claim": "authorized Ghost Chimera operator proxy",
            "blocked_claim": "undisclosed human impersonation",
        },
        "eval_suites": list(profile.eval_suites),
    }
```

- [ ] **Step 7: Add external source discovery policy**

```python
from __future__ import annotations

from dataclasses import dataclass


_TRAINING_COMPATIBLE_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "CC0-1.0"}


@dataclass(frozen=True)
class SourceCandidate:
    url: str
    kind: str
    license: str = ""
    commit: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"url": self.url, "kind": self.kind, "license": self.license, "commit": self.commit}


def filter_allowed_sources(candidates: list[SourceCandidate], *, intended_use: str) -> list[SourceCandidate]:
    if intended_use in {"fine_tuning", "dataset_generation"}:
        return [candidate for candidate in candidates if candidate.license in _TRAINING_COMPATIBLE_LICENSES and bool(candidate.commit)]
    return candidates
```

- [ ] **Step 8: Add dashboard path route**

Add route handlers to `ghostchimera/control_plane/console.py`:

```python
def role_profiles(ctx: dict[str, Any]) -> dict[str, Any]:
    from ..personalization.role_profiles import list_role_profiles

    return {"ok": True, "profiles": [profile.to_dict() for profile in list_role_profiles()]}


def synthesize_role_path(ctx: dict[str, Any]) -> dict[str, Any]:
    from ..personalization.path_synthesizer import synthesize_path

    body = _json_body(ctx)
    profile_id = str(body.get("profile_id") or "")
    if not profile_id:
        return {"ok": False, "error": "profile_id is required"}
    return {"ok": True, "path": synthesize_path(profile_id, preferences=dict(body.get("preferences") or {}))}
```

Register:

```python
_api_register("/api/console/paths", role_profiles, method="GET", description="List multi-purpose Ghost paths")
_api_register("/api/console/paths/synthesize", synthesize_role_path, method="POST", description="Synthesize Ghost Chimera from a selected user path")
```

- [ ] **Step 9: Add dashboard path chooser**

Add a top-level dashboard tab:

```html
<button class="tab-button" data-tab="path" type="button">Path</button>
```

Add a path panel:

```html
<section class="tab-panel" id="path-panel" data-panel="path">
  <div class="panel-grid">
    <section class="panel-block">
      <h2>Choose Ghost Path</h2>
      <select id="path-profile"></select>
      <select id="path-training-mode">
        <option value="rag-first">RAG first</option>
        <option value="dataset_generation">Dataset generation</option>
        <option value="local_fine_tuning">Local fine-tuning</option>
      </select>
      <button id="path-synthesize" type="button">Synthesize</button>
      <pre id="path-output"></pre>
    </section>
  </div>
</section>
```

Add JavaScript:

```javascript
async function refreshPathProfiles() {
  const payload = await apiGet("/api/console/paths");
  const select = document.querySelector("#path-profile");
  select.innerHTML = "";
  for (const profile of payload.profiles || []) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.name;
    select.appendChild(option);
  }
}

async function synthesizeSelectedPath() {
  const profile_id = document.querySelector("#path-profile").value;
  const training_mode = document.querySelector("#path-training-mode").value;
  const payload = await apiPost("/api/console/paths/synthesize", {
    profile_id,
    preferences: { training_mode, approval_level: "supervised" },
  });
  document.querySelector("#path-output").textContent = JSON.stringify(payload.path || payload, null, 2);
}
```

- [ ] **Step 10: Run focused tests**

Run:

```powershell
python -m pytest tests/test_role_profiles.py tests/test_path_synthesizer.py tests/test_source_discovery.py tests/test_console.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add ghostchimera/personalization/role_profiles.py ghostchimera/personalization/path_synthesizer.py ghostchimera/integrations/source_discovery.py ghostchimera/control_plane/console.py ghostchimera/control_plane/static/index.html ghostchimera/control_plane/static/app.js tests/test_role_profiles.py tests/test_path_synthesizer.py tests/test_source_discovery.py tests/test_console.py
git commit -m "Add multi-purpose Ghost path synthesizer"
```

---

### Task 1: GitHub Client And Auth Discovery

**Files:**
- Create: `ghostchimera/integrations/__init__.py`
- Create: `ghostchimera/integrations/github_client.py`
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write failing tests for auth discovery and request planning**

```python
import os
import unittest
from unittest.mock import patch

from ghostchimera.integrations.github_client import GitHubAuth, GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_auth_prefers_app_token_then_pat_then_gh_cli(self) -> None:
        with patch.dict(os.environ, {"GHOSTCHIMERA_GITHUB_TOKEN": "ghs_app"}, clear=True):
            auth = GitHubAuth.discover()
        self.assertEqual(auth.mode, "token")
        self.assertEqual(auth.token, "ghs_app")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_pat"}, clear=True):
            auth = GitHubAuth.discover()
        self.assertEqual(auth.mode, "token")
        self.assertEqual(auth.token, "ghp_pat")

    def test_client_builds_standard_headers_without_logging_secret(self) -> None:
        client = GitHubClient(auth=GitHubAuth(mode="token", token="ghs_secret"))
        headers = client.headers()
        self.assertEqual(headers["Authorization"], "Bearer ghs_secret")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertNotIn("ghs_secret", repr(client))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_client.py -q`

Expected: FAIL because `ghostchimera.integrations.github_client` does not exist.

- [ ] **Step 3: Add minimal client implementation**

```python
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GitHubAuth:
    mode: str
    token: str = ""

    @classmethod
    def discover(cls) -> "GitHubAuth":
        token = os.environ.get("GHOSTCHIMERA_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        if token:
            return cls(mode="token", token=token)
        return cls(mode="gh-cli")


class GitHubClient:
    def __init__(self, *, auth: GitHubAuth | None = None, api_base: str = "https://api.github.com") -> None:
        self.auth = auth or GitHubAuth.discover()
        self.api_base = api_base.rstrip("/")

    def __repr__(self) -> str:
        return f"GitHubClient(mode={self.auth.mode!r}, api_base={self.api_base!r})"

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ghostchimera-github-connected-beta",
        }
        if self.auth.token:
            headers["Authorization"] = f"Bearer {self.auth.token}"
        return headers

    def get_json(self, path: str) -> dict[str, Any] | list[Any]:
        if self.auth.mode == "gh-cli" and not self.auth.token:
            return self._gh_api(path)
        url = f"{self.api_base}/{path.lstrip('/')}"
        request = urllib.request.Request(url, headers=self.headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API failed with HTTP {exc.code}: {body}") from exc

    def _gh_api(self, path: str) -> dict[str, Any] | list[Any]:
        completed = subprocess.run(
            ["gh", "api", path],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "gh api failed").strip())
        return json.loads(completed.stdout or "{}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_client.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/__init__.py ghostchimera/integrations/github_client.py tests/test_github_client.py
git commit -m "Add GitHub client auth discovery"
```

---

### Task 2: Repository Scan And Task Conversion

**Files:**
- Create: `ghostchimera/integrations/github_tasks.py`
- Modify: `ghostchimera/integrations/github_client.py`
- Test: `tests/test_github_tasks.py`

- [ ] **Step 1: Write failing tests for repo and issue summaries**

```python
import unittest

from ghostchimera.integrations.github_tasks import GitHubIssue, GitHubRepoScan, issue_to_objective


class GitHubTaskTests(unittest.TestCase):
    def test_issue_to_objective_includes_repo_issue_and_acceptance(self) -> None:
        issue = GitHubIssue(
            repo="owner/repo",
            number=42,
            title="Add dashboard filter",
            body="Users need a status filter.\nAcceptance: filter queued and failed jobs.",
            labels=["enhancement"],
            url="https://github.com/owner/repo/issues/42",
        )
        objective = issue_to_objective(issue)
        self.assertIn("owner/repo#42", objective)
        self.assertIn("Add dashboard filter", objective)
        self.assertIn("Acceptance", objective)

    def test_repo_scan_reports_release_commands(self) -> None:
        scan = GitHubRepoScan(repo="owner/repo", default_branch="main", languages=["Python"], release_commands=["python -m pytest -q"])
        payload = scan.to_dict()
        self.assertEqual(payload["repo"], "owner/repo")
        self.assertEqual(payload["release_commands"], ["python -m pytest -q"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_tasks.py -q`

Expected: FAIL because `github_tasks.py` does not exist.

- [ ] **Step 3: Add task models and conversion**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GitHubIssue:
    repo: str
    number: int
    title: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    url: str = ""

    @classmethod
    def from_api(cls, repo: str, payload: dict[str, Any]) -> "GitHubIssue":
        return cls(
            repo=repo,
            number=int(payload["number"]),
            title=str(payload.get("title") or ""),
            body=str(payload.get("body") or ""),
            labels=[str(item.get("name") or "") for item in payload.get("labels") or [] if item.get("name")],
            url=str(payload.get("html_url") or ""),
        )


@dataclass(frozen=True)
class GitHubRepoScan:
    repo: str
    default_branch: str
    languages: list[str]
    release_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "default_branch": self.default_branch,
            "languages": self.languages,
            "release_commands": self.release_commands,
        }


def issue_to_objective(issue: GitHubIssue) -> str:
    labels = ", ".join(issue.labels) if issue.labels else "none"
    return "\n".join(
        [
            f"Implement GitHub issue {issue.repo}#{issue.number}: {issue.title}",
            f"Source: {issue.url or issue.repo}",
            f"Labels: {labels}",
            "",
            issue.body.strip(),
            "",
            "Deliver a tested change, run the repository release gates, review the diff, and prepare a pull request.",
        ]
    ).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_tasks.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/github_tasks.py tests/test_github_tasks.py
git commit -m "Add GitHub task conversion models"
```

---

### Task 3: Isolated GitHub Worktree Runner

**Files:**
- Create: `ghostchimera/integrations/github_worktree.py`
- Test: `tests/test_github_worktree.py`

- [ ] **Step 1: Write failing tests for worktree naming and command plan**

```python
import tempfile
import unittest
from pathlib import Path

from ghostchimera.integrations.github_worktree import GitHubWorktreePlan


class GitHubWorktreeTests(unittest.TestCase):
    def test_worktree_plan_uses_codex_branch_prefix_and_issue_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = GitHubWorktreePlan.create(
                repo_root=Path(tmp),
                repo="owner/repo",
                issue_number=42,
                base_branch="main",
            )
        self.assertEqual(plan.branch, "codex/github-42")
        self.assertTrue(str(plan.path).endswith("repo-github-42"))
        self.assertIn("git worktree add", " ".join(plan.commands))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_worktree.py -q`

Expected: FAIL because `github_worktree.py` does not exist.

- [ ] **Step 3: Add worktree plan object**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-").lower()


@dataclass(frozen=True)
class GitHubWorktreePlan:
    repo_root: Path
    path: Path
    branch: str
    base_branch: str
    commands: list[str]

    @classmethod
    def create(cls, *, repo_root: Path, repo: str, issue_number: int, base_branch: str) -> "GitHubWorktreePlan":
        repo_name = _slug(repo.split("/")[-1])
        branch = f"codex/github-{issue_number}"
        path = repo_root.resolve().parent / f"{repo_name}-github-{issue_number}"
        commands = [
            "git fetch origin",
            f"git worktree add {path} -b {branch} origin/{base_branch}",
        ]
        return cls(repo_root=repo_root.resolve(), path=path, branch=branch, base_branch=base_branch, commands=commands)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_worktree.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/github_worktree.py tests/test_github_worktree.py
git commit -m "Plan isolated GitHub worktrees"
```

---

### Task 4: PR Review Posting Contract

**Files:**
- Modify: `ghostchimera/chimera_pilot/pr_review.py`
- Create: `ghostchimera/integrations/github_review.py`
- Test: `tests/test_pr_review.py`
- Create: `tests/test_github_review.py`

- [ ] **Step 1: Write failing test for GitHub comment body**

```python
import unittest

from ghostchimera.chimera_pilot.pr_review import PRReviewReport, ReviewFinding
from ghostchimera.integrations.github_review import format_github_review_comment


class GitHubReviewPostingTests(unittest.TestCase):
    def test_format_github_review_comment_marks_blocking_findings(self) -> None:
        report = PRReviewReport(
            base="origin/main",
            head="HEAD",
            root=".",
            files_changed=["app.py"],
            findings=[ReviewFinding(severity="P1", title="Secret detected", path="app.py", line=7)],
        )
        body = format_github_review_comment(report)
        self.assertIn("Ghost Chimera PR Review", body)
        self.assertIn("Blocking findings: 1", body)
        self.assertIn("P1 Secret detected", body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_review.py -q`

Expected: FAIL because `github_review.py` does not exist.

- [ ] **Step 3: Add GitHub review comment formatting**

```python
from __future__ import annotations

from ghostchimera.chimera_pilot.pr_review import PRReviewReport, format_pr_review_report


def format_github_review_comment(report: PRReviewReport) -> str:
    payload = report.to_dict()
    blocking = [item for item in payload["findings"] if item["severity"] in {"P0", "P1"}]
    header = [
        "## Ghost Chimera PR Review",
        "",
        f"- Blocking findings: {len(blocking)}",
        f"- Risk score: {payload['risk_score']}",
        f"- Summary: {payload['summary']}",
        "",
    ]
    return "\n".join(header) + format_pr_review_report(report)
```

- [ ] **Step 4: Add post-comment method to `GitHubClient`**

```python
def post_issue_comment(self, repo: str, number: int, body: str) -> dict[str, Any]:
    payload = json.dumps({"body": body}).encode("utf-8")
    if self.auth.mode == "gh-cli" and not self.auth.token:
        completed = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{number}/comments", "-X", "POST", "-f", f"body={body}"],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "gh api failed").strip())
        return json.loads(completed.stdout or "{}")
    request = urllib.request.Request(
        f"{self.api_base}/repos/{repo}/issues/{number}/comments",
        data=payload,
        headers={**self.headers(), "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_pr_review.py tests/test_github_review.py tests/test_github_client.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ghostchimera/chimera_pilot/pr_review.py ghostchimera/integrations/github_review.py ghostchimera/integrations/github_client.py tests/test_pr_review.py tests/test_github_review.py tests/test_github_client.py
git commit -m "Add GitHub PR review posting contract"
```

---

### Task 5: CI Watch And Repair Classification

**Files:**
- Create: `ghostchimera/integrations/github_ci.py`
- Test: `tests/test_github_ci.py`

- [ ] **Step 1: Write failing tests for check-run classification**

```python
import unittest

from ghostchimera.integrations.github_ci import classify_check_runs


class GitHubCITests(unittest.TestCase):
    def test_classify_check_runs_marks_failed_required_checks(self) -> None:
        payload = [
            {"name": "pytest", "status": "completed", "conclusion": "failure", "html_url": "https://ci/1"},
            {"name": "lint", "status": "completed", "conclusion": "success", "html_url": "https://ci/2"},
        ]
        report = classify_check_runs(payload)
        self.assertFalse(report["ok"])
        self.assertEqual(report["failed"], ["pytest"])
        self.assertIn("pytest", report["repair_objective"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_ci.py -q`

Expected: FAIL because `github_ci.py` does not exist.

- [ ] **Step 3: Add CI classifier**

```python
from __future__ import annotations

from typing import Any


def classify_check_runs(check_runs: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [
        str(run.get("name") or "unnamed")
        for run in check_runs
        if str(run.get("status") or "") == "completed" and str(run.get("conclusion") or "") not in {"success", "neutral", "skipped"}
    ]
    return {
        "ok": not failed,
        "failed": failed,
        "total": len(check_runs),
        "repair_objective": "" if not failed else f"Diagnose and repair failing GitHub checks: {', '.join(failed)}.",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_ci.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/github_ci.py tests/test_github_ci.py
git commit -m "Add GitHub CI failure classifier"
```

---

### Task 6: Audit Trail For GitHub Tasks

**Files:**
- Create: `ghostchimera/integrations/github_audit.py`
- Test: `tests/test_github_audit.py`

- [ ] **Step 1: Write failing tests for append-only audit records**

```python
import json
import tempfile
import unittest
from pathlib import Path

from ghostchimera.integrations.github_audit import GitHubAuditLog


class GitHubAuditTests(unittest.TestCase):
    def test_audit_log_appends_jsonl_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = GitHubAuditLog(Path(tmp))
            path = log.record("owner/repo", "issue-plan", {"issue": 42, "approved": True})
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(records[0]["repo"], "owner/repo")
        self.assertEqual(records[0]["event"], "issue-plan")
        self.assertTrue(records[0]["payload"]["approved"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_audit.py -q`

Expected: FAIL because `github_audit.py` does not exist.

- [ ] **Step 3: Add audit log**

```python
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class GitHubAuditLog:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "github" / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, repo: str, event: str, payload: dict[str, Any]) -> Path:
        entry = {
            "timestamp": time.time(),
            "repo": repo,
            "event": event,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
        return self.path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_github_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/github_audit.py tests/test_github_audit.py
git commit -m "Add GitHub task audit log"
```

---

### Task 7: CLI GitHub Command Group

**Files:**
- Modify: `ghostchimera/control_plane/cli.py`
- Test: `tests/test_github_cli.py`

- [ ] **Step 1: Write failing CLI smoke tests**

```python
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ghostchimera.control_plane.cli import _main


class GitHubCLITests(unittest.TestCase):
    def test_github_status_prints_auth_mode(self) -> None:
        with patch.dict("os.environ", {"GHOSTCHIMERA_GITHUB_TOKEN": "ghs_test"}, clear=True):
            output = io.StringIO()
            with redirect_stdout(output):
                code = _main(["github", "status"])
        self.assertEqual(code, 0)
        self.assertIn("token", output.getvalue())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_cli.py -q`

Expected: FAIL because the `github` command does not exist.

- [ ] **Step 3: Add parser and status handler**

```python
github_parser = sub.add_parser("github", help="Run GitHub-connected autonomous engineering workflows")
github_parser.add_argument("action", choices=["status", "repos", "issues", "plan", "run", "review-post", "ci-watch", "repair"], nargs="?", default="status")
github_parser.add_argument("--repo", default="", help="Repository in owner/name form.")
github_parser.add_argument("--issue", type=int, default=0, help="GitHub issue number.")
github_parser.add_argument("--pr", type=int, default=0, help="GitHub pull request number.")
github_parser.add_argument("--base", default="origin/main", help="Base ref for local review.")
github_parser.add_argument("--head", default="HEAD", help="Head ref for local review.")
```

Add a command handler after args parsing:

```python
if args.command == "github":
    from ghostchimera.integrations.github_client import GitHubAuth

    auth = GitHubAuth.discover()
    if args.action == "status":
        print(json.dumps({"ok": True, "auth_mode": auth.mode, "has_token": bool(auth.token)}, indent=2))
        return 0
```

- [ ] **Step 4: Run CLI tests**

Run: `python -m pytest tests/test_github_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/control_plane/cli.py tests/test_github_cli.py
git commit -m "Expose GitHub workflows in the CLI"
```

---

### Task 8: Console API Routes

**Files:**
- Modify: `ghostchimera/control_plane/console.py`
- Test: `tests/test_console.py`

- [ ] **Step 1: Add failing console route test**

```python
def test_console_registers_github_routes(self) -> None:
    server = GatewayServer()
    register_console_routes(server)
    status_route = server.routes.find("GET", "/api/console/github/status")
    plan_route = server.routes.find("POST", "/api/console/github/plan")

    self.assertIsNotNone(status_route)
    self.assertIsNotNone(plan_route)

    status = status_route.handler({"method": "GET", "path": "/api/console/github/status", "headers": {}, "body": "", "query": {}})
    self.assertTrue(status["ok"])
    self.assertIn(status["auth_mode"], {"token", "gh-cli"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_console.py::ConsoleRouteTests::test_console_registers_github_routes -q`

Expected: FAIL because routes are missing.

- [ ] **Step 3: Add route handlers**

```python
def github_status(ctx: dict[str, Any]) -> dict[str, Any]:
    from ..integrations.github_client import GitHubAuth

    auth = GitHubAuth.discover()
    return {"ok": True, "auth_mode": auth.mode, "has_token": bool(auth.token)}


def github_plan(ctx: dict[str, Any]) -> dict[str, Any]:
    from ..integrations.github_tasks import GitHubIssue, issue_to_objective

    body = _json_body(ctx)
    repo = str(body.get("repo") or "")
    issue_number = int(body.get("issue") or 0)
    if not repo or issue_number <= 0:
        return {"ok": False, "error": "repo and issue are required"}
    issue = GitHubIssue(repo=repo, number=issue_number, title=str(body.get("title") or ""), body=str(body.get("body") or ""))
    return {"ok": True, "objective": issue_to_objective(issue)}
```

Register:

```python
_api_register("/api/console/github/status", github_status, method="GET", description="Inspect GitHub integration status")
_api_register("/api/console/github/plan", github_plan, method="POST", description="Convert a GitHub issue into a Ghost objective")
```

- [ ] **Step 4: Run console tests**

Run: `python -m pytest tests/test_console.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/control_plane/console.py tests/test_console.py
git commit -m "Expose GitHub workflows in the console API"
```

---

### Task 9: Dashboard GitHub Tab

**Files:**
- Modify: `ghostchimera/control_plane/static/index.html`
- Modify: `ghostchimera/control_plane/static/app.js`
- Modify: `ghostchimera/control_plane/static/styles.css`
- Test: `tests/test_console.py`

- [ ] **Step 1: Add failing static UI assertions**

```python
def test_console_static_ui_exposes_github_tab(self) -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "ghostchimera" / "control_plane" / "static" / "index.html").read_text(encoding="utf-8")
    app = (root / "ghostchimera" / "control_plane" / "static" / "app.js").read_text(encoding="utf-8")

    self.assertIn("data-tab=\"github\"", html)
    self.assertIn("/api/console/github/status", app)
    self.assertIn("/api/console/github/plan", app)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_console.py::ConsoleRouteTests::test_console_static_ui_exposes_github_tab -q`

Expected: FAIL because the UI does not expose the GitHub tab.

- [ ] **Step 3: Add compact dashboard tab**

In `index.html`, add a tab button near the other top-level tabs:

```html
<button class="tab-button" data-tab="github" type="button">GitHub</button>
```

Add a GitHub panel:

```html
<section class="tab-panel" id="github-panel" data-panel="github">
  <div class="panel-grid">
    <section class="panel-block">
      <h2>GitHub Autopilot</h2>
      <div id="github-status">Disconnected</div>
      <input id="github-repo" placeholder="owner/repo" />
      <input id="github-issue" placeholder="Issue number" />
      <button id="github-plan" type="button">Plan Issue</button>
      <pre id="github-objective"></pre>
    </section>
  </div>
</section>
```

In `app.js`, add fetch calls:

```javascript
async function refreshGithubStatus() {
  const payload = await apiGet("/api/console/github/status");
  document.querySelector("#github-status").textContent = payload.ok
    ? `Auth: ${payload.auth_mode}`
    : payload.error || "Unavailable";
}

async function planGithubIssue() {
  const repo = document.querySelector("#github-repo").value.trim();
  const issue = Number(document.querySelector("#github-issue").value.trim());
  const payload = await apiPost("/api/console/github/plan", { repo, issue });
  document.querySelector("#github-objective").textContent = payload.ok ? payload.objective : payload.error;
}
```

- [ ] **Step 4: Run UI/static tests**

Run: `python -m pytest tests/test_console.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/control_plane/static/index.html ghostchimera/control_plane/static/app.js ghostchimera/control_plane/static/styles.css tests/test_console.py
git commit -m "Add GitHub autopilot dashboard tab"
```

---

### Task 10: MiniMind Work Discovery Inbox

**Files:**
- Create: `ghostchimera/integrations/github_discovery.py`
- Modify: `ghostchimera/model_layer/minimind_personal_agent.py`
- Test: `tests/test_github_tasks.py`
- Test: `tests/test_minimind_personal_agent.py`

- [ ] **Step 1: Write failing work discovery test**

```python
import unittest

from ghostchimera.integrations.github_discovery import rank_work_items


class GitHubDiscoveryTests(unittest.TestCase):
    def test_rank_work_items_prioritizes_assigned_bug_and_user_context(self) -> None:
        items = [
            {"kind": "issue", "title": "Refactor docs", "labels": ["docs"], "assigned": False},
            {"kind": "issue", "title": "Fix failing release gate", "labels": ["bug"], "assigned": True},
        ]
        ranked = rank_work_items(items, personal_context="I maintain release gates and CI.")
        self.assertEqual(ranked[0]["title"], "Fix failing release gate")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_tasks.py::GitHubDiscoveryTests -q`

Expected: FAIL because `github_discovery.py` does not exist.

- [ ] **Step 3: Add deterministic ranking**

```python
from __future__ import annotations

from typing import Any


def rank_work_items(items: list[dict[str, Any]], personal_context: str = "") -> list[dict[str, Any]]:
    context = personal_context.lower()
    ranked: list[dict[str, Any]] = []
    for item in items:
        labels = {str(label).lower() for label in item.get("labels") or []}
        title = str(item.get("title") or "").lower()
        score = 0.0
        if item.get("assigned"):
            score += 2.0
        if "bug" in labels or "failure" in title or "failing" in title:
            score += 1.5
        if "release" in title and "release" in context:
            score += 1.0
        enriched = dict(item)
        enriched["score"] = round(score, 3)
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: item["score"], reverse=True)
```

- [ ] **Step 4: Run discovery tests**

Run: `python -m pytest tests/test_github_tasks.py tests/test_minimind_personal_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostchimera/integrations/github_discovery.py ghostchimera/model_layer/minimind_personal_agent.py tests/test_github_tasks.py tests/test_minimind_personal_agent.py
git commit -m "Add MiniMind-ranked GitHub work discovery"
```

---

### Task 11: Enterprise Policy Simulation

**Files:**
- Create: `ghostchimera/integrations/github_policy.py`
- Modify: `ghostchimera/control_plane/console.py`
- Test: `tests/test_github_policy.py`
- Test: `tests/test_console.py`

- [ ] **Step 1: Write failing policy simulation test**

```python
import unittest

from ghostchimera.integrations.github_policy import simulate_github_action_policy


class GitHubPolicyTests(unittest.TestCase):
    def test_policy_blocks_push_without_explicit_consent(self) -> None:
        result = simulate_github_action_policy({"action": "push_branch", "autonomous": True}, {"allow_push": False})
        self.assertFalse(result["allowed"])
        self.assertIn("allow_push", result["required_controls"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github_policy.py -q`

Expected: FAIL because `github_policy.py` does not exist.

- [ ] **Step 3: Add policy simulator**

```python
from __future__ import annotations

from typing import Any


def simulate_github_action_policy(action: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    required: list[str] = []
    name = str(action.get("action") or "")
    if name in {"push_branch", "open_pr", "post_review"} and not controls.get("allow_push"):
        required.append("allow_push")
    if action.get("autonomous") and not controls.get("allow_autonomy"):
        required.append("allow_autonomy")
    return {
        "allowed": not required,
        "required_controls": required,
        "action": name,
    }
```

- [ ] **Step 4: Add console route**

Register `POST /api/console/github/policy-simulate` with a handler that calls `simulate_github_action_policy`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_github_policy.py tests/test_console.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ghostchimera/integrations/github_policy.py ghostchimera/control_plane/console.py tests/test_github_policy.py tests/test_console.py
git commit -m "Add GitHub action policy simulation"
```

---

### Task 12: Competitive Matrix And Eval Gate

**Files:**
- Modify: `ghostchimera/chimera_pilot/capability_intelligence.py`
- Modify: `ghostchimera/evals/runner.py`
- Modify: `tests/test_path_synthesizer.py`
- Modify: `tests/test_capability_intelligence.py`
- Modify: `tests/test_evals.py`

- [ ] **Step 1: Write failing capability test**

```python
def test_capability_matrix_includes_github_connected_autonomous_engineer_and_path_synthesis(self) -> None:
    report = inspect_capabilities()
    ids = {item["id"] for item in report["capabilities"]}
    self.assertIn("github_connected_autonomous_engineer", ids)
    self.assertIn("multi_purpose_path_synthesis", ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_capability_intelligence.py::CapabilityIntelligenceTests::test_capability_matrix_includes_github_connected_autonomous_engineer -q`

Expected: FAIL because the capability is not registered.

- [ ] **Step 3: Add capability surfaces**

Add a capability entry requiring:

```python
CapabilityRequirement(
    id="github_connected_autonomous_engineer",
    name="GitHub-Connected Autonomous Engineer",
    description="Issue-to-PR workflows, review posting, CI watch, worktree isolation, MiniMind work discovery, and policy simulation.",
    competitors=["OpenAI Codex", "Claude Code", "LangGraph", "CrewAI"],
    priority=5,
    release_gate="python -m ghostchimera.evals run --suite github-connected",
    surfaces=[
        CapabilitySurface("GitHub client", "ghostchimera/integrations/github_client.py", "GitHubClient"),
        CapabilitySurface("GitHub worktree plans", "ghostchimera/integrations/github_worktree.py", "GitHubWorktreePlan"),
        CapabilitySurface("GitHub CI classifier", "ghostchimera/integrations/github_ci.py", "classify_check_runs"),
        CapabilitySurface("GitHub console routes", "ghostchimera/control_plane/console.py", "/api/console/github/status"),
        CapabilitySurface("GitHub CLI", "ghostchimera/control_plane/cli.py", "github"),
    ],
)
```

Add a second capability entry requiring:

```python
CapabilityRequirement(
    id="multi_purpose_path_synthesis",
    name="Multi-Purpose Ghost Path Synthesis",
    description="User-selectable Ghost paths that synthesize role, source, training, dashboard, proxy, and policy configuration.",
    competitors=["OpenAI Codex", "Claude Code", "CrewAI"],
    priority=5,
    release_gate="python -m ghostchimera.evals run --suite path-synthesis",
    surfaces=[
        CapabilitySurface("Role profiles", "ghostchimera/personalization/role_profiles.py", "RoleProfile"),
        CapabilitySurface("Path synthesizer", "ghostchimera/personalization/path_synthesizer.py", "synthesize_path"),
        CapabilitySurface("Source discovery policy", "ghostchimera/integrations/source_discovery.py", "filter_allowed_sources"),
        CapabilitySurface("Dashboard path route", "ghostchimera/control_plane/console.py", "/api/console/paths/synthesize"),
    ],
)
```

- [ ] **Step 4: Add eval suite**

Add `github-connected` and `path-synthesis` to `EVAL_SUITES` with checks that import the GitHub/path modules, run mocked client/task tests, assert source filtering blocks unlicensed training use, and assert console route registration.

- [ ] **Step 5: Run eval tests**

Run: `python -m pytest tests/test_capability_intelligence.py tests/test_evals.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ghostchimera/chimera_pilot/capability_intelligence.py ghostchimera/evals/runner.py tests/test_capability_intelligence.py tests/test_evals.py
git commit -m "Gate GitHub-connected autonomous engineering"
```

---

### Task 13: Documentation And Release Checklist

**Files:**
- Create: `docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md`
- Create: `docs/MULTIPURPOSE_GHOST_PATHS.md`
- Modify: `docs/COMPETITIVE_CAPABILITY_MATRIX.md`
- Modify: `docs/RELEASE_CHECKLIST.md`
- Modify: `README.md`

- [ ] **Step 1: Add operator documentation**

Create `docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md` with:

```markdown
# GitHub-Connected Autonomous Engineer

Ghost Chimera's public beta default is a local runner connected to GitHub. The operator connects a repository, selects an issue or objective, approves the plan, and lets Ghost create a worktree, implement, test, review, and prepare a pull request.

## Auth Modes

1. GitHub App installation token through `GHOSTCHIMERA_GITHUB_TOKEN`.
2. Fine-scoped personal access token through `GITHUB_TOKEN`.
3. `gh` CLI authentication for local beta users.

## Safety Controls

Ghost must require explicit approval before pushing branches, opening pull requests, posting comments, reading private repository data, or launching autonomous repair loops. All actions write an append-only audit record.

## Release Gate

Run:

```powershell
python -m ghostchimera.evals run --suite github-connected
python scripts\validate_release.py
```
```

- [ ] **Step 2: Add multi-purpose path documentation**

Create `docs/MULTIPURPOSE_GHOST_PATHS.md` with:

```markdown
# Multi-Purpose Ghost Paths

Ghost Chimera can synthesize itself around a selected operator path. Public beta paths include Autonomous Engineer, AI Engineer Proxy, Enterprise Operator, Personal Operations Assistant, Research Analyst, and Custom.

## AI Engineer Proxy

The AI Engineer Proxy path lets an authorized user configure Ghost Chimera to learn their engineering preferences, repository standards, source preferences, review style, and delivery workflow. Ghost may use local files, email, private repositories, and license-compatible external repositories only when the user grants the matching source scope.

Ghost must not present itself as the human user without disclosure. The correct claim is that it is an authorized Ghost Chimera operator proxy acting under the user's configured controls.

## External Source Policy

External repositories require URL, commit SHA, license signal, and intended use. Unknown-license sources are blocked for dataset generation and fine-tuning. They may only be used for RAG when the operator confirms the source is allowed for that use.
```

- [ ] **Step 3: Add README quickstart**

Add a "GitHub-connected beta workflow" section to `README.md` showing:

```powershell
$env:GHOSTCHIMERA_GITHUB_TOKEN="..."
ghostchimera github status
ghostchimera github plan --repo owner/repo --issue 42
ghostchimera console
```

- [ ] **Step 4: Add README path quickstart**

Add a "Choose your Ghost path" section to `README.md` showing:

```powershell
ghostchimera console
```

Then document that the dashboard Path tab can synthesize the AI Engineer Proxy path with RAG-first, dataset generation, or local fine-tuning preferences.

- [ ] **Step 5: Add release checklist entries**

Add `python -m ghostchimera.evals run --suite github-connected`, `python -m ghostchimera.evals run --suite path-synthesis`, and `ghostchimera github status` to `docs/RELEASE_CHECKLIST.md`.

- [ ] **Step 6: Run docs checks**

Run: `python -m ghostchimera.evals run --suite github-connected`

Expected: PASS.

Run: `python -m ghostchimera.evals run --suite path-synthesis`

Expected: PASS.

Run: `python scripts/validate_release.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md docs/MULTIPURPOSE_GHOST_PATHS.md docs/COMPETITIVE_CAPABILITY_MATRIX.md docs/RELEASE_CHECKLIST.md README.md
git commit -m "Document GitHub-connected and multi-purpose paths"
```

---

### Task 14: Full Release Verification

**Files:**
- No source files should change in this task unless verification exposes a real defect.

- [ ] **Step 1: Run focused test suite**

Run:

```powershell
python -m pytest tests/test_role_profiles.py tests/test_path_synthesizer.py tests/test_source_discovery.py tests/test_github_client.py tests/test_github_tasks.py tests/test_github_worktree.py tests/test_github_ci.py tests/test_github_audit.py tests/test_github_review.py tests/test_github_policy.py tests/test_github_cli.py tests/test_console.py tests/test_capability_intelligence.py tests/test_evals.py -q
```

Expected: PASS.

- [ ] **Step 2: Run lint**

Run: `python -m ruff check ghostchimera tests scripts`

Expected: PASS.

- [ ] **Step 3: Run GitHub-connected eval**

Run: `python -m ghostchimera.evals run --suite github-connected`

Expected: PASS.

- [ ] **Step 4: Run path-synthesis eval**

Run: `python -m ghostchimera.evals run --suite path-synthesis`

Expected: PASS.

- [ ] **Step 5: Run competitive eval**

Run: `python -m ghostchimera.evals run --suite competitive`

Expected: PASS with `github_connected_autonomous_engineer` complete.

- [ ] **Step 6: Run release validator**

Run: `python scripts\validate_release.py`

Expected: PASS.

- [ ] **Step 7: Build package**

Run: `python -m build`

Expected: source distribution and wheel created under `dist/`.

- [ ] **Step 8: Full test suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 9: Final review**

Run: `python -m ghostchimera review-pr --base origin/main --head WORKTREE --format markdown`

Expected: no P0 or P1 findings.

- [ ] **Step 10: Commit release integration if fixes were needed**

```bash
git add ghostchimera tests docs README.md
git commit -m "Complete GitHub-connected autonomous engineer beta"
```

---

## Self-Review

Spec coverage: The plan covers the approved Autonomous Engineer, Personal AI OS, and Enterprise Control Plane pillars through GitHub issue-to-PR execution, MiniMind work discovery, multi-purpose path synthesis, external source policy, and policy/audit controls.

Placeholder scan: This plan avoids open-ended placeholders and provides concrete file paths, tests, commands, code snippets, and expected outcomes.

Type consistency: The task models consistently use `RoleProfile`, `synthesize_path`, `SourceCandidate`, `GitHubAuth`, `GitHubClient`, `GitHubIssue`, `GitHubRepoScan`, `GitHubWorktreePlan`, `GitHubAuditLog`, `classify_check_runs`, `format_github_review_comment`, and `simulate_github_action_policy`.

Execution boundary: This document is a plan only. Implementation should proceed task-by-task using a fresh worktree or an explicit execution mode, with commits after each completed task.
