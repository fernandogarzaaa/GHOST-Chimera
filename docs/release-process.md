# Release Process

Before release:

1. Run `python -m pytest -q`.
2. Run `python scripts/bob_accelerator.py`.
3. Run `python scripts/audit_dependencies.py --format markdown`.
4. Run `python scripts/generate_sbom.py --format markdown`.
5. Regenerate `docs/bob_delivery_package.md`.
6. Review generated artifacts before committing.

The GitHub workflows run Bob quality checks and a multi-platform test matrix.
