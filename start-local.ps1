# Start the local browser studio on this computer (http://127.0.0.1:8321).
# First run: create .venv, install the Python libraries, build the editor if needed.
# Songs, uploads and the library database stay inside this folder. This script does not
# write to Documents, Desktop, or any other synced folder, and it does not build an installer.
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root
$Host.UI.RawUI.WindowTitle = 'Karaoke Studio server'
$Url = 'http://127.0.0.1:8321/'

# A shortcut can start with a stale PATH. Pick up Python, Node and ffmpeg installed after the last logon.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
# Leave KARAOKE_HOME unset so songs stay in this clone (songs\, inbox\, data\).

function Fail($Message) {
    Write-Host $Message -ForegroundColor Red
    Write-Host ''
    Read-Host 'Press Enter to close this window'
    exit 1
}

function Test-Studio {
    try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

if (Test-Studio) {
    Write-Host 'The studio is already running; opening it.'
    Start-Process $Url
    Start-Sleep -Seconds 2
    exit 0
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail "The Python launcher (py) was not found.`nInstall Python 3.11, then run this again:`n  winget install Python.Python.3.11"
}
& py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    Fail "Python 3.11 is required.`nInstall it with:`n  winget install Python.Python.3.11"
}

$venvPy = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Host 'Creating .venv with Python 3.11...'
    & py -3.11 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create .venv.' }
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Fail 'Could not upgrade pip.' }
}

function Test-Module($Name) {
    & $venvPy -c "import $Name" 2>$null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-Module 'torch')) {
    Write-Host 'Installing PyTorch with CUDA 12.6 (first run only, a few GB). This does not download the song models.'
    & $venvPy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
    if ($LASTEXITCODE -ne 0) { Fail 'PyTorch install failed. Check the messages above.' }
}

$stamp = Join-Path $Root '.venv\.karaoke-deps-ok'
$pyproject = Join-Path $Root 'backend\pyproject.toml'
$depsStale = -not (Test-Path -LiteralPath $stamp)
if (-not $depsStale) {
    $depsStale = (Get-Item -LiteralPath $pyproject).LastWriteTimeUtc -gt (Get-Item -LiteralPath $stamp).LastWriteTimeUtc
}
if ($depsStale -or -not (Test-Module 'karaoke')) {
    Write-Host 'Installing the studio Python libraries...'
    # Quote the extra so PowerShell does not treat [dev] as a wildcard.
    & $venvPy -m pip install -e "backend[dev]"
    if ($LASTEXITCODE -ne 0) { Fail 'Python library install failed. Check the messages above.' }
    Set-Content -LiteralPath $stamp -Value (Get-Date).ToUniversalTime().ToString('o') -Encoding ascii
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host 'ffmpeg was not found. The editor will still open, but adding a song needs ffmpeg.'
    Write-Host '  winget install Gyan.FFmpeg'
}

function Test-FrontendNeedsBuild {
    $index = Join-Path $Root 'frontend\dist\index.html'
    if (-not (Test-Path -LiteralPath $index)) { return $true }
    $built = (Get-Item -LiteralPath $index).LastWriteTimeUtc
    $watch = @(
        (Join-Path $Root 'frontend\src'),
        (Join-Path $Root 'frontend\index.html'),
        (Join-Path $Root 'frontend\package.json'),
        (Join-Path $Root 'frontend\package-lock.json'),
        (Join-Path $Root 'frontend\vite.config.ts'),
        (Join-Path $Root 'frontend\tsconfig.json')
    )
    foreach ($item in $watch) {
        if (-not (Test-Path -LiteralPath $item)) { continue }
        $info = Get-Item -LiteralPath $item
        $files = if ($info.PSIsContainer) { Get-ChildItem -LiteralPath $item -Recurse -File } else { $info }
        foreach ($file in $files) {
            if ($file.LastWriteTimeUtc -gt $built) { return $true }
        }
    }
    return $false
}

if (Test-FrontendNeedsBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail "Node.js is required to build the editor.`nInstall Node.js 24 LTS, then run this again:`n  winget install OpenJS.NodeJS.LTS"
    }
    Write-Host 'Building the editor...'
    Push-Location (Join-Path $Root 'frontend')
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed in frontend.' }
        & npm run build
        if ($LASTEXITCODE -ne 0) { Fail 'The editor build failed.' }
    } finally {
        Pop-Location
    }
}

# Open the browser once the server answers (loading takes a few seconds).
Start-Job -ArgumentList $Url -ScriptBlock {
    param($Url)
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            Start-Process $Url
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
} | Out-Null

Write-Host 'Starting the Karaoke Studio at http://127.0.0.1:8321/'
Write-Host 'Keep this window open while you use it. Close it to stop the server.'
Write-Host 'Your songs stay in this folder: songs\, inbox\, data\karaoke.db'
& $venvPy -m karaoke.cli serve
Write-Host ''
Read-Host 'The server stopped. Press Enter to close this window'
