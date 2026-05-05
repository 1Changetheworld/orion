# Orion browser extension

A Manifest V3 browser extension that lets you reach Orion's brain from any
browser tab. Built for Chromium (Chrome, Edge, Brave, Opera, Arc) and Firefox.

## What it does (v0.1)

- Click the extension icon → popup with a search box
- Type a query → calls `orion_recall` on the local brain, shows the result
- Settings page where you paste your auth token from `~/.orion/auth-token`
- Status indicator shows whether the brain is reachable and how many tools
  are registered

## What it will do (Phase 2)

- Inline overlays on web pages: "Orion remembers you read this article"
- Right-click context menu: "Save selection to Orion" / "What does Orion
  know about this?"
- Auto-injected into Gmail, Twitter, Notion, Slack — surfaces memory
  inside the apps where you actually work
- Streaming responses via `/stream` SSE endpoint

## Architecture

```
popup.html  ──┐
options.html ─┴── service_worker.js ── HTTP ──> orion_brain_service.py
                  (holds auth token)             (127.0.0.1:5556)
```

The service worker is the only place that talks to the brain. The popup
sends `chrome.runtime.sendMessage` requests; the worker holds the bearer
token and returns normalized `{ ok, data | error }` envelopes.

## Local install (developer mode)

### Chrome / Edge / Brave / Opera / Arc

1. Start Orion's brain service:
   ```bash
   python orion_brain_service.py
   ```
2. Find your auth token:
   ```bash
   cat ~/.orion/auth-token
   ```
   On Windows: `Get-Content $HOME\.orion\auth-token`
3. Open `chrome://extensions` (or `edge://extensions`, etc.)
4. Enable **Developer mode** (top-right toggle)
5. Click **Load unpacked**, point at this `browser-extension/` directory
6. Click the Orion icon in the toolbar → **Settings**
7. Paste your auth token, click **Save**
8. Click the icon again, ask the brain something

### Firefox

1. Start the brain service and get the auth token (same as above)
2. Open `about:debugging#/runtime/this-firefox`
3. Click **Load Temporary Add-on**, select `browser-extension/manifest.json`
4. Open the extension popup → **Settings** → paste token

Firefox temporary add-ons clear when the browser closes. Permanent install
requires signing the extension via Mozilla — that's a Phase 2 task.

## Threat model

- The brain service binds to `127.0.0.1` by default. Only this machine can
  reach it.
- The auth token is stored in `chrome.storage.local`, scoped to this
  extension. Other extensions and web pages cannot read it.
- `host_permissions` is restricted to `http://127.0.0.1:5556/*` and
  `http://localhost:5556/*` — the extension cannot reach any other
  origin, period.
- The brain enforces a Host-header allowlist on every request, so even if
  a malicious page somehow got the token, DNS-rebinding-style attacks
  pointing public domains at 127.0.0.1 still fail.

If you opt into LAN exposure (`ORION_BRAIN_BIND=0.0.0.0`), update the
extension's Brain URL in Settings to your LAN IP and add that IP to
`ORION_BRAIN_EXTRA_HOSTS` when starting the brain.
