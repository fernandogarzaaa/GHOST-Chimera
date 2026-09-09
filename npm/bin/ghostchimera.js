#!/usr/bin/env node
/* Ghost Chimera npm launcher: `ghostchimera ...` / `npx ghostchimera ...`.
 * Delegates to the Python backend (`python -m ghostchimera`). The backend
 * is pip-installed by postinstall; set GHOSTCHIMERA_SKIP_PIP=1 to skip that
 * check (e.g. Homebrew or manual pip installs).
 */
"use strict";

const { spawnSync } = require("child_process");

const CANDIDATES =
  process.platform === "win32" ? ["py -3", "python", "python3"] : ["python3", "python"];

function findPython() {
  for (const cmd of CANDIDATES) {
    const parts = cmd.split(" ");
    const probe = spawnSync(parts[0], [...parts.slice(1), "--version"], { encoding: "utf8" });
    if (probe.status === 0 && /Python 3\.(1[1-9]|[2-9][0-9])/.test(probe.stdout + probe.stderr)) {
      return parts;
    }
  }
  return null;
}

function main() {
  const python = findPython();
  if (!python) {
    console.error(
      "ghostchimera needs Python >= 3.11. Install it from https://www.python.org/downloads/ " +
        "or via `brew install python@3.12`, then re-run."
    );
    process.exit(1);
  }
  const args = process.argv.slice(2);
  if (process.env.GHOSTCHIMERA_SKIP_PIP !== "1") {
    const check = spawnSync(python[0], [...python.slice(1), "-c", "import ghostchimera"],
      { encoding: "utf8" });
    if (check.status !== 0) {
      console.error(
        "The ghostchimera Python package is not installed. Run `pip install ghostchimera` " +
          "(or `pip install \"ghostchimera[all]\"` for every backend), then re-run."
      );
      process.exit(1);
    }
  }
  const run = spawnSync(python[0], [...python.slice(1), "-m", "ghostchimera", ...args],
    { stdio: "inherit" });
  process.exit(run.status === null ? 1 : run.status);
}

if (require.main === module) main();

module.exports = { findPython };
