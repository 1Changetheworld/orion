# orion-install-fresh.ps1 — wipe + reinstall Orion on Windows.
#
# Detects the first removable USB, wipes any prior Orion state from
# both the host's home directory and the USB, clones a fresh copy of
# the Orion repo onto the USB, and runs Install Orion.bat.
#
# Run via:
#   iwr https://raw.githubusercontent.com/1Changetheworld/orion/master/scripts/orion-install-fresh.ps1 | iex
#
# Or download and run directly:
#   .\orion-install-fresh.ps1
#
# Preserves AI auth (Claude / Codex / Gemini logins are not touched).

# ---- 1. Find the USB ----
$drives = Get-Volume | Where-Object { $_.DriveType -eq 'Removable' -and $_.DriveLetter }
$drives = $drives | Sort-Object DriveLetter
if (-not $drives) {
    Write-Host "No removable USB drive detected. Plug it in and try again." -ForegroundColor Red
    return
}
$USB = "$($drives[0].DriveLetter):"
Write-Host "USB drive: $USB" -ForegroundColor Cyan

# ---- 2. Wipe Orion (host home + USB-side) ----
$ErrorActionPreference = 'SilentlyContinue'
Write-Host "Wiping prior Orion state..." -ForegroundColor Yellow

$wipePaths = @(
    "$env:USERPROFILE\.orion",
    "$env:USERPROFILE\.orion-bin",
    "$env:USERPROFILE\orion",
    "$env:USERPROFILE\Desktop\orion-test",
    "$env:USERPROFILE\CLAUDE.md",
    "$env:USERPROFILE\AGENTS.md",
    "$env:USERPROFILE\GEMINI.md",
    "$env:USERPROFILE\ORION-CONTEXT.md",
    "$USB\orion",
    "$USB\.orion",
    "$USB\CLAUDE.md",
    "$USB\AGENTS.md",
    "$USB\GEMINI.md",
    "$USB\ORION-CONTEXT.md"
)

foreach ($p in $wipePaths) {
    if (Test-Path $p) {
        $item = Get-Item $p -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            cmd /c "rmdir `"$p`"" 2>$null
        } else {
            Remove-Item $p -Recurse -Force
        }
        Write-Host "  removed: $p" -ForegroundColor DarkGray
    }
}

# Strip orion-brain from each CLI's MCP config (preserves auth)
$mcpJsons = @(
    "$env:USERPROFILE\.claude.json",
    "$env:USERPROFILE\.codex\mcp.json",
    "$env:USERPROFILE\.gemini\settings.json"
)
foreach ($cfg in $mcpJsons) {
    if (Test-Path $cfg) {
        try {
            $j = Get-Content $cfg -Raw | ConvertFrom-Json
            if ($j.mcpServers.'orion-brain') {
                $j.mcpServers.PSObject.Properties.Remove('orion-brain')
                $j | ConvertTo-Json -Depth 50 | Set-Content $cfg -Encoding UTF8
                Write-Host "  cleaned orion-brain from $cfg" -ForegroundColor DarkGray
            }
        } catch { }
    }
}

# Codex config.toml — strip [mcp_servers.orion-brain] block(s)
$codexToml = "$env:USERPROFILE\.codex\config.toml"
if (Test-Path $codexToml) {
    $kept = @()
    $inOrion = $false
    foreach ($line in Get-Content $codexToml) {
        if ($line -match '^\[mcp_servers\.orion-brain') {
            $inOrion = $true
            continue
        }
        if ($inOrion -and $line -match '^\[' -and $line -notmatch '^\[mcp_servers\.orion-brain') {
            $inOrion = $false
        }
        if (-not $inOrion) { $kept += $line }
    }
    $kept | Set-Content $codexToml -Encoding UTF8
    Write-Host "  cleaned orion-brain from $codexToml" -ForegroundColor DarkGray
}

# Strip orion-bin from User PATH (the launcher, not the brain)
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($userPath -like "*orion-bin*") {
    $newPath = ($userPath -split ';' | Where-Object { $_ -notmatch 'orion-bin' }) -join ';'
    [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
    Write-Host "  cleaned .orion-bin from User PATH" -ForegroundColor DarkGray
}

# Strip Orion's SessionStart hook from Claude settings (caught 2026-05-06)
# A stale hook pointing at a wiped install path makes Claude print a
# bash error every session start. Remove our entry; preserve others.
$claudeSettings = "$env:USERPROFILE\.claude\settings.json"
if (Test-Path $claudeSettings) {
    try {
        $j = Get-Content $claudeSettings -Raw | ConvertFrom-Json
        if ($j.hooks -and $j.hooks.SessionStart) {
            $kept = @()
            foreach ($entry in $j.hooks.SessionStart) {
                $isOrion = $false
                foreach ($h in $entry.hooks) {
                    if ($h.command -like "*orion_first_meeting*") { $isOrion = $true }
                }
                if (-not $isOrion) { $kept += $entry }
            }
            $j.hooks.SessionStart = @($kept)
            $j | ConvertTo-Json -Depth 50 | Set-Content $claudeSettings -Encoding UTF8
            Write-Host "  cleaned Orion SessionStart hook from $claudeSettings" -ForegroundColor DarkGray
        }
    } catch { }
}

Write-Host "Wipe complete. AI auth preserved." -ForegroundColor Green

# ---- 3. Clone Orion onto the USB ----
$ErrorActionPreference = 'Continue'
Write-Host ""
Write-Host "Cloning Orion onto $USB\orion ..." -ForegroundColor Cyan

$gitOk = git --version 2>$null
if (-not $gitOk) {
    Write-Host "git is not installed. Install Git for Windows first: https://git-scm.com/download/win" -ForegroundColor Red
    return
}

git clone https://github.com/1Changetheworld/orion.git "$USB\orion"
if ($LASTEXITCODE -ne 0) {
    Write-Host "git clone failed (rc=$LASTEXITCODE). Check your network and try again." -ForegroundColor Red
    return
}

# ---- 4. Run the install ----
Set-Location "$USB\orion"
Write-Host ""
Write-Host "Running Install Orion.bat from $USB\orion ..." -ForegroundColor Cyan
Write-Host ""

& ".\Install Orion.bat"
