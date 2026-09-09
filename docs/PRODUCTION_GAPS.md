# Production Gap Scanner

Ghost Chimera includes a local production-gap scanner that makes placeholder,
scaffold, stub, demo-runtime, and TODO-like markers visible before a release.

This is not a replacement for tests or code review. It is an operator-facing
audit layer that helps distinguish shipped runtime behavior from code that needs
implementation or review.

## Run It

```bash
ghostchimera production-gaps --format json
ghostchimera production-gaps --format markdown --limit 50
```

The same data is available in Ghost Console:

```text
GET /api/console/production/gaps
```

## Severity

- `action_required`: runtime package findings such as `NotImplemented`,
  scaffold/stub markers, or placeholder-like implementation text.
- `non_blocking`: docs, tests, examples, or review-only markers such as TODO
  notes and demo wording.

## Security

The scanner redacts secret-like values from snippets before returning results.
It never reads external services, sends telemetry, or mutates files.
