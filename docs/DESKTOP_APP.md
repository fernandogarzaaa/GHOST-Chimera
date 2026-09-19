# Ghost Chimera Desktop App (no terminal needed)

Download one file, double-click it, and Ghost Console opens in your browser.
No Python, no terminal, no environment variables.

## Install

1. Open the
   [latest release](https://github.com/fernandogarzaaa/GHOST-Chimera/releases).
2. Download the file for your machine:
   - **Windows:** `GhostChimeraSetup-<version>.exe`
   - **macOS:** `GhostChimera-<version>-macOS.dmg`
3. Run it:
   - **Windows:** double-click the Setup exe, accept the defaults, then open
     **Ghost Console** from the Start Menu (optional desktop shortcut).
   - **macOS:** open the DMG, drag **Ghost Chimera** into **Applications**,
     then open it from Applications or Spotlight.

Ghost Console opens automatically at a local address such as
`http://127.0.0.1:8766/`. If those ports are busy, the app silently picks
the next free ones and opens the right URL — you never configure ports.

## First run

Follow the on-screen Operator Workbench checklist:

1. Connect a model provider (choose **OpenCode CLI** or **Local** to start free).
2. Run the readiness check.
3. Connect integrations as needed.

Your data lives on your machine (`~/.ghostchimera`); uninstalling removes
the app but keeps your data unless you delete that folder too.

## Security notes (read before trusting the download)

- These builds are currently **unsigned**. Windows SmartScreen will warn
  about the Setup exe; on macOS, first launch an unsigned .app with
  right-click -> **Open** instead of double-click. Signing and Apple
  notarization are planned operator steps before any wide distribution.
- The app only listens on **localhost** — nothing is exposed to your network.
- Shell, network, desktop control, and personal context stay **off** until
  you explicitly enable them in the Console.

## For maintainers

The whole pipeline lives in [`packaging/`](../packaging/README.md):
PyInstaller bundle -> Inno Setup (Windows) / .app + DMG (macOS), built by
`.github/workflows/desktop.yml` on every published release.
