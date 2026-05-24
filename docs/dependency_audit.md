# Ghost Chimera Dependency Specification Audit

## Summary

- **Total dependencies:** 21
- **Dependencies with risks:** 21

## Optional Extras

### [quantum]

- `pyqpanda3>=3.0` :warning:
  - Unpinned upper bound (>=)

### [local]

- `llama-cpp-python>=0.3.0` :warning:
  - Unpinned upper bound (>=)

### [minimind]

- `torch>=2.6; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)
- `transformers>=4.57.0; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)
- `tokenizers>=0.20.0; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)

### [cute]

- `nvidia-cutlass-dsl>=4.0; python_version == '3.12' and platform_system == 'Linux'` :warning:
  - Unpinned upper bound (>=)

### [mcp]

- `mcp>=1.0.0` :warning:
  - Unpinned upper bound (>=)

### [gateway]

- `websockets>=12.0` :warning:
  - Unpinned upper bound (>=)
- `croniter>=6.0.0` :warning:
  - Unpinned upper bound (>=)

### [all]

- `pyqpanda3>=3.0` :warning:
  - Unpinned upper bound (>=)
- `llama-cpp-python>=0.3.0` :warning:
  - Unpinned upper bound (>=)
- `torch>=2.6; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)
- `transformers>=4.57.0; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)
- `tokenizers>=0.20.0; python_version < '3.14'` :warning:
  - Unpinned upper bound (>=)
- `nvidia-cutlass-dsl>=4.0; python_version == '3.12' and platform_system == 'Linux'` :warning:
  - Unpinned upper bound (>=)
- `mcp>=1.0.0` :warning:
  - Unpinned upper bound (>=)
- `websockets>=12.0` :warning:
  - Unpinned upper bound (>=)
- `croniter>=6.0.0` :warning:
  - Unpinned upper bound (>=)

### [dev]

- `build>=1.2` :warning:
  - Unpinned upper bound (>=)
- `pytest>=8.0` :warning:
  - Unpinned upper bound (>=)
- `ruff>=0.5` :warning:
  - Unpinned upper bound (>=)

## Common Risks

- **Unpinned upper bound (>=):** 21 occurrences

---

**Note:** This is a dependency specification audit, not a vulnerability scan.
For vulnerability scanning, use tools like `pip-audit` or `safety`.