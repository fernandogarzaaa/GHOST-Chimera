# Running Ghost Chimera

This guide shows the fastest way to run Ghost Chimera and a local Python setup if you do not want to use Docker.

## Fastest path: run the browser console with Docker

1. Install Docker and Docker Compose.
2. Open a terminal in `/home/runner/work/GHOST-Chimera/GHOST-Chimera`.
3. Start the app:

   ```bash
   docker compose up --build
   ```

4. Wait for the image build and container startup to finish.
5. Open `http://localhost:8766/` in your browser.
6. Use the Ghost Console web UI.

### What Docker starts

- The browser console on port `8766`
- The gateway service on port `8765`
- Production guardrail environment variables from `docker-compose.yml`
- Persistent state mounted at `/data`

## Local Python setup (without Docker)

1. Install Python `3.11`, `3.12`, or `3.13`.
2. Open a terminal in `/home/runner/work/GHOST-Chimera/GHOST-Chimera`.
3. Create a virtual environment:

   ```bash
   python -m venv .venv
   ```

4. Activate it:

   macOS/Linux:

   ```bash
   source .venv/bin/activate
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

5. Upgrade pip:

   ```bash
   python -m pip install --upgrade pip
   ```

6. Install the base package:

   ```bash
   python -m pip install -e .
   ```

7. Install console support:

   ```bash
   python -m pip install -e ".[gateway]"
   ```

8. Run the initial setup and health checks:

   ```bash
   ghostchimera setup
   ghostchimera doctor
   ```

9. Start the browser console:

   ```bash
   ghostchimera console
   ```

   If you do not want Ghost Chimera to open the browser automatically:

   ```bash
   ghostchimera console --no-open
   ```

10. Open `http://localhost:8766/` in your browser.

## Useful first commands

After the project is running, these commands are good sanity checks:

```bash
ghostchimera --config-show
chimera-pilot status --include-deterministic-backend
chimera-pilot run "retrieve memory about project" --include-deterministic-backend
```

## Optional extras

Install these only if you need them:

```bash
python -m pip install -e ".[mcp]"
python -m pip install -e ".[local]"
python -m pip install -e ".[minimind]"
```

- `.[mcp]` adds MCP integration
- `.[local]` adds llama.cpp local model support
- `.[minimind]` adds the MiniMind adapter

## Exposing the console beyond localhost

If the console will be reachable by other machines, require a token:

```bash
ghostchimera console --auth-token <token>
```

The browser UI will prompt for the token and send it on API requests.
