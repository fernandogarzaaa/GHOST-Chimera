/* postinstall: ensure the Python backend exists (pip install ghostchimera).
 * Skipped when GHOSTCHIMERA_SKIP_PIP=1 or NO_COLOR-free CI opts out.
 * Warns instead of failing so `npm install -g` stays resilient when the
 * user manages Python separately (pyenv, Homebrew, system pip).
 */
"use strict";

const { spawnSync } = require("child_process");
const { findPython } = require("./bin/ghostchimera.js");

const PKG_VERSION = require("./package.json").version;

function main() {
  if (process.env.GHOSTCHIMERA_SKIP_PIP === "1") {
    console.log("[ghostchimera] Skipping Python bootstrap (GHOSTCHIMERA_SKIP_PIP=1).");
    return;
  }
  const python = findPython();
  if (!python) {
    console.warn("[ghostchimera] Python >= 3.11 not found; install it, then run `pip install ghostchimera`.");
    return;
  }
  const check = spawnSync(python[0], [...python.slice(1), "-c", "import ghostchimera"],
    { encoding: "utf8" });
  if (check.status === 0) {
    console.log("[ghostchimera] Python backend already present.");
    return;
  }
  console.log(`[ghostchimera] Installing full Python backend (pip install "ghostchimera[all]==${PKG_VERSION}") ...`);
  const full = spawnSync(python[0],
    [...python.slice(1), "-m", "pip", "install", `ghostchimera[all]==${PKG_VERSION}`],
    { stdio: "inherit" });
  if (full.status !== 0) {
    console.warn("[ghostchimera] Full install did not complete (often a heavy " +
      "platform-specific extra like torch/CUDA). Falling back to the lean core ...");
    const lean = spawnSync(python[0],
      [...python.slice(1), "-m", "pip", "install", `ghostchimera==${PKG_VERSION}`],
      { stdio: "inherit" });
    if (lean.status !== 0) {
      console.warn("[ghostchimera] pip install did not complete. Run it manually: " +
        'pip install "ghostchimera[all]"');
      return;
    }
  }
  console.log("[ghostchimera] Done. Try: ghostchimera doctor");
}

main();
