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
if (-not (Test-Path $target)) { New-Item -ItemType File -Path $target -Force | Out-Null }

# ---- Append key idempotently ----
$existing = Get-Content $target -ErrorAction SilentlyContinue
if ($existing -notcontains $KEY) {
    Add-Content -Path $target -Value $KEY
    Write-Host "Key appended to $target" -ForegroundColor Green
} else {
    Write-Host "Key already present in $target" -ForegroundColor Yellow
}

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
