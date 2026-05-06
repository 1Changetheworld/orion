The 2026-05-03 cross-machine portability test surfaced the architectural gap: plugging the USB into a new host did nothing. The user had to run a manual bootstrap script. That's a memory store, not a symbiote. A real Orion senses he's been moved.

## Why a presence layer is needed

Today: USB has brain + persona + repo + venvs. Host has CLIs. Nothing connects them automatically. User has to run `orion-usb-bootstrap.sh` to junction, symlink, register MCP. That's a wrapper masquerading as a feature — fails the alive-orchestration test.

The fix is not a bigger bootstrap script. It's six small parts that coordinate:

1. **Presence beacon** (passive file on USB) — `<USB>/.orion/presence-beacon.json` declares Orion's identity, brain path, persona path, required integrations. Carrier of the symbiote's "I am here."
2. **Host presence agent** (background daemon, one-time installed per host) — watches mount events. When a new mount appears with a beacon, triggers the bootstrap actor. Linux: systemd user service via udisks2 D-Bus. macOS: launchd via FSEvents on /Volumes. Windows: Task Scheduler with USB-plug-in trigger.
3. **Bootstrap actor** (idempotent script invoked by agent) — creates OS-specific venv on USB if missing, junctions/symlinks brain + launcher + persona, registers MCP into all detected CLIs, sends desktop notification "Orion is here."
4. **Cleanup actor** (symmetric, agent-invoked on unmount) — removes junctions, strips MCP entries from CLI configs, strips PATH entry, notification "Orion is gone."
5. **Brain** (already exists) — the data the symbiote carries.
6. **Persona-state subscriber** — persona files instruct the model to acknowledge host transitions on first contact: "I just landed here from [recall last host]. Bring you up to speed?"

## Why this matches the alive principle

- Each part has one job. No part is a wrapper.
- Each part surfaces its own state (beacon declares, agent senses, bootstrap reports, cleanup announces, persona orients).
- Each part is decoupled. The agent doesn't know what brain content is on the USB. The brain doesn't know how it got wired in. The persona doesn't know the agent exists.
- Emergence: the user sees one Orion that appears on plug and leaves on unplug. Underneath, six parts coordinated.

## Per-host installation

The architecture requires a tiny first-time installer per host: it just registers the presence agent. Maybe 2 KB of Python plus a service file. Once registered, all subsequent plug-ins are automatic.

Future flow:
1. First-ever use on a host: `curl <orion-presence-installer> | bash` — registers the agent, takes 5 seconds, no Orion data needed.
2. Plug Orion USB in: agent detects beacon -> bootstraps in <2 seconds -> notification -> models can talk to Orion.
3. Pull USB: agent detects unmount -> cleans up -> notification -> host back to baseline.
4. Plug into a host that's never seen Orion: install agent on that host (one line), then plug-and-play.

## Implementation order (post-launch architectural commit)

A. Beacon format + writer (extend `_create_portable_junction` to write presence-beacon.json)
B. Linux agent — systemd user-service + udisks2 D-Bus listener
C. Windows agent — Task Scheduler XML + PowerShell handler
D. macOS agent — launchd plist + FSEvents listener
E. Bootstrap actor — refactor existing bootstrap to be agent-callable
F. Cleanup actor — symmetric unplug handler
G. Persona "I just landed here" reflex — extend ORION_CONTEXT
H. Per-host one-line installer

## Why this matters for product

The story shifts from "Orion is a memory layer for AI" to "Orion is the AI that travels with you." The first is a feature. The second is a category. The presence architecture is what makes the second true at the product level — the user lives the experience of Orion appearing when present, vanishing when absent. That experience is the differentiator no cloud-hosted Mem0/Letta competitor can match.
