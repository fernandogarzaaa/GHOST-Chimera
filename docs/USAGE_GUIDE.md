# Ghost Chimera Usage Guide

Ghost Chimera is a **local-first AI assistant system** that runs on your own
machine, learns how you work, and helps inside the AI tools you already use.
You operate it almost entirely from **Ghost Console**, a point-and-click
browser dashboard — no terminal needed for day-to-day use.

If you have not installed it yet, start with [INSTALL.md](INSTALL.md), then
come back here. For the guided first run, see [USER_TUTORIAL.md](USER_TUTORIAL.md).

## What it is, in plain words

Most AI assistants are amnesiacs: every chat starts from zero, and anything
they learn about you lives on somebody else's server. Ghost Chimera flips
that around:

- It **watches your workflow** (with your permission) and remembers what
  matters: people, projects, decisions, preferences.
- It **prepares help before you ask** — meeting context, draft replies,
  relevant files — and hands that context to your AI agent.
- Everything it learns is stored **on your machine**, in a database you can
  inspect, export, or delete.
- It **asks before acting**. Reading and drafting are free; anything that
  changes the world waits for your approval unless you explicitly allow more.

## Use cases

**Personal productivity**
- *Morning briefing.* Ghost notices today's calendar, pulls the relevant
  email threads and notes, and has a summary waiting in the console.
- *Meeting prep.* Before a call, it assembles who is attending, what was
  promised last time, and which documents matter.
- *Inbox triage assistance.* It drafts replies from your history and your
  voice; you approve or edit — nothing sends itself.
- *Ask your own history.* "What did we decide about pricing in March?"
  searches your local memory, not the public web.

**Operators and small teams**
- *Virtual-assistant runs.* Connect Gmail/Slack once, then hand Ghost
  repeatable objectives (scheduling, follow-ups, status pulls) with an
  approval checkpoint before anything goes out.
- *Standing orders.* Encode a recurring responsibility once ("every Friday,
  summarize open threads"), enable it, audit it, disable it — from the
  dashboard.
- *Phone control.* Pair the console with your phone and approve runs,
  check status, or dictate notes from messaging apps.

**Developers and tinkerers**
- *Coding-agent memory.* Ghost plugs into Claude Code, OpenCode, Codex,
  Gemini CLI, and others, injecting project context automatically so you
  stop re-explaining your repo.
- *Local and free models.* Run fully offline with Ollama/llama.cpp, use
  OpenRouter, or use the OpenCode CLI's free models — swap providers
  without rewriting anything.
- *Computer use.* Let Ghost see and operate a dedicated browser (launched
  from the console, never your everyday profile) or the desktop, always
  behind explicit approval.

## How it works

Three ideas do almost all the work:

1. **The Stealth Loop watches and learns.** Every event — an email, a file
   change, a prompt you typed — flows through stages: understand it, update
   Ghost's picture of the world, recall similar past experience, predict
   what happens next, and decide: stay silent, remember it, or prepare help.
   Silence is the default. Most events produce nothing visible at all.
2. **Chimera Pilot does.** When you approve an objective, the Pilot compiles
   it into steps, picks a backend (deterministic, local model, browser,
   desktop…), runs each step with fallbacks, and records telemetry. You can
   dry-run any plan before it touches anything.
3. **Trust Runtime remembers the receipts.** Every run, approval, and outcome
   is journaled locally with replayable traces, so you can always answer
   "what did Ghost do, and why?"

## Why Ghost is an advantage

- **Memory that compounds.** A chatbot forgets you every session; Ghost's
  memory gets more useful the longer you use it.
- **Works inside your tools.** Instead of replacing Claude/OpenCode/your
  editor, Ghost injects context into them. One memory, every agent.
- **Approval-first autonomy.** Four levels — observe, prepare, inject, act —
  and you set the ceiling. Nothing consequential happens silently.
- **Local-first privacy.** Your data stays in a SQLite file on your disk.
  Cloud features are opt-in per connection, and secrets are encrypted.
- **Runs on free models.** Local Ollama/llama.cpp models cost nothing, and
  the OpenCode CLI bridge taps generous free tiers — no API bill required
  to get started.

## Your first 5 minutes in Ghost Console

1. Start Ghost (`ghostchimera console` or Docker) and open
   `http://localhost:8766/`.
2. The **Setup** group walks you through the wizard: pick an AI provider.
   Tip: choose **OpenCode CLI** or **Local** to start free.
3. Go to the **Operate → Run** tab, type an objective in plain words
   ("Summarize my inbox priorities"), and press run.
4. Open the **Operate → Memory** tab to see what Ghost remembered, and the
   **Advanced → Trust** tab to see the run journal with replay.
5. Say `/ghost status` inside any connected coding agent to see Ghost
   working there too.

## Everyday recipes

- **Prep for a meeting:** Run tab → "Prepare me for my 2pm with Priya" →
  review the brief → inject it into your agent with one click.
- **Tame a busy inbox:** connect Gmail once (Connect group), then ask for
  drafts, never auto-sends. Approve each reply.
- **Make Fridays automatic:** Advanced → Standing Orders → create "Friday
  thread summary", enable it, check the audit trail Monday.
- **Work from your phone:** pair remote control once, then approve runs
  and dictate notes from messaging apps.
- **Let it drive the browser:** Browser tab → Launch (debuggable Chrome
  starts, managed by Ghost) → describe the task → approve each action.
- **Hands-free notes:** hold to talk, Ghost transcribes locally and files
  the note where it belongs.

## The safety model, briefly

- **Default-deny execution.** Shell, network, desktop, and host self-edits
  are off until you arm them.
- **Approvals for consequences.** Drafts are free; sending, buying,
  deleting, and publishing wait for you.
- **Kill switch.** One click (or one file) freezes all automation
  immediately; every run can be replayed afterward.
- **You own the off switch and the data.** Pause Ghost any time; export
  or wipe memory from the console.

## Go deeper

- [USER_TUTORIAL.md](USER_TUTORIAL.md) — guided first run
- [INSTALL.md](INSTALL.md) — install matrix and extras
- [CUSTOM_AUTH.md](CUSTOM_AUTH.md) — OAuth, shared logins, secrets
- [REMOTE_CONTROL.md](REMOTE_CONTROL.md) — phone pairing
- [STANDING_ORDERS.md](STANDING_ORDERS.md) — reusable autonomy programs
- [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) — guardrails for
  always-on use
- [ARCHITECTURE.md](ARCHITECTURE.md) — how the layers fit together
