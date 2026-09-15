# Ghost Chimera Dependency Specification Audit

## Summary

- **Total dependencies:** 43
- **Dependencies with risks:** 39

## Base Dependencies

- `certifi>=2024.2.2` :warning:
  - Unpinned upper bound (>=)
- `croniter>=6.0.0` :warning:
  - Unpinned upper bound (>=)
- `cryptography>=42.0` :warning:
  - Unpinned upper bound (>=)
- `jsonschema>=4.0` :warning:
  - Unpinned upper bound (>=)
- `websockets>=12.0,<18`

## Optional Extras

### [desktop]

- `pyautogui>=0.9.54` :warning:
  - Unpinned upper bound (>=)

### [quantum]

- `pyqpanda3>=0.3.5` :warning:
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

- `websockets>=12.0,<18`
- `croniter>=6.0.0` :warning:
  - Unpinned upper bound (>=)

### [voice]

- `SpeechRecognition>=3.10` :warning:
  - Unpinned upper bound (>=)
- `faster-whisper>=1.0` :warning:
  - Unpinned upper bound (>=)
- `pocketsphinx>=5.0` :warning:
  - Unpinned upper bound (>=)
- `vosk>=0.3.45` :warning:
  - Unpinned upper bound (>=)
- `av>=10.0` :warning:
  - Unpinned upper bound (>=)

### [all]

- `certifi>=2024.2.2` :warning:
  - Unpinned upper bound (>=)
- `croniter>=6.0.0` :warning:
  - Unpinned upper bound (>=)
- `cryptography>=42.0` :warning:
  - Unpinned upper bound (>=)
- `jsonschema>=4.0` :warning:
  - Unpinned upper bound (>=)
- `pyautogui>=0.9.54` :warning:
  - Unpinned upper bound (>=)
- `websockets>=12.0,<18`
- `fsspec[http]>=2023.1.0,<=2026.7.0`
- `pyqpanda3>=0.3.5` :warning:
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
- `SpeechRecognition>=3.10` :warning:
  - Unpinned upper bound (>=)
- `faster-whisper>=1.0` :warning:
  - Unpinned upper bound (>=)
- `pocketsphinx>=5.0` :warning:
  - Unpinned upper bound (>=)
- `vosk>=0.3.45` :warning:
  - Unpinned upper bound (>=)
- `av>=10.0` :warning:
  - Unpinned upper bound (>=)

### [dev]

- `build>=1.2` :warning:
  - Unpinned upper bound (>=)
- `pytest>=8.0` :warning:
  - Unpinned upper bound (>=)
- `pytest-cov>=5.0` :warning:
  - Unpinned upper bound (>=)
- `ruff>=0.5` :warning:
  - Unpinned upper bound (>=)

## Common Risks

- **Unpinned upper bound (>=):** 39 occurrences

---

**Note:** This is a dependency specification audit, not a vulnerability scan.
For vulnerability scanning, use tools like `pip-audit` or `safety`.