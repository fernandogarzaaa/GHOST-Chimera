# Personal MiniMind Privacy and Operation

Personal MiniMind is an opt-in local personalization layer. It can index user
files and email exports into a local SQLite memory store, generate local
MiniMind JSONL training records, train a small local neural Personal MiniMind
adapter, and prepare a RAG handoff prompt for the configured primary Ghost
model.

This document is product documentation, not legal advice.

## Consent Scopes

Personal MiniMind does nothing until admin controls are enabled.

| Scope | Effect |
|---|---|
| `admin_controls` | Required master toggle for Personal MiniMind. |
| `allow_system_specs` | Captures OS, Python, CPU count, disk usage, home path, and current working directory. |
| `allow_files` | Ingests explicit file or directory paths. |
| `allow_email` | Ingests explicit `.eml`, `.mbox`, or email-export directories. |
| `allow_machine_crawl` | Discovers supported text files under crawl roots. |
| `allow_email_crawl` | Discovers `.eml` and `.mbox` files under crawl roots. |
| `allow_training` | Writes MiniMind JSONL records and permits local neural adapter training under the local state directory. |
| `allow_autonomy` | Allows Personal MiniMind output to be used as task hints for autonomous workflows. |

Consent is persisted at:

```text
<state_dir>/minimind/personal_consent.json
```

Revoke it from the dashboard or with:

```bash
ghostchimera minimind personal-revoke
```

## Whole-Machine Crawl

The whole-machine toggle scans readable local files using the current OS user
account. It does not bypass permissions, decrypt protected stores, or elevate
privileges.

When `--crawl-root` is omitted, Ghost uses local drives on Windows and the user
home directory on Unix-like systems. Operators can provide specific crawl roots
to make the scan faster and easier to audit:

```bash
ghostchimera minimind personal-consent \
  --admin-controls \
  --allow-machine-crawl \
  --allow-email-crawl \
  --allow-training \
  --crawl-root C:\Users\you

ghostchimera minimind personal-bootstrap --max-files 500 --max-emails 1000
```

Default exclusions include common system, dependency, VCS, temp, and cache
directories such as `.git`, `.venv`, `node_modules`, `Windows`, `Program Files`,
`AppData`, `__pycache__`, and cache/temp folders.

Additional exclusions can be configured:

```bash
ghostchimera minimind personal-consent \
  --admin-controls \
  --allow-machine-crawl \
  --crawl-root C:\Users\you \
  --exclude-path C:\Users\you\Private
```

## Email Crawling

Email crawling means discovering local email artifacts (`.eml` and `.mbox`) in
approved crawl roots. Live Gmail, Outlook, or IMAP account access requires a
separate authenticated connector or export workflow and is not silently enabled
by Personal MiniMind.

## Local Storage

Personal MiniMind stores data locally:

| Data | Default location |
|---|---|
| Consent | `<state_dir>/minimind/personal_consent.json` |
| Memory | `<state_dir>/memory.sqlite3` |
| Dataset | `<state_dir>/minimind/datasets/dataset.jsonl` |
| Neural adapter weights | `<state_dir>/minimind/adapters/neural_adapter.json` |

Operators are responsible for backing up, deleting, encrypting, or excluding
private data according to their own environment and legal obligations.

## Local MiniMind Runtime

Personal MiniMind does not require a cloud provider for its local memory,
dataset, or neural adapter workflow. The built-in neural adapter performs real
numeric weight updates from approved dataset records and can answer locally
from those trained weights. It is intentionally small and auditable; it is not
full upstream MiniMind checkpoint fine-tuning.

Supported local paths:

- Ghost-native neural Personal MiniMind adapter trained with:

  ```bash
  ghostchimera minimind personal-train-neural --epochs 12 --learning-rate 0.25
  ghostchimera minimind personal-infer --objective "What did Ghost learn?"
  ```

- Transformers/PyTorch MiniMind checkpoint through `.[minimind]` and
  `MINIMIND_MODEL_PATH`.
- GGUF/llama.cpp-style local execution through Ghost's local model path when
  compatible quantized weights are available.

The primary Ghost model can still be a cloud provider, a local provider, or a
fallback chain. Personal MiniMind's handoff is provider-agnostic: it prepares
context and task hints, then the configured primary model executes the work.
