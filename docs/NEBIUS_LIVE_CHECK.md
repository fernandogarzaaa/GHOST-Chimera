# Nebius Token Factory live check

Run: 2026-10-13 18:41 UTC by `scripts/nebius_live_check.py` (re-run it to refresh this file).

- Endpoint: `https://api.tokenfactory.nebius.com/v1/chat/completions`
- Request: one chat completion per model, `max_tokens=4096`, `temperature=0`, `User-Agent: GHOST-Chimera/0.4.0-beta.1`, prompt "Reply with exactly the word: pong".
- Answer extraction: `ghostchimera.model_layer.reasoning_output.extract_answer` (`<think>` stripped, `reasoning_content` ignored, empty answer = failure).
- `GET /v1/models`: HTTP 200, 25 models listed

| Model ID | Listed in /v1/models | HTTP | Latency (s) | Non-empty answer | Excerpt | Notes |
|---|---|---|---|---|---|---|
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | yes | 200 | 0.81 | yes | pong | reasoning_content ignored; completion_tokens=44 |
| `nvidia/nemotron-3-super-120b-a12b` | yes | 200 | 1.04 | yes | pong | reasoning_content ignored; completion_tokens=22 |
| `nvidia/Nemotron-3-Ultra-550b-a55b` | yes | 200 | 1.06 | yes | pong | reasoning_content ignored; completion_tokens=41 |
| `nvidia/Nemotron-3_5-Lightning` | yes | 200 | 0.99 | yes | pong | reasoning_content ignored; completion_tokens=133 |

Nemotron models currently listed by Token Factory:

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`
- `nvidia/Nemotron-3-Ultra-550b-a55b`
- `nvidia/Nemotron-3_5-Lightning`
- `nvidia/nemotron-3-super-120b-a12b`
