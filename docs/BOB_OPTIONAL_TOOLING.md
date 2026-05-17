# IBM Bob Optional Tooling Boundary

IBM Bob support in this repository is hackathon and developer-experience tooling. It is not required to run Ghost Chimera, deploy Ghost Console, use the Python package, or call any Ghost Chimera CLI.

## Relationship

Ghost Chimera is the agent orchestration platform. IBM Bob was used as a codebase-aware development partner during the IBM Bob hackathon to analyze the repository, identify developer productivity gaps, and help produce local tooling around onboarding, coverage visibility, documentation, dependency review, release readiness, and judge-facing evidence.

The Bob work is intentionally outside the runtime path:

- Runtime package: `ghostchimera/`
- User CLIs: `ghostchimera`, `ghostchimera-parallel`, `chimera-pilot`, `ghostchimera-eval`
- Optional Bob developer tools: `scripts/bob_*.py` and related local scripts in `scripts/`
- Bob documentation: `docs/IBM_BOB_*.md`, `docs/BOB_POST_HACKATHON_ROADMAP.md`, and `docs/bob_delivery_package.md`
- Bob tests: `tests/test_bob_*.py`, related tool tests, and `tests/integration/test_bob_toolchain.py`

## Opt Out

Users who do not care about IBM Bob can ignore all Bob-named files. No package dependency, environment variable, provider configuration, or runtime command is required for Bob.

For a normal Ghost Chimera install, use the standard project commands:

```bash
python -m pip install -e ".[dev,gateway,mcp]"
ghostchimera --help
chimera-pilot --help
```

For Bob developer tooling, use the explicit scripts:

```bash
python scripts/bob_accelerator.py
python scripts/bob_delivery_package.py
```

## Modularity Rule

Bob-specific code must remain opt-in and outside the `ghostchimera/` runtime package. If future Bob-related tooling is added, it should follow these constraints:

1. Do not import Bob tooling from `ghostchimera/`.
2. Do not add Bob as a required dependency in `pyproject.toml`.
3. Do not require Bob credentials, tokens, services, or environment variables to run Ghost Chimera.
4. Keep Bob commands explicit under `scripts/`, docs, tests, or optional CI workflows.
5. Describe Bob features as developer tooling, not core Ghost Chimera runtime capability.

`tests/test_bob_optional_boundary.py` enforces this boundary by scanning the runtime package for Bob references.
