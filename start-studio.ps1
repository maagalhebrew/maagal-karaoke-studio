# Start the Hebrew Karaoke Studio and open it in the browser (the desktop shortcut runs this).
# If the server is already running, just open the browser. Closing this window stops the server.
$ErrorActionPreference = 'Stop'
$Url = 'http://127.0.0.1:8321/'
Set-Location -LiteralPath $PSScriptRoot
$Host.UI.RawUI.WindowTitle = 'Karaoke Studio server'
# ffmpeg and Node come from the installed PATH (a shortcut may start with an older copy of it)
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

function Test-Studio {
    try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

if (Test-Studio) {
    Write-Host 'The studio is already running; opening it.'
    Start-Process $Url
    Start-Sleep -Seconds 2
    exit
}

# Open the browser once the server answers (it takes a few seconds to load).
Start-Job -ArgumentList $Url -ScriptBlock {
    param($Url)
    for ($i = 0; $i -lt 60; $i++) {
        try { Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $Url; return } catch { Start-Sleep -Seconds 1 }
    }
} | Out-Null

Write-Host 'Starting the Karaoke Studio. Keep this window open while you use it; close it to stop the server.'
& (Join-Path $PSScriptRoot '.venv\Scripts\karaoke.exe') serve
Write-Host ''
Read-Host 'The server stopped. Press Enter to close this window'
