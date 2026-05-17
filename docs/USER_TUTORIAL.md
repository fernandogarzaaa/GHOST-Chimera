# Ghost Chimera User Tutorial

This tutorial walks a new user through the first practical Ghost Chimera workflow: install the app, open Ghost Console, choose a Ghost Path, run a first objective, optionally connect personal context, and understand the GitHub and self-evolution boundaries.

## What Ghost Chimera is

Ghost Chimera is a local-first agent orchestration system. It does not start by taking over your machine. It starts in a conservative mode where you choose:

- what role your Ghost should act as
- what sources it may learn from
- what tools it may use
- how much autonomy it gets

The normal first experience is through the browser UI, called **Ghost Console**.

## Before you start

You need one of these:

- Docker, if you want the fastest path
- Python 3.11, 3.12, or 3.13, if you want a local install

For most users, start with Docker.

## Step 1: Start Ghost Chimera

### Docker

```bash
docker compose up --build
```

Open `http://localhost:8766/`.

### Local Python install

Linux or macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[gateway]"
ghostchimera console
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[gateway]"
ghostchimera console
```

If you want token-protected local access:

```bash
ghostchimera console --auth-token mysecrettoken
```

## Step 2: Check the Status tab

When the console opens, start on **Status**.

Look for:

- gateway running
- registered backends visible
- autonomy profile set to a reasonable default
- personal context toggle in the state you want

If you are new, keep the system conservative:

- leave high-impact autonomy off
- leave desktop control off
- keep personal context off until you explicitly configure it

## Step 3: Choose a Ghost Path

Open the **Path** tab.

Ghost Paths define what your Ghost becomes. A Ghost Path controls:

- role
- allowed learning sources
- tool domains
- eval expectations
- disclosure and approval posture

Examples:

- `manager-operator`
- `virtual-assistant`
- `marketing-specialist`
- `research-analyst`
- `ai-engineer-proxy`
- `security-analyst`
- `product-manager`
- `crm-operator`

The system now includes a large catalog of paths for operators across engineering, business, operations, support, security, analytics, recruiting, and administrative work.

For your first run:

1. Choose a profile such as `manager-operator` or `virtual-assistant`.
2. Keep `RAG first` as the training mode.
3. Keep the approval level at `supervised` or `assist`.
4. Click **Synthesize**.
5. Review the generated `ghost_blueprint`.
6. Click **Save Path**.

That saved path becomes the active role for future console and CLI flows.

## Step 4: Run your first objective

Open the **Run** tab.

Use one of the Quick Actions or enter your own objective.

Good first objectives:

- `Summarize my current workspace and identify the next safe action.`
- `Review my current setup and tell me what is configured and what is missing.`
- `Prepare a short status report based on the current workspace and memory.`

Then:

1. Click **Run**.
2. Read the output panel.
3. Check the run summary and run history.

If you want to observe how Ghost Chimera reasoned about the workflow, open the **Thinking** tab after the run.

## Step 5: Use the Thinking tab

The **Thinking** tab is an explainability view, not a claim of literal machine consciousness.

It shows the runtime stages Ghost Chimera is using to process your work:

- objective intake
- policy gate
- Ghost Path
- memory and RAG
- planner
- scheduler
- tool router
- verification
- audit handoff

Use it to answer:

- which layer is active
- whether MiniMind is ready or still guarded
- which path is shaping behavior
- how much capability coverage is available

This is useful when you want to understand why Ghost behaved a certain way without reading source code.

## Step 6: Add personal context only if you want it

Open **MiniMind** only when you want Ghost to use your private local context.

Personal MiniMind is opt-in. It does nothing until you grant consent.

Typical safe first setup:

1. Enable admin controls.
2. Allow files only for specific approved directories.
3. Optionally allow email only for exported `.eml` or `.mbox` files you choose.
4. Leave whole-machine crawl off unless you know you want it.
5. Click bootstrap to ingest the approved sources.

After that, Ghost can:

- build local memory
- prepare RAG handoff context
- generate local MiniMind JSONL training data if you allow training

Read the privacy details before enabling broader crawl:

- [PERSONAL_MINIMIND_PRIVACY.md](PERSONAL_MINIMIND_PRIVACY.md)

## Step 7: Use GitHub only if you need it

Open the **GitHub** tab if you want GitHub-connected planning.

GitHub integration is optional.

You can use Ghost Chimera without:

- GitHub sign-in
- GitHub tokens
- GitHub issue planning
- self-evolution preview

Ghost Chimera still works as a local orchestration runtime without GitHub.

### GitHub status and issue planning

If you already use:

- `GHOSTCHIMERA_GITHUB_TOKEN`
- `GITHUB_TOKEN`
- `gh` CLI authentication

the GitHub tab can inspect connection status and convert issues into Ghost objectives.

### GitHub sign-in in the UI

The browser UI also supports optional GitHub device-flow sign-in, but only when `GHOSTCHIMERA_GITHUB_CLIENT_ID` is configured by the operator running the console.

If that variable is not configured, sign-in stays disabled. That is expected.

## Step 8: Understand Self-Evolution correctly

The **Self-Evolution Preview** panel does not silently scrape repositories, install tools, or retrain the system.

It is intentionally guarded.

The preview exists to help the user inspect a possible intake plan for:

- verified skills
- MCP servers
- open-source reference materials

Before anything is allowed for dataset generation or fine-tuning, Ghost Chimera expects:

- explicit user approval
- license visibility
- commit or immutable revision tracking
- auditability

This is by design. Self-evolution in Ghost Chimera is meant to be governed, not invisible.

## Step 9: Use the other tabs as needed

- **Workspace**: add goals, evidence, and reflections
- **Memory**: ingest files, text, and email exports
- **Skills**: run registered skills directly
- **Browser**: fetch or inspect web pages
- **Security**: inspect audit and threat status
- **Jobs**: run autonomy jobs such as self-audit or repair-preview
- **Schedules**: create recurring jobs
- **Review**: run PR or diff review
- **Capabilities**: inspect the competitive capability matrix
- **Readiness**: see release and production checks

## A practical first workflow

If you just want one concrete path through the product, use this:

1. Start Ghost Console.
2. Choose `manager-operator` or `virtual-assistant`.
3. Save the path.
4. Run: `Summarize my current workspace and identify pending tasks.`
5. Add a goal in **Workspace**.
6. Add one or two evidence items.
7. Re-run the objective and compare the result.
8. If you need personal context, configure MiniMind with one approved folder and bootstrap it.
9. If you use GitHub, connect it and preview issue planning.

That gets you from an empty console to a meaningful local-first operator workflow without enabling risky behaviors.

## Common mistakes

- Enabling too much autonomy before verifying the path and policy
- Turning on broad personal crawl without reviewing consent scopes
- Assuming GitHub sign-in is required when it is optional
- Assuming self-evolution means automatic scraping or self-modification
- Treating Ghost Paths as labels instead of policy and source contracts

## Where to go next

- Fast setup: [quick-start.md](quick-start.md)
- Path details: [MULTIPURPOSE_GHOST_PATHS.md](MULTIPURPOSE_GHOST_PATHS.md)
- GitHub flow: [GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md](GITHUB_CONNECTED_AUTONOMOUS_ENGINEER.md)
- Privacy and consent: [PERSONAL_MINIMIND_PRIVACY.md](PERSONAL_MINIMIND_PRIVACY.md)
