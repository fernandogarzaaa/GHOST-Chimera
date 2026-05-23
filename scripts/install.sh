#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${GHOSTCHIMERA_INSTALL_DIR:-"$HOME/ghost-chimera"}"
EXTRAS="${GHOSTCHIMERA_EXTRAS:-all}"
REF="${GHOSTCHIMERA_REF:-main}"
DRY_RUN="${GHOSTCHIMERA_DRY_RUN:-0}"

step() {
  printf '[ghostchimera] %s\n' "$1"
}

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
      then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [ -z "$PYTHON_BIN" ]; then
  printf 'Python 3.11+ is required. Install Python first, then rerun this script.\n' >&2
  exit 1
fi

INSTALL_DIR="$("$PYTHON_BIN" - <<PY
from pathlib import Path
print(Path("$INSTALL_DIR").expanduser().resolve())
PY
)"

step "Install directory: $INSTALL_DIR"
step "Runtime profile: $EXTRAS"
step "GitHub ref: $REF"

if [ "$DRY_RUN" = "1" ]; then
  step "Dry run only. No files will be created."
  exit 0
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  step "Existing git checkout found. Updating $REF."
  git -C "$INSTALL_DIR" fetch origin
  git -C "$INSTALL_DIR" checkout "$REF"
  git -C "$INSTALL_DIR" pull --ff-only origin "$REF"
elif [ -f "$INSTALL_DIR/pyproject.toml" ]; then
  step "Existing source tree found. Reusing it."
else
  if [ -d "$INSTALL_DIR" ] && [ "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 | head -n 1)" ]; then
    printf 'Install directory exists and is not a Ghost Chimera checkout: %s\n' "$INSTALL_DIR" >&2
    printf 'Set GHOSTCHIMERA_INSTALL_DIR to an empty directory.\n' >&2
    exit 1
  fi
  step "Downloading Ghost Chimera source archive."
  mkdir -p "$INSTALL_DIR"
  "$PYTHON_BIN" - "$REF" "$INSTALL_DIR" <<'PY'
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ref = sys.argv[1]
install_dir = Path(sys.argv[2])
url = f"https://github.com/fernandogarzaaa/GHOST-Chimera/archive/refs/heads/{ref}.zip"
with tempfile.TemporaryDirectory(prefix="ghostchimera-install-") as tmp:
    tmp_path = Path(tmp)
    zip_path = tmp_path / "source.zip"
    extract_path = tmp_path / "extract"
    urllib.request.urlretrieve(url, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_path)
    roots = [item for item in extract_path.iterdir() if item.is_dir()]
    if not roots:
        raise SystemExit("Downloaded archive did not contain a source directory.")
    for item in roots[0].iterdir():
        target = install_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)
PY
fi

cd "$INSTALL_DIR"
step "Creating virtual environment."
"$PYTHON_BIN" -m venv .venv

VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"
VENV_GHOST="$INSTALL_DIR/.venv/bin/ghostchimera"

step "Installing full Python runtime dependencies."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e ".[${EXTRAS}]"

step "Verifying CLI entrypoint."
"$VENV_GHOST" doctor

printf '\nGhost Chimera installed.\n'
printf 'Launch Ghost Console:\n'
printf '  cd "%s"\n' "$INSTALL_DIR"
printf '  .venv/bin/ghostchimera console\n\n'
printf 'Then open: http://127.0.0.1:8766/\n'
