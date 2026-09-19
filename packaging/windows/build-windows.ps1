# Build the Ghost Chimera Windows bundle (and installer when Inno is present).
# Run from the repo root:
#   powershell -ExecutionPolicy Bypass -File packaging/windows/build-windows.ps1
# Requires: Python 3.11+, Inno Setup 6 (optional, for the Setup exe).

$ErrorActionPreference = "Stop"
$root = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Set-Location $root

$version = (python -c "import ghostchimera; print(ghostchimera.__version__)")
Write-Output "Ghost Chimera $version"

python -m pip install --upgrade pip
python -m pip install ".[gateway]" pyinstaller pillow

python packaging/assets/generate_icons.py --out packaging/assets

pyinstaller packaging/ghostchimera.spec --distpath dist-desktop --workpath build-desktop -y

$exe = Join-Path $root "dist-desktop/GhostChimera/GhostConsole.exe"
if (-not (Test-Path $exe)) { throw "Build failed: $exe not found" }
Write-Output "Bundle ready: $exe"

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($iscc) {
    & $iscc packaging/windows/ghost-chimera.iss /DAppVersion=$version
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
    $installer = Join-Path $root "dist-desktop/installer/GhostChimeraSetup-$version.exe"
    if (-not (Test-Path -LiteralPath $installer)) {
        throw "Build failed: $installer not found"
    }
    Write-Output "Installer written to dist-desktop/installer/"
} else {
    Write-Output "Inno Setup (iscc) not on PATH — bundle built, installer skipped."
    Write-Output "Install Inno Setup 6, then run: iscc packaging/windows/ghost-chimera.iss /DAppVersion=$version"
}
