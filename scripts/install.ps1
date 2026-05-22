param(
    [string]$InstallDir = $(if ($env:GHOSTCHIMERA_INSTALL_DIR) { $env:GHOSTCHIMERA_INSTALL_DIR } else { Join-Path $HOME "ghost-chimera" }),
    [string]$Extras = $(if ($env:GHOSTCHIMERA_EXTRAS) { $env:GHOSTCHIMERA_EXTRAS } else { "gateway,mcp" }),
    [string]$Ref = $(if ($env:GHOSTCHIMERA_REF) { $env:GHOSTCHIMERA_REF } else { "main" }),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[ghostchimera] $Message"
}

function Find-Python {
    $candidates = @(
        @("py", "-3.13"),
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("python", ""),
        @("python3", "")
    )
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arg = $candidate[1]
        try {
            $versionText = if ($arg) {
                & $exe $arg -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            } else {
                & $exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            }
            if ($LASTEXITCODE -eq 0) {
                $parts = $versionText.Trim().Split(".")
                if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) {
                    return @{ Exe = $exe; Arg = $arg }
                }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Invoke-Python {
    param(
        [hashtable]$Python,
        [string[]]$Arguments
    )
    if ($Python.Arg) {
        & $Python.Exe $Python.Arg @Arguments
    } else {
        & $Python.Exe @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $($Arguments -join ' ')"
    }
}

$installPath = [System.IO.Path]::GetFullPath($InstallDir)
Write-Step "Install directory: $installPath"
Write-Step "Optional extras: $Extras"
Write-Step "GitHub ref: $Ref"

if ($DryRun) {
    Write-Step "Dry run only. No files will be created."
    exit 0
}

$python = Find-Python
if (-not $python) {
    throw "Python 3.11+ is required. Install it from https://www.python.org/downloads/ or run: winget install --id Python.Python.3.12 -e"
}

if (Test-Path (Join-Path $installPath ".git")) {
    Write-Step "Existing git checkout found. Updating $Ref."
    Push-Location $installPath
    try {
        git fetch origin
        git checkout $Ref
        git pull --ff-only origin $Ref
    } finally {
        Pop-Location
    }
} elseif (Test-Path (Join-Path $installPath "pyproject.toml")) {
    Write-Step "Existing source tree found. Reusing it."
} else {
    if ((Test-Path $installPath) -and (Get-ChildItem -LiteralPath $installPath -Force | Select-Object -First 1)) {
        throw "Install directory exists and is not a Ghost Chimera checkout: $installPath. Set GHOSTCHIMERA_INSTALL_DIR to an empty directory."
    }
    Write-Step "Downloading Ghost Chimera source archive."
    New-Item -ItemType Directory -Force -Path $installPath | Out-Null
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("ghostchimera-install-" + [System.Guid]::NewGuid().ToString("N"))
    $zipPath = Join-Path $tempRoot "source.zip"
    $extractPath = Join-Path $tempRoot "extract"
    New-Item -ItemType Directory -Force -Path $tempRoot, $extractPath | Out-Null
    try {
        $archiveUrl = "https://github.com/fernandogarzaaa/GHOST-Chimera/archive/refs/heads/$Ref.zip"
        Invoke-WebRequest -Uri $archiveUrl -OutFile $zipPath
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force
        $sourceRoot = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
        if (-not $sourceRoot) {
            throw "Downloaded archive did not contain a source directory."
        }
        Copy-Item -Path (Join-Path $sourceRoot.FullName "*") -Destination $installPath -Recurse -Force
    } finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Push-Location $installPath
try {
    Write-Step "Creating virtual environment."
    Invoke-Python -Python $python -Arguments @("-m", "venv", ".venv")
    $venvPython = Join-Path $installPath ".venv\Scripts\python.exe"
    $venvGhost = Join-Path $installPath ".venv\Scripts\ghostchimera.exe"

    Write-Step "Installing Python package dependencies."
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $venvPython -m pip install -e ".[${Extras}]"
    if ($LASTEXITCODE -ne 0) { throw "Ghost Chimera install failed" }

    Write-Step "Verifying CLI entrypoint."
    & $venvGhost doctor
    if ($LASTEXITCODE -ne 0) { throw "ghostchimera doctor failed" }

    Write-Host ""
    Write-Host "Ghost Chimera installed."
    Write-Host "Launch Ghost Console:"
    Write-Host "  cd `"$installPath`""
    Write-Host "  .\.venv\Scripts\ghostchimera.exe console"
    Write-Host ""
    Write-Host "Then open: http://127.0.0.1:8766/"
} finally {
    Pop-Location
}
