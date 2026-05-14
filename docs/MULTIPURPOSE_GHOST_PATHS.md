# Multi-Purpose Ghost Paths

Ghost Chimera can synthesize itself around a selected operator path. Public beta paths include Autonomous Engineer, AI Engineer Proxy, Manager Operator, Marketing Specialist, Virtual Assistant, Enterprise Operator, Personal Operations Assistant, Research Analyst, and Custom Ghost.

Each path resolves into a Ghost blueprint: the role the Ghost becomes, what it learns from, what work domains it can operate, which training pipeline is allowed, and which consent, approval, and disclosure controls apply.

## AI Engineer Proxy

The AI Engineer Proxy path lets an authorized user configure Ghost Chimera to learn their engineering preferences, repository standards, source preferences, review style, and delivery workflow. Ghost may use local files, email, private repositories, and license-compatible external repositories only when the user grants the matching source scope.

Ghost must not present itself as the human user without disclosure. The correct claim is that it is an authorized Ghost Chimera operator proxy acting under the user's configured controls.

## Manager Operator

The Manager Operator path learns from approved email exports, calendar exports, team documents, meeting notes, and management preferences. It is designed for meeting briefs, follow-up plans, status summaries, decision logs, planning, team coordination, and communication workflows.

## Marketing Specialist

The Marketing Specialist path learns from brand guidelines, campaign assets, audience research, content history, approved documents, and approved public sources. It is designed for campaign briefs, content drafts, audience research, brand-consistent reviews, asset review, and publishing workflows.

## Virtual Assistant

The Virtual Assistant path learns from approved email exports, schedule exports, local documents, and assistant preferences. It is designed for inbox triage, schedule prep, reminders, personal task execution, calendar workflows, communication, and local file workflows.

## Custom Ghost

The Custom Ghost path lets the operator define the sources, learning strategy, tool domains, autonomy posture, and approval policy manually while preserving the same consent and disclosure contract.

## External Source Policy

External repositories require URL, commit SHA, license signal, and intended use. Unknown-license sources are blocked for dataset generation and fine-tuning. They may only be used for RAG when the operator confirms the source is allowed for that use.

## Dashboard Flow

1. Open Ghost Console.
2. Choose the Path tab.
3. Select a role profile.
4. Choose RAG-first, dataset generation, or local fine-tuning.
5. Review the synthesized source, tool, proxy, and eval policy before granting permissions.
6. Select **Save Path** to persist the active profile for future console, CLI, and Personal MiniMind handoff use.

## CLI Flow

```powershell
ghostchimera path list
ghostchimera path set --profile ai-engineer-proxy --training-mode rag-first --approval-level supervised
ghostchimera path set --profile marketing-specialist --training-mode dataset_generation --approval-level supervised
ghostchimera path show
```

The active path is stored in the Ghost Chimera config file and defaults to
Autonomous Engineer when no profile has been selected. Personal MiniMind handoff
prompts read the active path and include the role name, proxy posture, and
synthesized policy in the prompt bundle sent to the configured primary model.

The `path show` and console synthesis payloads include `ghost_blueprint`, which is the operator-readable contract for what the selected Ghost learns from, what it can operate, and which training pipeline is active.

## Release Gate

```powershell
python -m ghostchimera.evals run --suite path-synthesis
python scripts\validate_release.py
```
