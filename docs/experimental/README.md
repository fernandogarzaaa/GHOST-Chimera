# Experimental features

Everything on this page is **experimental**. It ships in the package (mostly
behind optional extras or explicit commands) but it is early, may change or be
removed without notice, and is **not** part of what the Nebius x NVIDIA
hackathon submission should be evaluated on. The supported core is the Stealth
Loop, Chimera Pilot, the Trust Runtime, and the optional Nemotron reasoning on
Nebius Token Factory (see [OVERVIEW](../OVERVIEW.md)).

| Feature | How it is reached | Docs | Status |
|---|---|---|---|
| Superiority scorecard | `ghostchimera superiority score`, `python -m ghostchimera.evals run --suite superiority`, `GET /api/console/superiority` | [COMPETITIVE_CAPABILITY_MATRIX.md](../COMPETITIVE_CAPABILITY_MATRIX.md) | Experimental. A self-assessment computed from the project's own checks, not an independent benchmark; treat scores as internal progress signals, not comparative claims. |
| SaaS / multi-tenant launch | `ghostchimera saas status`, `ghostchimera worker status`, `docker-compose.saas.yml` | [PUBLIC_LAUNCH_SAAS.md](../PUBLIC_LAUNCH_SAAS.md) | Experimental scaffolding (OIDC, Postgres schema, worker leases). Not a hosted service. |
| Quantum backend | `pip install "ghostchimera[quantum]"`, `--include-quantum-backend` | [CHIMERA_PILOT.md](../../CHIMERA_PILOT.md) | Experimental. Optional pyqpanda3 *simulator* backend for Chimera Pilot; no access to quantum hardware or a quantum OS. |
| MiniMind personal models | `pip install "ghostchimera[minimind]"`, `ghostchimera minimind ...` | [PERSONAL_MINIMIND_PRIVACY.md](../PERSONAL_MINIMIND_PRIVACY.md) | Experimental. Opt-in local training of small personal models; heavy dependencies (torch, transformers). |
