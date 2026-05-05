# authorize-forge-key.ps1 — grant FORGE SSH access to this Windows host.
#
# Adds FORGE's public key to the right authorized_keys file (Windows
# OpenSSH puts admin keys in C:\ProgramData\ssh\administrators_authorized_keys
# and regular-user keys in ~/.ssh/authorized_keys), tightens the ACL so
# OpenSSH won't reject the file, and verifies sshd is running.
#
# Run via:
#   powershell -ExecutionPolicy Bypass -File scripts\authorize-forge-key.ps1

$KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHCO4KHOeNch/UKFLfyrxF4ygDu66NXEepauRia//Zej FORGE-to-orion-vm-20260429'

# ---- Detect admin ----
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# ---- Pick the correct authorized_keys path ----
if ($isAdmin) {
    $sshDir = "$env:ProgramData\ssh"
    $target = "$sshDir\administrators_authorized_keys"
} else {
    $sshDir = "$env:USERPROFILE\.ssh"
    $target = "$sshDir\authorized_keys"
}

New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

# ---- Rewrite the file from scratch with explicit ASCII encoding ----
# Why rewrite (not just append): a prior multi-line paste can leave
# orphan comment fragments and BOM-encoded content. OpenSSH on Windows
# can be picky about encoding (UTF-16 / UTF-8 BOM tripped past attempts).
# We collect the FORGE key + any other valid pubkey lines already in
# the file, then write everything back fresh in ASCII with LF endings.
$kept = New-Object System.Collections.Generic.List[string]
$kept.Add($KEY)
if (Test-Path $target) {
    foreach ($line in (Get-Content $target -ErrorAction SilentlyContinue)) {
        $trimmed = $line.Trim()
        # Keep only well-formed pubkey lines that aren't already our FORGE key.
        if ($trimmed -match '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp\d+)\s+\S+(\s+.+)?$' -and $trimmed -ne $KEY) {
            $kept.Add($trimmed)
        }
    }
}
$content = ($kept -join "`n") + "`n"
[System.IO.File]::WriteAllText($target, $content, [System.Text.Encoding]::ASCII)
Write-Host "Wrote $($kept.Count) key(s) to $target (ASCII, LF)" -ForegroundColor Green

# ---- Tighten ACL — OpenSSH refuses keys if file is too permissive ----
if ($isAdmin) {
    icacls $target /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F" | Out-Null
} else {
    icacls $target /inheritance:r /grant "$($env:USERNAME):F" /grant "SYSTEM:F" | Out-Null
}

# ---- Verify sshd is running ----
$svc = Get-Service sshd -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne 'Running') {
        Start-Service sshd
        Write-Host "Started sshd service." -ForegroundColor Green
    } else {
        Write-Host "sshd is running." -ForegroundColor Green
    }
    Set-Service -Name sshd -StartupType Automatic
} else {
    Write-Host "OpenSSH server not installed. Installing now..." -ForegroundColor Yellow
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    Start-Service sshd
    Set-Service -Name sshd -StartupType Automatic
    Write-Host "OpenSSH server installed and started." -ForegroundColor Green
}

# ---- Firewall rule ----
$fwRule = Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue
if (-not $fwRule -or $fwRule.Enabled -eq 'False') {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -ErrorAction SilentlyContinue | Out-Null
    Write-Host "Firewall rule OpenSSH-Server-In-TCP enabled." -ForegroundColor Green
}

Write-Host ""
Write-Host "----- Summary -----" -ForegroundColor Cyan
Write-Host "User:           $env:USERNAME"
Write-Host "Admin:          $isAdmin"
Write-Host "Hostname:       $env:COMPUTERNAME"
Write-Host "Authorized at:  $target"
Write-Host ""
Write-Host "From FORGE, test:"
Write-Host "  ssh -i ~/.ssh/id_orion_vm $env:USERNAME@<this-machine-ip-or-tailscale>"
