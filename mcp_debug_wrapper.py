"""Debug wrapper - logs exactly what the MCP client sends and what the server responds."""
import sys
import os
import time
import subprocess

LOG = os.path.expanduser("~/.orion/mcp_debug.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== Wrapper started ===")

# Start the real server
server = subprocess.Popen(
    [sys.executable, os.path.join(os.path.dirname(__file__), "orion_mcp_server.py")],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)

log(f"Server PID: {server.pid}")

# Read stdin byte by byte and log + forward
import threading

def forward_stderr():
    for line in server.stderr:
        log(f"SERVER STDERR: {line}")

threading.Thread(target=forward_stderr, daemon=True).start()

def forward_stdout():
    while True:
        chunk = server.stdout.read(1)
        if not chunk:
            log("SERVER STDOUT EOF")
            break
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
        # Buffer for logging
        forward_stdout._buf = getattr(forward_stdout, '_buf', b'') + chunk
        if chunk == b'\n':
            log(f"SERVER->CLIENT: {forward_stdout._buf!r}")
            forward_stdout._buf = b''

threading.Thread(target=forward_stdout, daemon=True).start()

# Read from client (Codex/Gemini) and log + forward to server
try:
    while True:
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            log("CLIENT STDIN EOF")
            break
        server.stdin.write(chunk)
        server.stdin.flush()
        # Buffer for logging
        if not hasattr(forward_stdout, '_inbuf'):
            forward_stdout._inbuf = b''
        forward_stdout._inbuf += chunk
        if chunk == b'\n':
            log(f"CLIENT->SERVER: {forward_stdout._inbuf!r}")
            forward_stdout._inbuf = b''
except Exception as e:
    log(f"ERROR: {e}")
finally:
    log("=== Wrapper shutting down ===")
    server.terminate()
