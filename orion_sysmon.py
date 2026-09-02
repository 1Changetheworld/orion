#!/usr/bin/python3
"""
orion_sysmon.py - writes /Users/servermac/mission-control/system-monitor.json

Replaces agent09_system_monitor.sh, which (a) was never scheduled, (b) never
collected FORGE at all (hardcoded "alien1": {"online": false}), and (c) polled
OUTPOST/ARSENAL on the retired 10.0.0.x network.

Collects: COMMAND (local, macOS) + FORGE (alien1 over SSH/Tailscale, Windows).
Schema kept identical to what index.html's fetchDeviceMetrics() expects.
"""
import json, subprocess, time, os, re, socket, datetime

OUT   = "/Users/servermac/mission-control/system-monitor.json"
TMP   = OUT + ".tmp"
SSH   = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         "-o", "StrictHostKeyChecking=no", "alien1-ts"]

def sh(cmd, timeout=15):
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                              text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""

# ---------- COMMAND (local macOS) ----------
def collect_server():
    d = {"online": True}
    try:
        cores = int(sh("sysctl -n hw.ncpu") or 10)
        d["cpu_cores"] = cores
        # per-core sum, matching what the dashboard normalizes by cpu_cores
        cpu = sh("ps -A -o %cpu | awk '{s+=$1} END {printf \"%.1f\", s}'")
        d["cpu"] = float(cpu or 0)

        total = int(sh("sysctl -n hw.memsize") or 0)
        vm = sh("vm_stat")
        page = 4096
        m = re.search(r"page size of (\d+)", vm)
        if m: page = int(m.group(1))
        def pages(label):
            mm = re.search(label + r":\s+(\d+)", vm)
            return int(mm.group(1)) * page if mm else 0
        free = pages("Pages free") + pages("Pages inactive") + pages("Pages speculative")
        used = total - free
        d["mem_pct"]   = int(round(used / total * 100)) if total else 0
        d["mem_used"]  = "%.1fGB" % (used / 1e9)
        d["mem_total"] = "%.0fGB" % (total / 1e9)

        # APFS: "/" is the read-only System volume. Real user storage lives on the
        # Data volume, so report that. Also derive the label from used/(used+avail)
        # so disk_info and disk_pct can never disagree.
        target = "/System/Volumes/Data"
        df = sh("df -k %s | tail -1" % target).split()
        if len(df) < 5:
            df = sh("df -k / | tail -1").split()
        if len(df) >= 5:
            used, avail = int(df[2]), int(df[3])
            total = used + avail
            d["disk_pct"]  = int(round(used / total * 100)) if total else 0
            d["disk_info"] = "%.0fGi / %.0fGi" % (used/1048576, total/1048576)

        bt = sh("sysctl -n kern.boottime")
        mb = re.search(r"sec\s*=\s*(\d+)", bt)
        d["uptime_sec"] = int(time.time()) - int(mb.group(1)) if mb else 0

        docker = "/usr/local/bin/docker"
        if os.path.exists(docker):
            lines = [l for l in sh([docker, "ps", "-a", "--format",
                     "{{.Names}}\t{{.Status}}\t{{.Image}}"]).split("\n") if l.strip()]
            conts = []
            for l in lines:
                p = l.split("\t")
                if len(p) >= 3:
                    conts.append({"name": p[0], "status": p[1].split()[0], "image": p[2]})
            d["containers"]     = conts
            d["docker_total"]   = len(conts)
            d["docker_running"] = sum(1 for c in conts if c["status"] == "Up")
    except Exception as e:
        d["error"] = str(e)
    return d

# ---------- FORGE (Windows over SSH) ----------
PS = (
 "$os=Get-CimInstance Win32_OperatingSystem;"
 "$c=(Get-CimInstance Win32_Processor|Measure-Object -Property LoadPercentage -Average).Average;"
 "$n=(Get-CimInstance Win32_Processor|Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum;"
 "$d=Get-PSDrive C;"
 "$tot=$os.TotalVisibleMemorySize;$fre=$os.FreePhysicalMemory;"
 "$up=[int]((Get-Date)-$os.LastBootUpTime).TotalSeconds;"
 "$o=[ordered]@{cpu=[double]$c;cpu_cores=0;"
 "mem_pct=[int](100*($tot-$fre)/$tot);"
 "mem_used=('{0:N1}GB' -f (($tot-$fre)/1MB));mem_total=('{0:N0}GB' -f ($tot/1MB));"
 "disk_pct=[int](100*$d.Used/($d.Used+$d.Free));"
 "disk_info=('{0:N0}Gi / {1:N0}Gi' -f ($d.Used/1GB),(($d.Used+$d.Free)/1GB));"
 "uptime_sec=$up};"
 "$o|ConvertTo-Json -Compress"
)

def collect_alien1():
    raw = sh(SSH + [PS], timeout=25)
    if not raw:
        return {"online": False}
    try:
        j = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        j["online"] = True
        j["cpu_cores"] = 0          # Windows already reports true 0-100%
        return j
    except Exception:
        return {"online": False}

# ---------- services ----------
SERVICES = [(5678,"n8n"),(3000,"Open WebUI"),(9000,"Portainer"),(3002,"Grafana"),
            (8888,"Vaultwarden"),(9090,"Prometheus"),(6333,"Qdrant"),
            (11434,"Ollama"),(4000,"Mission Control"),(6080,"noVNC COMMAND")]

def collect_services():
    lst = []
    for port, name in SERVICES:
        up = False
        try:
            s = socket.create_connection(("127.0.0.1", port), 1.5); s.close(); up = True
        except Exception:
            pass
        lst.append({"port": port, "name": name, "up": up})
    return {"up": sum(1 for x in lst if x["up"]), "total": len(lst), "list": lst}

def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    data = {
        "updated":       now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated_local": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "server":   collect_server(),
        "alien1":   collect_alien1(),
        "services": collect_services(),
    }
    with open(TMP, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(TMP, OUT)          # atomic; dashboard never reads a half-written file
    print("wrote %s  server=%s alien1=%s" %
          (OUT, data["server"].get("online"), data["alien1"].get("online")))

if __name__ == "__main__":
    main()
