// Orion brain client — Manifest V3 service worker.
//
// The popup asks this worker to call the local Orion brain. The worker
// holds the auth token (stored once in the extension options page) and
// is the single place that talks to http://127.0.0.1:5556. Running the
// fetch from the service worker rather than the popup means CORS and
// the bearer token never leak to the active tab's content scripts.
//
// Endpoints reached:
//   GET  /health     — liveness probe (no auth)
//   GET  /v1/tools   — list available brain tools (auth)
//   POST /v1/call    — invoke a tool by name (auth)
//
// All errors get normalized to { ok: false, error: "<message>" } so the
// popup can render them without parsing surprises.

const BRAIN_BASE_DEFAULT = "http://127.0.0.1:5556";

async function getConfig() {
  const stored = await chrome.storage.local.get(["brainBase", "authToken"]);
  return {
    brainBase: stored.brainBase || BRAIN_BASE_DEFAULT,
    authToken: stored.authToken || ""
  };
}

async function brainFetch(path, init = {}) {
  const { brainBase, authToken } = await getConfig();
  const headers = { ...(init.headers || {}) };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;
  if (init.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(`${brainBase}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).error || ""; } catch (_) { detail = res.statusText; }
    return { ok: false, status: res.status, error: detail || `HTTP ${res.status}` };
  }
  const data = await res.json();
  return { ok: true, data };
}

// ── Public actions the popup can request ──

async function probeHealth() {
  // /health is unauthenticated — useful diagnostic for "is the brain even
  // running?" before we ask the user to fix their auth token.
  try {
    const { brainBase } = await getConfig();
    const res = await fetch(`${brainBase}/health`);
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, data };
  } catch (e) {
    return { ok: false, error: e.message || "brain unreachable" };
  }
}

async function listTools() {
  return brainFetch("/v1/tools");
}

async function callTool(name, args) {
  return brainFetch("/v1/call", {
    method: "POST",
    body: JSON.stringify({ name, arguments: args || {} })
  });
}

// ── Message router ──

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.action) {
        case "health":
          sendResponse(await probeHealth());
          break;
        case "listTools":
          sendResponse(await listTools());
          break;
        case "callTool":
          sendResponse(await callTool(msg.name, msg.args));
          break;
        case "recall":
          // Convenience shortcut for the most common case.
          sendResponse(await callTool("orion_recall", {
            query: msg.query,
            limit: msg.limit || 5
          }));
          break;
        default:
          sendResponse({ ok: false, error: `unknown action: ${msg.action}` });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message || String(e) });
    }
  })();
  // async response pattern
  return true;
});
