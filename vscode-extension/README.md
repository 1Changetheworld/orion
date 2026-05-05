# Orion VS Code extension

Reach Orion's brain from any VS Code editor. Recall, memorize selections,
see Orion's identity, all without leaving your work.

## What it does (v0.1)

- **Orion: Recall** — input box, types a question, opens a side-pane markdown
  doc with the recall result
- **Orion: Memorize selection** — right-click on selected text → "Orion:
  Memorize selection" → optional tag → stored in the brain
- **Orion: Show identity** — tiny info popup with Orion's public intro
- **Orion: Check brain status** — diagnostic about brain reachability and
  whether your auth token is set
- **Status bar item** — `Orion · 13` when online, `Orion · off` when not.
  Click it to run the health command.

## Architecture

Pure JavaScript. No build step. All brain calls go through one
`brainFetch()` helper that holds the bearer token and normalizes errors.

```
extension.js (commands + status bar) ── HTTP ──> orion_brain_service.py
                                                  (127.0.0.1:5556)
```

## Local install (developer mode)

1. Start Orion's brain service:
   ```bash
   python orion_brain_service.py
   ```
2. Read your auth token (`cat ~/.orion/auth-token` or
   `Get-Content $HOME\.orion\auth-token`)
3. In VS Code, open this `vscode-extension/` folder
4. Press **F5** to launch a new VS Code window with the extension loaded
   *(or)* run `code --install-extension <path-to-this-dir>` from a terminal
   *(or)* package as VSIX with `vsce package` and install via
   `code --install-extension orion-0.1.0.vsix`
5. Open Settings (`Cmd/Ctrl + ,`), search "orion", paste your auth token
   into `Orion: Auth Token`
6. Open the Command Palette (`Cmd/Ctrl + Shift + P`), type **Orion: Recall**

## Settings

| Key | Default | What it does |
|---|---|---|
| `orion.brainBase` | `http://127.0.0.1:5556` | Brain URL |
| `orion.authToken` | (empty) | Bearer token from `~/.orion/auth-token` |
| `orion.recallLimit` | 5 | Max recall results |
| `orion.showStatusBar` | true | Show "Orion · N" in status bar |

## Phase 2 (not in this commit)

- Sidebar tree view of recent recalls + memories
- Inline hover provider — see Orion's notes about a function name
- Code action: "Ask Orion about this code"
- Streaming responses via `/stream` SSE
- `vsce publish` to the VS Code Marketplace
