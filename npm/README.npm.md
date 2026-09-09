# ghostchimera (npm)

Background AI infrastructure — Ghost Chimera with one command:

```bash
npm install -g ghostchimera   # global CLI: `ghostchimera` + `ghost`
npx ghostchimera doctor       # no install: runs the Console health check
```

Requires **Python ≥ 3.11**. The postinstall step pip-installs the matching
`ghostchimera` Python backend automatically (skip with
`GHOSTCHIMERA_SKIP_PIP=1` if you manage Python yourself, e.g. Homebrew).

```bash
ghostchimera doctor           # health checks
ghostchimera start            # Ghost Console (http://127.0.0.1:8766/)
ghostchimera --help           # everything else
```

Full docs: https://github.com/fernandogarzaaa/GHOST-Chimera
Backend source: `pip install ghostchimera` (PyPI) · MIT license.
