# Desktop distribution (Windows installer + macOS app)

End-user goal: **no terminal**. A user downloads one file, double-clicks it,
and Ghost Console opens in their browser.

```
packaging/
  README.md                  this file — the whole story
  ghost_console_entry.py     frozen-app entry point (starts console, opens browser)
  ghostchimera.spec          PyInstaller build (one-dir bundle, no terminal window on Windows)
  assets/
    generate_icons.py        draws the Ghost mark -> icon.png / ghost.ico / ghost.icns
  windows/
    ghost-chimera.iss        Inno Setup script -> GhostChimeraSetup-<version>.exe
    build-windows.ps1        one-command local build (PyInstaller + optional Inno)
  macos/
    Info.plist               bundle metadata template (version stamped at build)
    build-macos-app.sh       one-command local build (.app + DMG via hdiutil)
```

## How it works

1. **PyInstaller** freezes the already-installed `ghostchimera` package plus
   the `ghost_console_entry.py` launcher into a folder (`dist-desktop/`).
   The launcher calls `run_console()` with defaults: localhost only,
   browser auto-open, and — thanks to the gateway's auto port selection —
   the next free ports when 8765/8766 are taken.
2. **Windows**: Inno Setup wraps the folder into `GhostChimeraSetup-<v>.exe`
   with Start Menu + optional desktop shortcuts and an uninstaller.
3. **macOS**: the folder is placed inside `Ghost Chimera.app`
   (`Contents/MacOS`, `Contents/Resources`, `Info.plist`), then packed into
   a drag-to-Applications DMG.
4. **Releases**: `.github/workflows/desktop.yml` builds both artifacts on
   every published GitHub Release and attaches them to the release.

## What is deliberately NOT in this iteration

- **Code signing / notarization.** CI produces unsigned artifacts. Windows
  SmartScreen will warn; macOS Gatekeeper will block the unsigned .app
  until the user right-clicks -> Open. Signing (EV cert / Apple Developer
  ID + `notarytool`) is an operator step documented in `docs/DESKTOP_APP.md`.
- **Auto-update.** The app does not self-update; users re-run the installer.
- **Heavy ML extras.** torch/transformers/llama.cpp/MCP/voice/quantum are
  excluded from the bundle to keep it small. They degrade gracefully at
  runtime (missing extras never crash), and `ghostchimera doctor` reports
  exactly what is live.

## Versioning

`ghostchimera.__version__` is the single source of truth. Build scripts read
it from the installed package; the Inno script takes it as
`/DAppVersion=<v>`; the macOS script stamps `Info.plist` from the
`GHOSTCHIMERA_VERSION` env var (default: package version).
