# Multi-Purpose Ghost Paths

Ghost Chimera can synthesize itself around a selected operator path. Public beta paths include Autonomous Engineer, AI Engineer Proxy, Enterprise Operator, Personal Operations Assistant, Research Analyst, and Custom Ghost.

## AI Engineer Proxy

The AI Engineer Proxy path lets an authorized user configure Ghost Chimera to learn their engineering preferences, repository standards, source preferences, review style, and delivery workflow. Ghost may use local files, email, private repositories, and license-compatible external repositories only when the user grants the matching source scope.

Ghost must not present itself as the human user without disclosure. The correct claim is that it is an authorized Ghost Chimera operator proxy acting under the user's configured controls.

## External Source Policy

External repositories require URL, commit SHA, license signal, and intended use. Unknown-license sources are blocked for dataset generation and fine-tuning. They may only be used for RAG when the operator confirms the source is allowed for that use.

## Dashboard Flow

1. Open Ghost Console.
2. Choose the Path tab.
3. Select a role profile.
4. Choose RAG-first, dataset generation, or local fine-tuning.
5. Review the synthesized source, tool, proxy, and eval policy before granting permissions.

## Release Gate

```powershell
python -m ghostchimera.evals run --suite path-synthesis
python scripts\validate_release.py
```
