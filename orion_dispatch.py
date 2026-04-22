#!/usr/bin/env python3
"""Orion Dispatch — Command execution layer.
Any interface can call these. Not tied to Telegram, iMessage, or any specific channel.
Runs shell commands locally and dispatches to configured mesh devices via SSH.
"""
import subprocess
import time
import os

SECURITY_DIR = "{SECURITY_DIR}"
AGENTS_DIR = "{AGENTS_DIR}"
SSH_KEY = os.path.expanduser("~/.ssh/id_server_home")


def run_cmd(cmd, timeout=60):
    """Run a shell command locally. Returns (output, elapsed_seconds)."""
    start = time.time()
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        elapsed = time.time() - start
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr.strip():
            output += "\n" + result.stderr.strip()
        return (output[:4000] if output else "(no output)", round(elapsed, 1))
    except subprocess.TimeoutExpired:
        return (f"Command timed out after {timeout}s", round(time.time() - start, 1))
    except Exception as e:
        return (f"Error: {e}", round(time.time() - start, 1))


def ssh_cmd(host, user, cmd, timeout=60):
    """Run a command on a remote mesh device via SSH."""
    ssh = f"ssh -o ConnectTimeout=10 -o BatchMode=yes -i {SSH_KEY} {user}@{host} '{cmd}'"
    return run_cmd(ssh, timeout=timeout)


# ═══════════════════════════════════════════════════════════════
# STATUS COMMANDS
# ═══════════════════════════════════════════════════════════════

def status():
    """System overview — CPU, RAM, disk, Docker, uptime."""
    out, _ = run_cmd(
        "echo '--- Uptime ---'; uptime; "
        "echo '--- Memory ---'; vm_stat | head -5; "
        "echo '--- Disk ---'; df -h / | tail -1; "
        "echo '--- Docker ---'; export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH; "
        "docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | head -20"
    )
    return out


def mesh():
    """Ping all mesh devices.

    Example mesh topology — real deployments customize by editing the
    devices list below or by supplying hosts via a config file. Names and
    IPs here are placeholders, not real infrastructure.
    """
    results = []
    devices = [
        ("primary-hub", "{PRIMARY_HUB_IP}", "{SSH_USER}", "Central hub"),
        ("workstation", "{WORKSTATION_IP}", None, "Dev workstation"),
        ("vision-node", "{VISION_IP}", "{VISION_USER}", "Vision agent"),
        ("security-node", "{SECURITY_IP}", "{SECURITY_USER}", "Security"),
    ]
    for name, ip, user, role in devices:
        out, elapsed = run_cmd(f"ping -c 1 -W 2 {ip} >/dev/null 2>&1 && echo UP || echo DOWN", timeout=5)
        status = "ONLINE" if "UP" in out else "OFFLINE"
        results.append(f"{name} ({ip}): {status} — {role}")
    return "\n".join(results)


def services():
    """Docker container status."""
    out, _ = run_cmd(
        "export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH; "
        "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null"
    )
    return out


def agents():
    """Automation script status."""
    out, _ = run_cmd(f"cat {DASHBOARD_DIR}/agent-status.json 2>/dev/null")
    return out


# ═══════════════════════════════════════════════════════════════
# SECURITY COMMANDS (dispatched to configured security node)
# ═══════════════════════════════════════════════════════════════

def scan(target):
    out, elapsed = run_cmd(f"/bin/zsh {SECURITY_DIR}/agent05_security.sh scan-device {target}", timeout=300)
    return f"Scan results for {target} ({elapsed}s):\n{out}"


def portscan(target):
    out, elapsed = ssh_cmd("{SECURITY_IP}", "{SECURITY_USER}", f"nmap -F {target} 2>/dev/null", timeout=120)
    return f"Port scan {target} ({elapsed}s):\n{out}"


def vulnscan(target):
    out, elapsed = ssh_cmd("{SECURITY_IP}", "{SECURITY_USER}", f"nuclei -u {target} -severity medium,high,critical 2>/dev/null", timeout=300)
    return f"Vulnerability scan {target} ({elapsed}s):\n{out}"


def webscan(url):
    out, elapsed = ssh_cmd("{SECURITY_IP}", "{SECURITY_USER}", f"nikto -h {url} -maxtime 120 2>/dev/null", timeout=180)
    return f"Web scan {url} ({elapsed}s):\n{out}"


def sslcheck(domain):
    out, elapsed = ssh_cmd("{SECURITY_IP}", "{SECURITY_USER}", f"sslscan {domain} 2>/dev/null", timeout=60)
    return f"SSL check {domain} ({elapsed}s):\n{out}"


def headers(url):
    out, elapsed = run_cmd(f"curl -sI -m 10 {url} 2>/dev/null", timeout=15)
    return f"HTTP headers for {url} ({elapsed}s):\n{out}"


def subdomains(domain):
    out, elapsed = ssh_cmd("{SECURITY_IP}", "{SECURITY_USER}", f"subfinder -d {domain} -silent 2>/dev/null | head -30", timeout=120)
    return f"Subdomains for {domain} ({elapsed}s):\n{out}"


# ═══════════════════════════════════════════════════════════════
# AI COMMANDS
# ═══════════════════════════════════════════════════════════════

def dolphin(prompt):
    """Uncensored local-model query via configured workstation's Ollama."""
    out, elapsed = run_cmd(
        f'curl -s --max-time 120 http://{FORGE_IP}:11434/api/generate '
        f'-d \'{{"model":"dolphin-mistral:7b","prompt":"{prompt[:500]}","stream":false}}\' '
        f'2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get(\'response\',\'\'))"',
        timeout=130
    )
    return f"Dolphin ({elapsed}s):\n{out}"


# ═══════════════════════════════════════════════════════════════
# TOOL COMMANDS
# ═══════════════════════════════════════════════════════════════

def dispatch(device, command):
    """Execute any command on any mesh device."""
    devices = {
        "primary-hub": ("{PRIMARY_HUB_IP}", "{SSH_USER}"),
        "workstation": ("{WORKSTATION_IP}", "{WORKSTATION_USER}"),
        "vision-node":  ("{VISION_IP}", "{VISION_USER}"),
        "security-node": ("{SECURITY_IP}", "{SECURITY_USER}"),
    }
    dev = devices.get(device.lower())
    if not dev:
        return f"Unknown device: {device}. Available: command, forge, outpost, asus"
    out, elapsed = ssh_cmd(dev[0], dev[1], command, timeout=120)
    return f"[{device}] ({elapsed}s):\n{out}"


def docker_cmd(action, container=""):
    """Docker management."""
    out, _ = run_cmd(
        f"export PATH=/usr/local/bin:/opt/homebrew/bin:$PATH; docker {action} {container} 2>&1",
        timeout=30
    )
    return out


def send_email(to, subject, body):
    """Send email via himalaya."""
    header = chr(10).join(["From: {EMAIL_ADDRESS}", "To: " + to, "Subject: " + subject, "", body])
    cmd = "printf " + repr(header) + " | {EMAIL_TOOL} message send 2>&1"
    out, _ = run_cmd(cmd, timeout=30)
    return out if out else "Email sent."


def disk():
    """Disk usage."""
    out, _ = run_cmd("df -h / /Volumes/AtlasVault 2>/dev/null")
    return out


def ip():
    """IP addresses."""
    out, _ = run_cmd("ifconfig en0 2>/dev/null | grep 'inet '; echo 'Tailscale:'; tailscale ip -4 2>/dev/null")
    return out


# ═══════════════════════════════════════════════════════════════
# DISPATCH ROUTER — called by the brain when it detects an action
# ═══════════════════════════════════════════════════════════════

DISPATCH_MAP = {
    "status": lambda args: status(),
    "mesh": lambda args: mesh(),
    "services": lambda args: services(),
    "agents": lambda args: agents(),
    "scan": lambda args: scan(args),
    "portscan": lambda args: portscan(args),
    "vulnscan": lambda args: vulnscan(args),
    "webscan": lambda args: webscan(args),
    "sslcheck": lambda args: sslcheck(args),
    "headers": lambda args: headers(args),
    "subdomains": lambda args: subdomains(args),
    "dolphin": lambda args: dolphin(args),
    "dispatch": lambda args: dispatch(args.split()[0], " ".join(args.split()[1:])) if " " in args else "Usage: dispatch <device> <command>",
    "docker": lambda args: docker_cmd(args),
    "email": lambda args: send_email(*args.split("|", 2)) if "|" in args else "Usage: email to|subject|body",
    "disk": lambda args: disk(),
    "ip": lambda args: ip(),
}


def execute(command_name, args=""):
    """Execute a dispatch command by name. Returns result string."""
    handler = DISPATCH_MAP.get(command_name.lower())
    if not handler:
        return None  # Not a known command — let the brain handle conversationally
    try:
        return handler(args)
    except Exception as e:
        return f"Dispatch error: {e}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        args = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        print(execute(cmd, args) or f"Unknown command: {cmd}")
    else:
        print("Available commands:", ", ".join(sorted(DISPATCH_MAP.keys())))
