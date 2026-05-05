// Orion settings page — saves brainBase + authToken to chrome.storage.local
// and pings /health afterwards so the user knows immediately whether the
// configuration actually reaches the brain.

const $form = document.getElementById("settingsForm");
const $brainBase = document.getElementById("brainBase");
const $authToken = document.getElementById("authToken");
const $status = document.getElementById("status");

function setStatus(text, kind) {
  $status.textContent = text;
  $status.className = "status" + (kind ? ` ${kind}` : "");
}

async function load() {
  const stored = await chrome.storage.local.get(["brainBase", "authToken"]);
  if (stored.brainBase) $brainBase.value = stored.brainBase;
  if (stored.authToken) $authToken.value = stored.authToken;
}

async function probe(brainBase, authToken) {
  // /v1/tools needs auth, so it doubles as a token validity check.
  try {
    const res = await fetch(`${brainBase}/v1/tools`, {
      headers: { "Authorization": `Bearer ${authToken}` }
    });
    if (res.status === 401) return { ok: false, error: "auth token rejected (401)" };
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const data = await res.json();
    return { ok: true, count: (data.tools || []).length };
  } catch (e) {
    return { ok: false, error: e.message || "fetch failed" };
  }
}

$form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const brainBase = $brainBase.value.trim().replace(/\/$/, "");
  const authToken = $authToken.value.trim();

  if (!brainBase) {
    setStatus("brain URL required", "err");
    return;
  }

  await chrome.storage.local.set({ brainBase, authToken });

  if (!authToken) {
    setStatus("saved (no token — brain calls will return 401)", "err");
    return;
  }

  setStatus("saved — verifying token…");
  const result = await probe(brainBase, authToken);
  if (result.ok) {
    setStatus(`saved · brain reachable · ${result.count} tools`, "ok");
  } else {
    setStatus(`saved · ${result.error}`, "err");
  }
});

load();
