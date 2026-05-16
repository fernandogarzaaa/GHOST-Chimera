# SBOM-lite

Project: `ghostchimera`
Version: `0.4.0-beta`
Components: 21

## Components

- `pyqpanda3` (optional:quantum): `pyqpanda3>=3.0`
- `llama-cpp-python` (optional:local): `llama-cpp-python>=0.3.0`
- `torch` (optional:minimind): `torch>=2.6; python_version < '3.14'`
- `transformers` (optional:minimind): `transformers>=4.57.0; python_version < '3.14'`
- `tokenizers` (optional:minimind): `tokenizers>=0.20.0; python_version < '3.14'`
- `nvidia-cutlass-dsl` (optional:cute): `nvidia-cutlass-dsl>=4.0; python_version == '3.12' and platform_system == 'Linux'`
- `mcp` (optional:mcp): `mcp>=1.0.0`
- `websockets` (optional:gateway): `websockets>=12.0`
- `croniter` (optional:gateway): `croniter>=6.0.0`
- `pyqpanda3` (optional:all): `pyqpanda3>=3.0`
- `llama-cpp-python` (optional:all): `llama-cpp-python>=0.3.0`
- `torch` (optional:all): `torch>=2.6; python_version < '3.14'`
- `transformers` (optional:all): `transformers>=4.57.0; python_version < '3.14'`
- `tokenizers` (optional:all): `tokenizers>=0.20.0; python_version < '3.14'`
- `nvidia-cutlass-dsl` (optional:all): `nvidia-cutlass-dsl>=4.0; python_version == '3.12' and platform_system == 'Linux'`
- `mcp` (optional:all): `mcp>=1.0.0`
- `websockets` (optional:all): `websockets>=12.0`
- `croniter` (optional:all): `croniter>=6.0.0`
- `build` (optional:dev): `build>=1.2`
- `pytest` (optional:dev): `pytest>=8.0`
- `ruff` (optional:dev): `ruff>=0.5`

## Limitations

- Generated from declared dependency specifications only.
- Does not resolve transitive dependencies.
- Does not perform vulnerability scanning.
