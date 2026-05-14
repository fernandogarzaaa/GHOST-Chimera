# GitHub-Connected Autonomous Engineer

Ghost Chimera's public beta default can run as a local runner connected to GitHub. The operator connects a repository, selects an issue or objective, approves the plan, and lets Ghost create a worktree, implement, test, review, and prepare a pull request.

## Auth Modes

1. GitHub App or installation token through `GHOSTCHIMERA_GITHUB_TOKEN`.
2. Fine-scoped personal access token through `GITHUB_TOKEN`.
3. `gh` CLI authentication for local beta users.

## Operator Flow

```powershell
$env:GHOSTCHIMERA_GITHUB_TOKEN="..."
ghostchimera github status
ghostchimera github plan --repo owner/repo --issue 42 --title "Fix CI"
ghostchimera console
```

The Ghost Console exposes the same workflow through the GitHub tab:

- connection status
- issue-to-objective planning
- policy preview for push, PR, review, and private-repo actions

## Safety Controls

Ghost must require explicit approval before pushing branches, opening pull requests, posting comments, reading private repository data, or launching autonomous repair loops. All production actions should write append-only audit records with repository, issue or PR, command, result, and operator approval metadata.

## Release Gate

```powershell
python -m ghostchimera.evals run --suite github-connected
python scripts\validate_release.py
```
