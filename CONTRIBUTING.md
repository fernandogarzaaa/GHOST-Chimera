# Contributing

Thank you for contributing to Ghost Chimera.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/validate_release.py
```

## Engineering rules

- Keep changes small and directly tied to the issue.
- Do not refactor unrelated modules while fixing a bug.
- Add tests for new behavior.
- Keep local execution capabilities opt-in and policy-gated.
- Do not add proprietary code, private APIs, scraped licensed artifacts, or copied implementation details from external products.

## Test requirements

Before opening a pull request, run:

```bash
python -m unittest tests.test_chimera_pilot tests.test_release_package -v
python -m compileall ghostchimera tests
python scripts/validate_release.py
```

## Clean-room requirements

When implementing ideas inspired by external systems:

1. Use public docs, papers, and open-source repositories only.
2. Convert product-specific ideas into neutral architecture notes.
3. Implement from the neutral spec, not from proprietary code.
4. Add attribution or clean-room notes where appropriate.
