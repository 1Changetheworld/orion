// Orion VS Code extension — talks to orion_brain_service.py over HTTP.
//
// Pure JavaScript so we ship without a build step. Single chokepoint for
// brain calls (brainFetch) holds the bearer token and normalizes errors,
// matching the pattern used by the browser extension's service worker.

const vscode = require("vscode");

// ── Helpers ──

function getConfig() {
  const cfg = vscode.workspace.getConfiguration("orion");
  return {
    brainBase: (cfg.get("brainBase") || "http://127.0.0.1:5556").replace(/\/$/, ""),
    authToken: cfg.get("authToken") || "",
    recallLimit: cfg.get("recallLimit") || 5,
    showStatusBar: cfg.get("showStatusBar") !== false
  };
}

async function brainFetch(path, init = {}) {
  const { brainBase, authToken } = getConfig();
  const headers = Object.assign({}, init.headers || {});
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (init.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  try {
    const res = await fetch(`${brainBase}${path}`, Object.assign({}, init, { headers }));
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).error || ""; } catch (_) { detail = res.statusText; }
      return { ok: false, status: res.status, error: detail || `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message || String(e) };
  }
}

async function callTool(name, args) {
  return brainFetch("/v1/call", {
    method: "POST",
    body: JSON.stringify({ name, arguments: args || {} })
  });
}

function extractText(content) {
  if (!Array.isArray(content)) return "(no result)";
  return content
    .filter(c => c && c.type === "text")
    .map(c => c.text)
    .join("\n\n") || "(no result)";
}

// ── Status bar ──

let statusBarItem = null;
let statusInterval = null;

async function refreshStatusBar() {
  if (!statusBarItem) return;
  const { brainBase } = getConfig();
  try {
    const res = await fetch(`${brainBase}/health`);
    if (res.ok) {
      const data = await res.json();
      statusBarItem.text = `$(circuit-board) Orion · ${data.tool_count}`;
      statusBarItem.tooltip = `Orion brain online — ${data.tool_count} tools at ${brainBase}`;
      statusBarItem.backgroundColor = undefined;
    } else {
      statusBarItem.text = `$(circuit-board) Orion · err`;
      statusBarItem.tooltip = `Orion brain reachable but returned HTTP ${res.status}`;
      statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    }
  } catch (e) {
    statusBarItem.text = `$(circuit-board) Orion · off`;
    statusBarItem.tooltip = `Orion brain unreachable at ${brainBase}\nStart it: python orion_brain_service.py`;
    statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
  }
}

// ── Command: Orion: Recall ──

async function recallCommand() {
  const query = await vscode.window.showInputBox({
    prompt: "Ask Orion's brain",
    placeHolder: "What does Orion know about…"
  });
  if (!query) return;

  const { recallLimit } = getConfig();
  const res = await callTool("orion_recall", { query, limit: recallLimit });

  if (!res.ok) {
    if (res.status === 401) {
      const action = await vscode.window.showErrorMessage(
        "Orion: auth token missing or wrong. Open settings to paste it.",
        "Open Settings"
      );
      if (action === "Open Settings") {
        vscode.commands.executeCommand("workbench.action.openSettings", "orion.authToken");
      }
      return;
    }
    vscode.window.showErrorMessage(`Orion error: ${res.error}`);
    return;
  }

  const text = extractText(res.data.content);
  const elapsed = res.data.elapsed_ms;

  // Show in a new untitled markdown doc so the user can read, copy, and
  // keep the result alongside their work. Quick-Pick is too cramped for
  // multi-paragraph recall output.
  const doc = await vscode.workspace.openTextDocument({
    language: "markdown",
    content: `# Orion recall: ${query}\n\n${text}\n\n---\n_${elapsed ? `${elapsed}ms` : "ok"}_\n`
  });
  await vscode.window.showTextDocument(doc, { preview: true, viewColumn: vscode.ViewColumn.Beside });
}

// ── Command: Orion: Memorize selection ──

async function memorizeCommand() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showInformationMessage("Orion: no active editor.");
    return;
  }
  const text = editor.document.getText(editor.selection).trim();
  if (!text) {
    vscode.window.showInformationMessage("Orion: select some text first.");
    return;
  }

  const tag = await vscode.window.showInputBox({
    prompt: "Tag for this memory (optional)",
    placeHolder: "e.g. 'auth-flow', 'meeting-notes', or leave blank"
  });

  const args = { content: text };
  if (tag) args.tags = [tag];

  const res = await callTool("orion_memorize", args);
  if (!res.ok) {
    vscode.window.showErrorMessage(`Orion error: ${res.error}`);
    return;
  }
  vscode.window.showInformationMessage("Orion: memorized.");
}

// ── Command: Orion: Identity ──

async function identityCommand() {
  const res = await callTool("orion_identity", {});
  if (!res.ok) {
    vscode.window.showErrorMessage(`Orion error: ${res.error}`);
    return;
  }
  const text = extractText(res.data.content);
  vscode.window.showInformationMessage(text, { modal: false });
}

// ── Command: Orion: Health ──

async function healthCommand() {
  const { brainBase, authToken } = getConfig();
  const tokenSet = authToken ? "set" : "MISSING";
  try {
    const res = await fetch(`${brainBase}/health`);
    if (!res.ok) {
      vscode.window.showWarningMessage(`Orion brain returned HTTP ${res.status}. Token: ${tokenSet}.`);
      return;
    }
    const data = await res.json();
    vscode.window.showInformationMessage(
      `Orion online · ${data.service} v${data.version} · ${data.tool_count} tools · token ${tokenSet}`
    );
  } catch (e) {
    vscode.window.showErrorMessage(
      `Orion brain unreachable at ${brainBase}. Start it with: python orion_brain_service.py`
    );
  }
}

// ── Activation / deactivation ──

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("orion.recall", recallCommand),
    vscode.commands.registerCommand("orion.memorize", memorizeCommand),
    vscode.commands.registerCommand("orion.identity", identityCommand),
    vscode.commands.registerCommand("orion.health", healthCommand)
  );

  const { showStatusBar } = getConfig();
  if (showStatusBar) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = "orion.health";
    context.subscriptions.push(statusBarItem);
    statusBarItem.show();
    refreshStatusBar();
    // Re-probe every 30s — cheap GET, no auth required.
    statusInterval = setInterval(refreshStatusBar, 30000);
    context.subscriptions.push({ dispose: () => clearInterval(statusInterval) });
  }

  // Re-read config when the user changes settings (e.g. paste auth token).
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("orion")) refreshStatusBar();
    })
  );
}

function deactivate() {
  if (statusInterval) clearInterval(statusInterval);
}

module.exports = { activate, deactivate };
