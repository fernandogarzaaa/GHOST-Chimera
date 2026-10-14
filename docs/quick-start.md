# Quick Start

This is the fastest way to get Ghost Chimera running locally.

## Step 0: one-minute demo (no keys, no network)

```bash
pipx install ghostchimera      # or: pip install ghostchimera
ghost demo                     # replays a recorded NVIDIA Nemotron session offline
```

`ghost demo` runs the real Stealth Loop against a Nemotron session recorded live on
Nebius Token Factory and bundled with the package.

## Step 1: connect NVIDIA Nemotron on Nebius Token Factory (recommended)

Get a key at [console.nebius.com](https://console.nebius.com) (Token Factory → API keys), then:

```bash
export GHOSTCHIMERA_MODEL_PROVIDER=nebius
export NEBIUS_API_KEY=your-token-factory-key
ghost ask "In one sentence, what is NVIDIA Nemotron?"
ghost demo --record session.json   # record your own live Nemotron session
```

On Windows PowerShell:

```powershell
$env:GHOSTCHIMERA_MODEL_PROVIDER = "nebius"
$env:NEBIUS_API_KEY = "your-token-factory-key"
ghost ask "In one sentence, what is NVIDIA Nemotron?"
```

`ghost setup` offers Nebius Token Factory as the first (default) provider and can save the
key to your config instead. Without any provider configured, `ghost ask` only has the
deterministic offline backend and will tell you so.

## Option 1: Docker

If you want the browser UI without setting up a Python environment:

```bash
docker compose up --build
```

Then open `http://localhost:8766/`.

## Option 2: Local Python install from a clone

Use Python 3.11, 3.12, or 3.13. These commands install from a source checkout:

```bash
git clone https://github.com/fernandogarzaaa/GHOST-Chimera
cd GHOST-Chimera
```

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gateway]"
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[gateway]"
```

Start the console:

```bash
ghostchimera start
```

Then open `http://localhost:8766/`.

Run a one-liner objective (OpenClaw/Hermes-style terminal flow; needs a provider from Step 1):

```bash
ghost "Summarize my current workspace and tell me the next safest action."
```

## First successful run

1. Open the **Path** tab and choose a role.
2. Click **Synthesize** and then **Save Path**.
3. Open the **Run** tab.
4. Enter an objective such as `Summarize my current workspace and identify the next safe action.`
5. Click **Run**.

## Optional next steps

- Uninstall and remove local state (`~/.ghostchimera`): [INSTALL.md](INSTALL.md#uninstall-and-clean-up)

- Personal memory and training setup: [USER_TUTORIAL.md](USER_TUTORIAL.md)
- GitHub-connected workflow: [GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md](GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md)
- Personal MiniMind privacy and consent: [PERSONAL_MINIMIND_PRIVACY.md](PERSONAL_MINIMIND_PRIVACY.md)
