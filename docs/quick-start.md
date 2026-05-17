# Quick Start

This is the fastest way to get Ghost Chimera running locally.

## Option 1: Docker

If you want the browser UI without setting up a Python environment:

```bash
docker compose up --build
```

Then open `http://localhost:8766/`.

## Option 2: Local Python install

Use Python 3.11, 3.12, or 3.13.

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
ghostchimera console
```

Then open `http://localhost:8766/`.

## First successful run

1. Open the **Path** tab and choose a role.
2. Click **Synthesize** and then **Save Path**.
3. Open the **Run** tab.
4. Enter an objective such as `Summarize my current workspace and identify the next safe action.`
5. Click **Run**.

## Optional next steps

- Personal memory and training setup: [USER_TUTORIAL.md](USER_TUTORIAL.md)
- GitHub-connected workflow: [GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md](GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md)
- Personal MiniMind privacy and consent: [PERSONAL_MINIMIND_PRIVACY.md](PERSONAL_MINIMIND_PRIVACY.md)
