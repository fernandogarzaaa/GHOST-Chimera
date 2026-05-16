# Quick Start

Install the project in editable mode:

```bash
python -m pip install -e .[dev,gateway]
```

Run the test suite:

```bash
python -m pytest tests/ -q
```

Run Bob's developer report:

```bash
python scripts/bob_accelerator.py
```

Generate the delivery package:

```bash
python scripts/bob_delivery_package.py --output docs/bob_delivery_package.md
```
