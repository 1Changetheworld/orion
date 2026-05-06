# orion install -- Windows bootstrapper.
#
# Mirrors install.sh for Windows. Does what a new user needs on a fresh machine:
#   1. Verify Python 3.10+ is available (install via winget if missing)
#   2. Create a venv inside the repo and install pip deps
#   3. Offer to install Ollama (optional, for free local fuel)
#   4. Write an `orion.cmd` launcher to %USERPROFILE%\.orion-bin and add to user PATH
#   5. Run the setup wizard (orion_setup_chat.py) and preflight
#
# What this script does NOT do:
#   - Run as administrator unless absolutely necessary
#   - Modify system PATH (only user PATH, scoped to current user)
#   - Install AI CLIs (Claude, Codex, Gemini have their own installers)
#
# Usage (in PowerShell, after cloning the repo):
#   cd orion
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# Or for users who already allow scripts:
#   .\install.ps1
#
# Tested on: Windows 11 (PowerShell 5.1 and 7+).

$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['*:Encoding'] = 'utf8'

# ----------------------------------------------------------------
# Helpers — parity with install.sh (info/ok/warn/fail)
# ----------------------------------------------------------------

function Say  { param($m); Write-Host $m }
function Info { param($m); Write-Host $m -ForegroundColor Cyan }
function Ok   { param($m); Write-Host "[OK]   $m" -ForegroundColor Green }
function Warn { param($m); Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail { param($m); Write-Host "[FAIL] $m" -ForegroundColor Red }
function Ask  {
    param([string]$Prompt)
    # Drain any queued keystrokes so Read-Host blocks on fresh input.
    # Without this, paste buffers / typeahead consume prompts immediately
    # and Read-Host returns "" — caught in 2026-04-29 dog-food install
    # where every prompt was silently skipped.
    try {
        while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) }
    } catch { }
    $resp = Read-Host -Prompt "[?] $Prompt"
    return $resp
}

$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }

Say ""
Info "=== Orion install (Windows) ==="
Info "Repo: $ScriptDir"
Say ""

# ----------------------------------------------------------------
# Step 1: Python 3.10+ — winget install if missing
# ----------------------------------------------------------------

$pythonCmd = $null
foreach ($candidate in @('py', 'python3', 'python')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        try {
            $verOutput = & $candidate --version 2>&1
            if ($verOutput -match 'Python\s+(\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                    $pythonCmd = $candidate
                    Ok "Python found: $verOutput (using '$candidate')"
                    break
                }
            }
        } catch { }
    }
}

if (-not $pythonCmd) {
    Warn "Python 3.10+ not found."
    $resp = Ask "Install Python 3.12 via winget? [y/N]"
    if ($resp -match '^[Yy]') {
        $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $wingetCheck) {
            Fail "winget is not available. Install Python manually from https://python.org and re-run this script."
            exit 1
        }
        Info "Installing Python 3.12 via winget (this may take a minute)..."
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        Warn "Python installed. Open a NEW PowerShell window (so PATH refreshes), cd back here, and re-run install.ps1."
        exit 0
    } else {
        Fail "Python 3.10+ is required. Install it and re-run."
        exit 1
    }
}

# ----------------------------------------------------------------
# Step 2: Python venv + pip deps
# ----------------------------------------------------------------

$VenvDir = Join-Path $ScriptDir '.venv'
if (-not (Test-Path $VenvDir)) {
    Info "Creating venv at $VenvDir"
    & $pythonCmd -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Fail "venv creation failed"
        exit 1
    }
}

$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPip    = Join-Path $VenvDir 'Scripts\pip.exe'

if (-not (Test-Path $VenvPython)) {
    Fail "venv Python not found at $VenvPython"
    exit 1
}

Info "Upgrading pip in venv..."
& $VenvPython -m pip install --upgrade pip --quiet

$reqFile = Join-Path $ScriptDir 'requirements.txt'
if (Test-Path $reqFile) {
    Info "Installing pip deps from requirements.txt..."
    # --quiet suppresses the per-package wall of text. Failures still
    # surface because pip prints errors regardless of -q. Matches the
    # signal-to-noise the user expects from official installers.
    & $VenvPip install -r $reqFile --quiet
    if ($LASTEXITCODE -ne 0) {
        Fail "pip install failed. Re-run with verbose: $VenvPip install -r $reqFile"
        exit 1
    }
    Ok "Python deps installed in venv"
} else {
    Warn "No requirements.txt found; skipping dep install"
}

# ----------------------------------------------------------------
# Step 3: Optional Ollama install
# ----------------------------------------------------------------

$ollamaCheck = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaCheck) {
    # Soft offer — Ollama is one fuel option among many, not a default.
    # The wizard handles fuel selection; the install script just makes
    # the option available if the user already wants it.
    Say ""
    Say "  (Optional) Ollama runs models locally — useful for offline / private fuel."
    $resp = Ask "Install Ollama? [y/N, default N]"
    if ($resp -match '^[Yy]') {
        $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
        if ($wingetCheck) {
            Info "Installing Ollama via winget..."
            winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
            Ok "Ollama installed (open a new shell to use it)"
        } else {
            Warn "winget not available. Install Ollama manually from https://ollama.com/download"
        }
    }
} else {
    Ok "Ollama already installed"
}

# Model selection — only if Ollama is now callable
$ollamaCheck = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCheck) {
    Say ""
    Say "  Orion chat needs a tool-capable model. Pick one:"
    Say "    1) qwen3:8b        ~5 GB  -- recommended, works on 8GB+ RAM"
    Say "    2) qwen3:14b       ~9 GB  -- best quality, 16GB+ RAM"
    Say "    3) llama3.1:8b     ~5 GB  -- Meta, similar size to qwen3:8b"
    Say "    4) deepseek-r1:7b  ~4.7 GB -- reasoning focus"
    Say "    5) phi3:mini       ~2.2 GB -- small, but chat mode won't work (no tool calls)"
    Say "    6) skip            -- pull a model later with: ollama pull <name>"
    $resp = Ask "Pull which model? [1-6]"
    switch -Regex ($resp) {
        '^1$|^$' { ollama pull qwen3:8b }
        '^2$'    { ollama pull qwen3:14b }
        '^3$'    { ollama pull llama3.1:8b }
        '^4$'    { ollama pull deepseek-r1:7b }
        '^5$'    { ollama pull phi3:mini; Warn "phi3:mini installed but chat mode won't work. Pull qwen3:8b to enable chat." }
        default  { Say "  Skipped. Pull later with: ollama pull qwen3:8b" }
    }
}

# ----------------------------------------------------------------
# Step 4: Write orion.cmd launcher INSIDE the repo, junction from home
# ----------------------------------------------------------------
#
# The launcher physically lives at <repo>/bin/orion.cmd — wherever the
# repo is. If the repo is on a USB stick, the launcher follows. The
# user's PATH points at ~/.orion-bin, which is a junction to <repo>/bin.
# When the USB is unplugged, the junction dangles, the launcher
# vanishes, `orion` is not found. Same load-bearing principle as the
# brain dir.
#
# The brain dir at ~/.orion stays untouched here — only the wizard's
# brain-location prompt creates it (or junctions it to a portable drive).

$LauncherSrcDir = Join-Path $ScriptDir 'bin'
$LauncherSrc    = Join-Path $LauncherSrcDir 'orion.cmd'
$LauncherLink   = Join-Path $env:USERPROFILE '.orion-bin'

if (-not (Test-Path $LauncherSrcDir)) {
    New-Item -ItemType Directory -Path $LauncherSrcDir -Force | Out-Null
}

$launcherContent = @"
@echo off
REM orion launcher -- created by install.ps1
REM Runs orion.py via the repo's venv so deps are always available.
"$VenvPython" "$ScriptDir\orion.py" %*
"@

Set-Content -Path $LauncherSrc -Value $launcherContent -Encoding ascii
Ok "Launcher installed at: $LauncherSrc"

# Junction ~/.orion-bin -> <repo>/bin so it follows the repo. If a real
# folder or stale junction is at that path, replace it.
if (Test-Path $LauncherLink) {
    $existing = Get-Item $LauncherLink -Force
    if ($existing.Attributes -match "ReparsePoint") {
        cmd /c rmdir "$LauncherLink" 2>&1 | Out-Null
    } else {
        Remove-Item $LauncherLink -Recurse -Force
    }
}
$mklinkOut = cmd /c mklink /J "$LauncherLink" "$LauncherSrcDir" 2>&1
Ok "Junction created: $LauncherLink -> $LauncherSrcDir"

# Add to user PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if (-not $userPath) { $userPath = '' }

if (($userPath -split ';') -notcontains $LauncherLink) {
    $newPath = if ($userPath) { "$userPath;$LauncherLink" } else { $LauncherLink }
    [Environment]::SetEnvironmentVariable('PATH', $newPath, 'User')
    Ok "Added $LauncherLink to user PATH"
    Warn "Open a NEW PowerShell window for the PATH change to take effect."
} else {
    Ok "$LauncherLink already in user PATH"
}

# ----------------------------------------------------------------
# Step 5: Conversational setup wizard (proto-Orion) + preflight
# ----------------------------------------------------------------

$useClassic = $args -contains '--classic'

Say ""
$setupChat = Join-Path $ScriptDir 'orion_setup_chat.py'
$setupClassic = Join-Path $ScriptDir 'setup.py'

if ($useClassic -or -not (Test-Path $setupChat)) {
    if (Test-Path $setupClassic) {
        Info "Running classic setup wizard..."
        & $VenvPython $setupClassic
    } else {
        Warn "No setup script found, skipping wizard"
    }
} else {
    & $VenvPython $setupChat
}

Say ""
Info "Running preflight health check..."
$preflight = Join-Path $ScriptDir 'orion_preflight.py'
if (Test-Path $preflight) {
    & $VenvPython $preflight
}

# ----------------------------------------------------------------
# Done
# ----------------------------------------------------------------

Say ""
Ok "Install complete."
Say ""
Say "  Start talking to Orion:    orion chat"
Say "  Re-run health check:       python orion_preflight.py"
Say ""
Say "  If 'orion' isn't found, open a NEW PowerShell window so PATH refreshes."
Say "  Or call directly:          $Launcher chat"
Say ""
