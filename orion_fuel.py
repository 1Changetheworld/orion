#!/usr/bin/env python3
"""
ORION FUEL SYSTEM — Detect and use whatever AI model is available.
The brain stays constant. The fuel changes based on what's at the pump.

On startup, scans the environment for available models/CLIs/apps.
Ranks them by capability. Uses the best one available.
Falls back down the chain if the primary fails.

This is what makes Orion portable. Plug the drive in anywhere,
this module finds the power source.
"""
import subprocess
import json
import os
import urllib.request
import shutil
import time


# ═══════════════════════════════════════════════════════════════
# FUEL ADAPTER INTERFACE
# Every adapter implements: detect() -> bool, query(prompt) -> str
# ═══════════════════════════════════════════════════════════════

class FuelAdapter:
    """Base class for all fuel sources."""
    name = "unknown"
    tier = 99  # lower = better (tier 1 = strongest)

    def detect(self):
        """Return True if this fuel source is available."""
        return False

    def query(self, prompt, max_turns=15):
        """Send prompt, get response. Returns string or None."""
        return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Claude CLI (Opus via Pro subscription — $0/request)
# ═══════════════════════════════════════════════════════════════

class ClaudeCLIFuel(FuelAdapter):
    name = "claude-cli"
    tier = 1  # Best available — Opus power

    def __init__(self):
        self._path = None
        self._bridge_url = "http://127.0.0.1:3460"

    def detect(self):
        # Check for file bridge first (persistent session, fastest)
        try:
            req = urllib.request.Request(f"{self._bridge_url}/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        # Check for CLI binary
        self._path = shutil.which("claude")
        return self._path is not None

    def query(self, prompt, max_turns=15):
        # Try bridge first (persistent session)
        try:
            payload = json.dumps({"prompt": prompt, "interface": "orion", "max_turns": max_turns}).encode()
            req = urllib.request.Request(self._bridge_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read())
                output = result.get("output", "")
                if output and not output.startswith("Error:"):
                    return output
        except Exception:
            pass
        # Fallback: direct CLI call
        if self._path:
            try:
                result = subprocess.run(
                    [self._path, "-p", prompt, "--max-turns", str(max_turns), "--dangerously-skip-permissions"],
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass
        return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Codex CLI (OpenAI)
# ═══════════════════════════════════════════════════════════════

class CodexCLIFuel(FuelAdapter):
    name = "codex-cli"
    tier = 2

    def __init__(self):
        self._path = None

    def detect(self):
        self._path = shutil.which("codex")
        return self._path is not None

    def query(self, prompt, max_turns=15):
        if not self._path:
            return None
        try:
            # `codex exec` is the non-interactive mode. `--skip-git-repo-check`
            # is required for dirs that aren't trusted by codex (e.g. non-git
            # paths, or first-time-touched directories). Validated via
            # session 2026-04-21 MCP proof-of-life.
            result = subprocess.run(
                [self._path, "exec", "--skip-git-repo-check", prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Gemini CLI (Google, free tier)
# ═══════════════════════════════════════════════════════════════

class GeminiCLIFuel(FuelAdapter):
    name = "gemini-cli"
    tier = 2

    def __init__(self):
        self._path = None

    def detect(self):
        self._path = shutil.which("gemini")
        return self._path is not None

    def query(self, prompt, max_turns=15):
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, "-p", prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Anthropic API (direct HTTP — survives CLI auth expiry)
# ═══════════════════════════════════════════════════════════════
#
# Why this exists: when claude-cli's keychain credentials expire
# (observed 2026-05-10/11), the CLI fuel returns None and the brain
# goes silent on iMessage. Founder rule: "the brain should be
# adaptive enough to reach out to me via other communication points."
# This adapter gives the router a fallback that doesn't share fate
# with the CLI's auth layer. If ANTHROPIC_API_KEY is in the
# environment OR in .env.secrets, this fuel works.

class AnthropicAPIFuel(FuelAdapter):
    name = "anthropic-api"
    tier = 1  # Same quality as claude-cli — same model, different transport

    def __init__(self):
        self._key = None
        self._model = os.environ.get("ORION_ANTHROPIC_MODEL", "claude-opus-4-7")

    def _load_key(self):
        if self._key:
            return self._key
        # 1. Env var
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            self._key = env_key
            return env_key
        # 2. .env.secrets file alongside the brain — never in code
        for candidate in [
            os.environ.get("ORION_BRAIN_DIR", "") + "/.env.secrets",
            os.path.expanduser("~/.orion/.env.secrets"),
            "/Volumes/AtlasVault/.orion/.env.secrets",
        ]:
            if candidate and os.path.isfile(candidate):
                try:
                    for line in open(candidate, encoding="utf-8"):
                        if line.startswith("ANTHROPIC_API_KEY="):
                            self._key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            return self._key
                except Exception:
                    continue
        return None

    def detect(self):
        return self._load_key() is not None

    def query(self, prompt, max_turns=15):
        key = self._load_key()
        if not key:
            return None
        payload = json.dumps({
            "model": self._model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
                blocks = data.get("content", [])
                for b in blocks:
                    if b.get("type") == "text":
                        return b.get("text", "")
                return None
        except Exception as e:
            try:
                from orion_substrate import publish
                publish("brain.fuel.error", {
                    "ts": time.time(),
                    "engine": self.name,
                    "error": str(e)[:200],
                })
            except Exception:
                pass
            return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Ollama (local models — free, works offline)
# ═══════════════════════════════════════════════════════════════

class OllamaFuel(FuelAdapter):
    name = "ollama"
    tier = 3  # Free but weaker

    def __init__(self):
        self._url = None
        self._model = None

    def detect(self):
        # Check common Ollama endpoints
        for url in ["http://localhost:11434", "http://127.0.0.1:11434"]:
            try:
                req = urllib.request.Request(f"{url}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = data.get("models", [])
                    if models:
                        self._url = url
                        # Pick best available model
                        names = [m["name"] for m in models]
                        for preferred in ["qwen3:14b", "qwen3:8b", "dolphin-mistral:7b",
                                         "mistral:7b", "llama3.1:8b", "phi3:mini"]:
                            if preferred in names:
                                self._model = preferred
                                break
                        if not self._model and names:
                            self._model = names[0]
                        return True
            except Exception:
                continue
        # Check if ollama binary exists but server not running
        if shutil.which("ollama"):
            try:
                subprocess.Popen(["ollama", "serve"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)
                return self.detect()  # retry after starting
            except Exception:
                pass
        return False

    def query(self, prompt, max_turns=15):
        if not self._url or not self._model:
            return None
        payload = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self._url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "")
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: tgpt (multi-provider, free)
# ═══════════════════════════════════════════════════════════════

class TgptFuel(FuelAdapter):
    name = "tgpt"
    tier = 4

    def __init__(self):
        self._path = None

    def detect(self):
        self._path = shutil.which("tgpt")
        return self._path is not None

    def query(self, prompt, max_turns=15):
        if not self._path:
            return None
        try:
            result = subprocess.run(
                [self._path, "-q", prompt],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


# ═══════════════════════════════════════════════════════════════
# ADAPTER: Remote Ollama (on another device in the mesh)
# ═══════════════════════════════════════════════════════════════

class RemoteOllamaFuel(FuelAdapter):
    name = "remote-ollama"
    tier = 3

    def __init__(self, hosts=None):
        # Default host list is placeholder-only. Real deployments set these
        # via the ORION_REMOTE_OLLAMA_HOSTS env var (comma-separated) or by
        # passing hosts= explicitly. Tailscale/VPN fallbacks are opt-in,
        # not wired at the library level.
        import os as _os
        env_hosts = _os.environ.get("ORION_REMOTE_OLLAMA_HOSTS", "")
        if env_hosts:
            self._hosts = [h.strip() for h in env_hosts.split(",") if h.strip()]
        else:
            self._hosts = hosts or [
                "{PRIMARY_HOST}:11434",     # primary inference host
                "{SECONDARY_HOST}:11434",   # secondary/fallback
            ]
        self._active = None
        self._model = None

    def detect(self):
        for host in self._hosts:
            try:
                req = urllib.request.Request(f"http://{host}/api/tags")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read())
                    models = data.get("models", [])
                    if models:
                        self._active = host
                        names = [m["name"] for m in models]
                        for preferred in ["qwen3:14b", "qwen3:8b", "dolphin-mistral:7b", "mistral:7b", "phi3:mini"]:
                            if preferred in names:
                                self._model = preferred
                                break
                        if not self._model:
                            self._model = names[0]
                        return True
            except Exception:
                continue
        return False

    def query(self, prompt, max_turns=15):
        if not self._active or not self._model:
            return None
        payload = json.dumps({"model": self._model, "prompt": prompt, "stream": False}).encode()
        try:
            req = urllib.request.Request(
                f"http://{self._active}/api/generate",
                data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read()).get("response", "")
        except Exception:
            return None


# ═══════════════════════════════════════════════════════════════
# FUEL SYSTEM — Detects, ranks, and manages all available fuel
# ═══════════════════════════════════════════════════════════════

class FuelSystem:
    """
    The fuel system. Scans environment, ranks available power sources,
    uses the best one. Falls back automatically.

    This is what makes Orion portable. The brain is on the drive.
    The fuel comes from whatever the host device has.
    """

    def __init__(self):
        self.adapters = [
            ClaudeCLIFuel(),
            AnthropicAPIFuel(),    # same model as CLI, different auth — survives keychain expiry
            CodexCLIFuel(),
            GeminiCLIFuel(),
            OllamaFuel(),
            RemoteOllamaFuel(),
            TgptFuel(),
        ]
        self.available = []
        self.primary = None

    def scan(self):
        """Scan environment for available fuel sources."""
        self.available = []
        for adapter in self.adapters:
            try:
                if adapter.detect():
                    self.available.append(adapter)
            except Exception:
                continue
        # Sort by tier (lower = better)
        self.available.sort(key=lambda a: a.tier)
        self.primary = self.available[0] if self.available else None
        return self.available

    def status(self):
        """Return human-readable fuel status."""
        if not self.available:
            return "No fuel sources detected."
        lines = []
        for i, a in enumerate(self.available):
            marker = ">>>" if a == self.primary else "   "
            lines.append(f"{marker} [{a.tier}] {a.name}")
        return "\n".join(lines)

    def query(self, prompt, max_turns=15):
        """
        Query the best available fuel. Auto-fallback on failure.
        Returns (response, engine_name) or (None, "none").

        Read ~/.orion/fuel_preference.json at top of routing. If a specific
        fuel is named there (not "auto"), try it first. On its failure,
        fall through the priority cascade. Escape hatch:
        ORION_FUEL_PREF_LOCKED=1 disables the preference read.
        """
        if not os.environ.get("ORION_FUEL_PREF_LOCKED"):
            try:
                pref_path = os.path.expanduser("~/.orion/fuel_preference.json")
                if os.path.exists(pref_path):
                    with open(pref_path, encoding="utf-8") as _pf:
                        pref = json.load(_pf).get("fuel", "auto")
                    if pref and pref != "auto":
                        for adapter in self.available:
                            if adapter.name == pref:
                                try:
                                    result = adapter.query(prompt, max_turns)
                                    if result:
                                        return result, adapter.name
                                except Exception:
                                    pass  # fall through to cascade
                                break
            except Exception:
                pass  # preference is advisory; never block on read failure
        for adapter in self.available:
            try:
                result = adapter.query(prompt, max_turns)
                if result:
                    return result, adapter.name
            except Exception:
                continue
        return None, "none"


# ═══════════════════════════════════════════════════════════════
# MODULE-LEVEL INSTANCE — scan on import
# ═══════════════════════════════════════════════════════════════

fuel = FuelSystem()


def init():
    """Scan for available fuel. Call on startup."""
    sources = fuel.scan()
    return fuel


def get_fuel(prompt, interface="cli", max_turns=15):
    """Query best available fuel. Used by the brain."""
    if not fuel.available:
        fuel.scan()
    response, engine = fuel.query(prompt, max_turns)
    if response:
        return response, engine
    return "All models unavailable. Try another interface.", "none"


def status():
    """Human-readable fuel status."""
    return fuel.status()


# ═══════════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("ORION FUEL SYSTEM — Scanning environment...\n")
    system = init()
    print(f"Found {len(system.available)} fuel source(s):\n")
    print(system.status())
    print()

    if system.primary:
        print(f"Primary: {system.primary.name} (tier {system.primary.tier})")
        print("\nTest query: 'What is 2+2?'")
        response, engine = system.query("What is 2+2? Reply with just the number.")
        print(f"Response via {engine}: {response[:100] if response else 'FAILED'}")
    else:
        print("No fuel sources available.")
