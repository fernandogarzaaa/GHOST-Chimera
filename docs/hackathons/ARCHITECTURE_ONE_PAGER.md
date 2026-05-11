# Architecture One-Pager (Hackathon)

## Product scope

Ghost Chimera is a local-first **Governed Enterprise Change Agent**.

## End-to-end path

Objective -> TaskSpec compilation -> backend scoring/scheduling -> policy gate -> execution/fallback -> verification -> confidence/audit envelope.

## Control surfaces

- Chimera Pilot scheduler and backend contract
- Policy enforcement and production guardrails
- Verification + telemetry + replay
- Operator console (`/api/console/*`) for status, jobs, and readiness

## Enterprise trust posture

- Deny-by-default for high-risk execution without explicit opt-in
- Deployment readiness gate for production mode
- Auditable and explainable behavior over opaque automation

## Hackathon fit

- Agentic Olympics: bounded autonomy and orchestration depth
- Transforming Enterprise: security + governance + explainability
- IBM Bob: repo-aware analysis to governed change package
- AI GENESIS: modular adapter-ready architecture
