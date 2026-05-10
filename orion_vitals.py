"""orion_vitals.py — per-service adaptive nervous-ending.

Every Plexus service can mix this in to gain its own homeostasis:
  - vitals tracking (uptime, event count, last-event-age, error rate, memory)
  - dependency probes (substrate, brain, filesystem)
  - auto-recovery hooks for known failure modes (stuck state, dropped
    connections, FS unwritable)
  - pulse publish on the substrate (host.<svc>.vitals every PULSE_SEC)
  - subscribe to ping requests (anyone can ask 'are you alive?')

DESIGN PRINCIPLE — cellular homeostasis, not centralized monitoring.
Every service watches itself. The claustrum integrates the cross-service
pattern. Both layers run; neither owns the others. Pull the claustrum
offline and individual services keep adapting locally. Pull a single
service offline and the others notice via its missing pulse.

This is the cellular-immune-system layer — what makes the architecture
genuinely cellular and not microservice-shaped. A microservice exposes
endpoints. A cell maintains itself.

USAGE
=====

  from orion_vitals import Vitals

  vitals = Vitals(service_name="claustrum")
  vitals.start_pulse()  # background thread, publishes every 30s

  # call note_event() on every meaningful event
  vitals.note_event()

  # call note_error() on every caught exception you care about
  try:
      do_thing()
  except Exception as e:
      vitals.note_error(e)

  # register recovery routines for known stuck-state patterns
  vitals.register_recovery(
      "no_events_for_1hr",
      lambda v: v.last_event_age_sec() > 3600,
      lambda v: do_recovery_action(),
  )

  # services with known dependencies should declare them
  vitals.add_dependency_probe("substrate", lambda: substrate.available)
  vitals.add_dependency_probe("brain_endpoint", lambda: probe_brain_5555())

The mixin doesn't dictate WHAT a service does on stuck-state. It gives
the service the primitives to define its own reflexes. Different services
recover differently. Some restart, some reconnect, some fall back to a
slower path.

OUTPUTS
=======

Subjects published:
  host.<svc>.vitals      — full vitals snapshot, every PULSE_SEC
  host.<svc>.recovery    — when a recovery routine fires
  host.<svc>.error       — when an error rate threshold is crossed

Persisted (optional):
  ~/.orion/vitals/<svc>.json  — latest snapshot for offline inspection

The claustrum's GlobalWorkspace already tracks 'host_last_seen' from
host.*.heartbeat. Vitals pulse uses host.<svc>.vitals so the claustrum
can integrate per-service health alongside the host-level heartbeats.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

logger = logging.getLogger("orion.vitals")

DEFAULT_PULSE_SEC = float(os.environ.get("ORION_VITALS_PULSE_SEC", "30"))
ERROR_RATE_THRESHOLD = int(os.environ.get("ORION_VITALS_ERROR_THRESHOLD", "5"))
RECOVERY_CHECK_SEC = float(os.environ.get("ORION_VITALS_RECOVERY_SEC", "60"))
VITALS_DIR = Path(os.path.expanduser(
    os.environ.get("ORION_VITALS_DIR", "~/.orion/vitals")
))


class Vitals:
    """Per-service homeostasis primitive.

    Thread-safe. Every counter, every recovery registration, every
    dependency probe, locked. The pulse loop and the recovery loop
    each run as their own daemon thread.

    v1.2 additions (Plexus research-driven):
    - restart_policy declaration (OTP: permanent / transient / temporary)
    - restart-intensity budget (MaxR / MaxT) with PAMP escalation on
      overshoot — services emit a hard danger signal instead of flapping
    - DCA-style danger signal emit (Aickelin Danger Theory) —
      emit_pamp / emit_danger / emit_safe replace simple booleans;
      orion_immune.py aggregates these into a context-adjusted score
      and decides restart-strategy choice (one_for_one / rest_for_one /
      one_for_all) — the novel OTP+AIS synthesis from 2026-05-09
      research.
    """

    def __init__(self, service_name: str,
                 restart_policy: str = "permanent",
                 max_restarts: int = 5,
                 restart_window_sec: float = 300.0):
        self.name = service_name
        self.start_ts = time.time()
        self._lock = threading.Lock()

        # Restart policy (OTP-style)
        # permanent: always restart on exit (e.g. claustrum, substrate)
        # transient: restart only on abnormal exit
        # temporary: never restart (e.g. one-shot ingest)
        if restart_policy not in ("permanent", "transient", "temporary"):
            restart_policy = "permanent"
        self.restart_policy = restart_policy

        # Restart-intensity budget. If we exceed max_restarts in
        # restart_window_sec, emit PAMP and stop self-recovering —
        # the immune layer + executive must take over.
        self.max_restarts = int(max_restarts)
        self.restart_window_sec = float(restart_window_sec)
        self._restart_log: deque = deque(maxlen=100)

        # Counters
        self.event_count = 0
        self.error_count = 0
        self.last_event_ts = self.start_ts
        self.last_error_ts: float | None = None
        self.last_error_msg: str | None = None
        self.recovery_count = 0
        self.last_recovery_ts: float | None = None

        # Rolling error window (last 100 errors with timestamps)
        self.error_log: deque = deque(maxlen=100)

        # Dependency probes — name -> () -> bool
        self._dep_probes: dict[str, Callable[[], bool]] = {}

        # Recovery routines
        # name -> (predicate(vitals)->bool, action(vitals)->None)
        self._recoveries: list[tuple[str, Callable, Callable]] = []

        # Lifecycle
        self._stop = threading.Event()
        self._pulse_thread: threading.Thread | None = None
        self._recovery_thread: threading.Thread | None = None

    # ---------- counters (cheap, thread-safe) ----------

    def note_event(self) -> None:
        with self._lock:
            self.event_count += 1
            self.last_event_ts = time.time()

    def note_error(self, exc_or_msg) -> None:
        msg = str(exc_or_msg)[:200] if exc_or_msg else "(unspecified)"
        with self._lock:
            self.error_count += 1
            self.last_error_ts = time.time()
            self.last_error_msg = msg
            self.error_log.append((self.last_error_ts, msg))

    def note_recovery(self, recovery_name: str) -> None:
        now = time.time()
        with self._lock:
            self.recovery_count += 1
            self.last_recovery_ts = now
            self._restart_log.append(now)
            # Prune outside the window
            cutoff = now - self.restart_window_sec
            while self._restart_log and self._restart_log[0] < cutoff:
                self._restart_log.popleft()
            recent_restarts = len(self._restart_log)
        # If we're over the budget, escalate via PAMP (hard danger signal)
        if recent_restarts > self.max_restarts:
            self.emit_pamp(
                signal_id="restart_storm",
                detail=f"{recent_restarts} restarts in {self.restart_window_sec}s — "
                       f"reflex insufficient, immune/executive should take over",
                weight=1.0,
            )

    # ---------- DCA-style danger signaling (Aickelin Danger Theory) ----------
    # Three signal classes:
    #   PAMP   — Pathogen-Associated Molecular Pattern; hard error, "this is wrong now"
    #   danger — drift / anomaly / latency creep; weighted concern signal
    #   safe   — recovery confirmation, brings the danger context back down
    # The immune aggregator (orion_immune.py) subscribes to these and
    # decides restart-strategy choice from the context-adjusted danger
    # score, not from boolean health checks. This is what lets the
    # supervision tree learn its own restart policy from what worked.

    def emit_pamp(self, signal_id: str, detail: str = "",
                  weight: float = 1.0) -> None:
        """Hard danger signal — definitely something is broken."""
        try:
            from orion_substrate import publish
            publish(f"host.{self.name}.danger.pamp", {
                "service": self.name,
                "signal_id": signal_id,
                "detail": detail[:300],
                "weight": float(weight),
                "ts": time.time(),
            })
        except Exception:
            pass

    def emit_danger(self, signal_id: str, weight: float,
                    detail: str = "") -> None:
        """Soft danger signal — concerning but not yet pathological.
        Weight is a 0..1 magnitude. The immune aggregator treats these
        as context that COULD escalate to PAMP if the pattern persists."""
        try:
            from orion_substrate import publish
            publish(f"host.{self.name}.danger.warn", {
                "service": self.name,
                "signal_id": signal_id,
                "weight": float(max(0.0, min(1.0, weight))),
                "detail": detail[:300],
                "ts": time.time(),
            })
        except Exception:
            pass

    def emit_safe(self, signal_id: str, detail: str = "") -> None:
        """Resolution / recovery / nominal-operation confirmation.
        Brings the danger context window's accumulated weight down."""
        try:
            from orion_substrate import publish
            publish(f"host.{self.name}.danger.safe", {
                "service": self.name,
                "signal_id": signal_id,
                "detail": detail[:200],
                "ts": time.time(),
            })
        except Exception:
            pass

    # ---------- registration ----------

    def add_dependency_probe(self, name: str,
                             probe: Callable[[], bool]) -> None:
        with self._lock:
            self._dep_probes[name] = probe

    def register_recovery(self, name: str,
                          predicate: Callable,
                          action: Callable) -> None:
        with self._lock:
            self._recoveries.append((name, predicate, action))

    # ---------- queries ----------

    def last_event_age_sec(self) -> float:
        with self._lock:
            return time.time() - self.last_event_ts

    def uptime_sec(self) -> float:
        return time.time() - self.start_ts

    def error_rate_per_min(self) -> float:
        now = time.time()
        with self._lock:
            recent = [t for t, _ in self.error_log if (now - t) < 60.0]
            return float(len(recent))

    def memory_mb(self) -> float:
        try:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS reports ru_maxrss in bytes; Linux reports in KB
            if sys.platform == "darwin":
                return ru / (1024.0 * 1024.0)
            return ru / 1024.0
        except Exception:
            return -1.0

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            dep_status = {}
            for name, probe in self._dep_probes.items():
                try:
                    dep_status[name] = bool(probe())
                except Exception:
                    dep_status[name] = False
            return {
                "service": self.name,
                "ts": now,
                "uptime_sec": now - self.start_ts,
                "event_count": self.event_count,
                "error_count": self.error_count,
                "recovery_count": self.recovery_count,
                "last_event_age_sec": now - self.last_event_ts,
                "last_error_age_sec": (
                    (now - self.last_error_ts) if self.last_error_ts else None
                ),
                "last_error_msg": self.last_error_msg,
                "error_rate_per_min": self.error_rate_per_min(),
                "memory_mb": round(self.memory_mb(), 1),
                "dependencies": dep_status,
                "alive": True,
            }

    # ---------- background loops ----------

    def start_pulse(self, interval_sec: float = DEFAULT_PULSE_SEC) -> None:
        """Begin publishing host.<svc>.vitals on the substrate every
        `interval_sec`. Also persist latest to ~/.orion/vitals/<svc>.json."""
        if self._pulse_thread and self._pulse_thread.is_alive():
            return
        self._pulse_thread = threading.Thread(
            target=self._pulse_loop, args=(interval_sec,),
            name=f"vitals-pulse-{self.name}", daemon=True,
        )
        self._pulse_thread.start()
        self._recovery_thread = threading.Thread(
            target=self._recovery_loop,
            name=f"vitals-recovery-{self.name}", daemon=True,
        )
        self._recovery_thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _pulse_loop(self, interval_sec: float) -> None:
        try:
            from orion_substrate import publish
        except ImportError:
            publish = None

        VITALS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = VITALS_DIR / f"{self.name}.json"

        while not self._stop.is_set():
            try:
                snap = self.snapshot()
                if publish:
                    publish(f"host.{self.name}.vitals", snap)
                try:
                    out_path.write_text(
                        json.dumps(snap, indent=2, default=str),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.debug("pulse error: %s", e)
            self._stop.wait(interval_sec)

    def _recovery_loop(self) -> None:
        try:
            from orion_substrate import publish
        except ImportError:
            publish = None

        while not self._stop.is_set():
            try:
                with self._lock:
                    recs = list(self._recoveries)
                for name, predicate, action in recs:
                    try:
                        if predicate(self):
                            logger.info("recovery firing: %s.%s", self.name, name)
                            try:
                                action(self)
                                self.note_recovery(name)
                                if publish:
                                    publish(f"host.{self.name}.recovery", {
                                        "service": self.name,
                                        "recovery": name,
                                        "ts": time.time(),
                                    })
                            except Exception as e:
                                logger.warning(
                                    "recovery action %s.%s raised: %s",
                                    self.name, name, e,
                                )
                                self.note_error(e)
                    except Exception as e:
                        logger.debug("predicate error %s.%s: %s",
                                     self.name, name, e)
            except Exception as e:
                logger.debug("recovery loop error: %s", e)
            self._stop.wait(RECOVERY_CHECK_SEC)
