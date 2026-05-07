# Cloud-memory mode — login anywhere, no drive required

## Founder articulation 2026-05-07

> "What if we also had a feature of Orion that was more cloud-based
> memory? That way you didn't need a drive but could log into your
> CLI memory (Orion) anywhere?"

Companion to USB-portable mode, not a replacement. Two ways to carry
Orion with you:

| Mode | Substrate | Tradeoff |
|---|---|---|
| **Drive mode** (current) | Brain on USB stick | Pull drive = brain physically gone. Maximum privacy. No internet needed. |
| **Cloud mode** (new) | Brain on user-owned cloud account | Log in from any device with internet. No drive to carry. Trust depends on cloud config. |

User picks one or both at install. The brain is the same shape; only
where it lives differs.

## Why this matters for the launch

Drive-mode is the most viscerally compelling demo (plug-and-play between
machines), but it's not the only valid product. Many users:
- Don't want to carry physical hardware
- Already trust their own cloud (iCloud Drive, Google Drive, Dropbox,
  S3 bucket, self-hosted Nextcloud)
- Use multiple devices in places where they wouldn't bring a USB
  (phone, work laptop with USB ports disabled, public library computer)

Cloud mode opens those segments. Drive mode keeps the privacy-first
demo. Both ship under the same Orion identity. The user picks.

## Architecture

The brain is already a network service (`orion_brain_service.py` ships
the HTTP surface — REST + MCP + auth token + Host allowlist). For cloud
mode the brain runs **somewhere the user owns** that's reachable over
the internet:

```
                   user's iPhone (Codex iOS, browser)
                              │
                              ↓ HTTPS / Tailscale
       ┌───────────────────────────────────────────┐
       │  Brain HTTP service (cloud-mode)          │
       │  - Same orion_brain_service.py            │
       │  - Bound to a user-owned host             │
       │  - Bearer token in user's password mgr    │
       └────────────────────┬──────────────────────┘
                            │
                            ↓
    user's Mac (CLI) ───────┴────── user's work laptop (browser ext)
    user's home Pi
```

The "cloud" is the user's own machine in any of these forms:
1. **Self-hosted on a Raspberry Pi at home** (the Pi we already have).
   Tailscale gives the brain a stable 100.x.x.x address. Phone, laptop,
   work computer all hit it the same way regardless of where the user is.
2. **VPS the user owns** (Hetzner $5/mo, Linode, etc.). Same flow.
3. **Their always-on desktop** at home. Same flow.
4. **Tailscale Funnel** to expose home brain over public TLS without
   port-forwarding. Already supported.

We do not run a centralized Orion-Cloud SaaS. The user's brain stays
on their own infrastructure. That's the privacy promise.

## The fall-through

For users who don't have a Pi or VPS:
- Document `Tailscale + a $5 VPS` as the "cloud-mode starter kit."
- Optional: provide a one-command bootstrap — `bash <(curl -fsSL
  orion.dev/install-cloud)` runs the brain service on whatever Linux box
  it's pointed at, wires Tailscale, prints the bearer token. Cloud mode
  is just install-on-server with a more public network surface.

## Login from anywhere

User on a fresh device opens any AI CLI / IDE / browser:
1. Reads their bearer token from a password manager (or types once)
2. Sets `ORION_BRAIN_HTTP_URL=https://<their-tailscale-funnel>` env var
3. Done. Same brain, same memory, anywhere.

No drive required. No prior install on the device required (other than
the AI CLI itself, which the user picked). The user's brain follows
their identity, not a piece of hardware.

## Cellular framing

In drive-mode, Orion is the symbiote that physically travels. Receptor
binding requires the body to be present.

In cloud-mode, Orion is more like a hormonal signaling network — every
cell with the right receptor (auth token) reads the same message
regardless of physical position. The user's identity replaces the USB
stick as the binding agent.

Both are valid biological patterns. Both ship.

## Brain-as-network expansion implication

Cloud-mode + the channels/ framework already shipped means: every
communication point the user has — iMessage on COMMAND, Telegram bot,
Telnyx phone, email, agents — points at the same cloud-resident brain.
The user's identity is what binds them all together, not "which device
I happen to be on."

This is **the moat**. Not just "memory across CLI tools." Memory across
every channel the user uses to communicate, period.

## v1 launch implication

Drive-mode is the demo (visceral, viral, cellular-poetry).
Cloud-mode is the practical default for power users (Tailscale + Pi
or VPS).

Both ship. The README's hero demo is the USB swap; the README's
practical setup section is the cloud-mode quickstart. The user picks
based on their threat model and preference.

## Implementation work

We already have:
- `orion_brain_service.py` — the HTTP surface
- Auth token at `~/.orion/auth-token`
- Host-header allowlist (DNS-rebinding defense)
- CORS for browser extensions
- mDNS-ready (one flag flip)
- Tailscale-friendly (default `0.0.0.0` bind option in env vars)

Cloud-mode requires:
- Documentation: `docs/cloud-mode-setup.md` walking through Tailscale +
  expose
- Wizard flag: `--cloud` mode that asks for the cloud host URL during
  install, writes that into the local bearer token + URL config
- A way to enroll a new device against an existing cloud brain — point
  the local CLI at the cloud URL + paste the token. Already possible
  manually; needs UX.

This is small. The infrastructure is there. The product framing is
the work.
