; Ghost Chimera — Inno Setup 6 script (Windows installer).
; Build from the repo root after packaging/windows/build-windows.ps1:
;   iscc packaging/windows/ghost-chimera.iss /DAppVersion=0.4.0-beta
; Paths below are relative to this file's directory.

#define AppVersion "0.0.0-dev"

[Setup]
AppId={{3F2A1B4C-7D9E-4A5F-8C2B-6E1D0F9A3B7C}
AppName=Ghost Chimera
AppVersion={#AppVersion}
AppPublisher=Fernando Garza
AppPublisherURL=https://github.com/fernandogarzaaa/GHOST-Chimera
DefaultDirName={autopf}\GhostChimera
DefaultGroupName=Ghost Chimera
OutputDir=..\..\dist-desktop\installer
OutputBaseFilename=GhostChimeraSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\GhostConsole.exe
; Unsigned build: SmartScreen will warn until an EV cert signs the Setup exe.
; SignTool=...

[Files]
Source: "..\..\dist-desktop\GhostChimera\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Ghost Console"; Filename: "{app}\GhostConsole.exe"; Comment: "Start Ghost Console in your browser"
Name: "{group}\Uninstall Ghost Chimera"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Ghost Console"; Filename: "{app}\GhostConsole.exe"; Tasks: desktopicon; Comment: "Start Ghost Console in your browser"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\GhostConsole.exe"; Description: "Launch Ghost Console now"; Flags: nowait postinstall skipifsilent
