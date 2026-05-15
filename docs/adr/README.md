# Architecture Decision Records (ADR)

This directory contains Architecture Decision Records for Ghost Chimera.

## What is an ADR?

An Architecture Decision Record (ADR) captures an important architectural decision made along with its context and consequences.

## Format

Each ADR follows this structure:

```markdown
# ADR-NNN: [Title]

**Date:** YYYY-MM-DD  
**Status:** [Proposed | Accepted | Deprecated | Superseded by ADR-XXX]

## Context

What is the issue we're facing? What factors are influencing this decision?

## Decision

What did we decide to do?

## Consequences

What becomes easier or harder as a result of this decision?

## Alternatives Considered

What other options did we evaluate and why were they not chosen?
```

## Creating a New ADR

Use the template script:

```bash
python scripts/create_adr.py "Title of Decision"
```

Or manually:

1. Copy `template.md` to a new file with the next number
2. Fill in the sections
3. Submit for review via pull request

## Index

- [ADR-001: Chimera Pilot Scheduling Architecture](001-chimera-pilot-scheduling.md)
- [ADR-002: Conservative Safety Defaults](002-conservative-safety-defaults.md)
- [ADR-003: Layer Separation Architecture](003-layer-separation.md)
- [ADR-004: Optional Dependency Strategy](004-optional-dependencies.md)

## Status Definitions

- **Proposed:** Under discussion, not yet accepted
- **Accepted:** Decision has been made and is active
- **Deprecated:** No longer relevant but kept for historical context
- **Superseded:** Replaced by a newer decision (link to new ADR)