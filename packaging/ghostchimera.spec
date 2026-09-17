# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the Ghost Chimera desktop bundle.

One-dir (not one-file) so the console's static assets stay real files on
disk and `Path(__file__)` lookups keep working. Run from the repo root
after `pip install ".[gateway]"`:

    pyinstaller packaging/ghostchimera.spec --distpath dist-desktop --workpath build-desktop -y
"""

import os
import platform

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

APP_NAME = "GhostConsole"
# NOTE: spec-relative paths must use SPECPATH — PyInstaller resolves bare
# relative paths against the spec file's own directory, not the cwd.
ENTRY = os.path.join(SPECPATH, "ghost_console_entry.py")
ASSETS = os.path.join(SPECPATH, "assets")

# The skill registries discover modules dynamically (pkgutil + import_module),
# so every ghostchimera submodule must be collected explicitly.
hiddenimports = collect_submodules("ghostchimera")
datas = collect_data_files("ghostchimera", excludes=["**/__pycache__"])

# Optional heavy extras degrade gracefully at runtime (guarded imports), so
# they stay out of the bundle to keep download size sane.
excludes = [
    "torch",
    "transformers",
    "tokenizers",
    "llama_cpp",
    "pyqpanda3",
    "mcp",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "tkinter",
    "matplotlib",
]

_system = platform.system()
if _system == "Windows":
    icon = os.path.join(ASSETS, "ghost.ico")
elif _system == "Darwin":
    icon = os.path.join(ASSETS, "ghost.icns")
else:
    icon = None

a = Analysis(
    [ENTRY],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Windowed on Windows: no terminal flashes on double-click; the browser
    # auto-open carries the startup URL. Console kept on other platforms.
    console=_system != "Windows",
    disable_windowed_traceback=False,
    icon=icon if icon and os.path.exists(icon) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="GhostChimera",
)
