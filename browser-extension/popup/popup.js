// Orion popup — talks to the brain through the service worker.

const $status = document.getElementById("status");
const $form = document.getElementById("recallForm");
const $query = document.getElementById("query");
const $result = document.getElementById("result");
const $openOptions = document.getElementById("openOptions");

function setStatus(text, kind) {
  $status.textContent = text;
  $status.className = "status" + (kind ? ` ${kind}` : "");
}

function showResult(text, kind) {
  $result.textContent = text;
  $result.className = "result" + (kind ? ` ${kind}` : "");
}

async function send(action, extra = {}) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action, ...extra }, resolve);
  });
}

async function probeBrain() {
  setStatus("checking…");
  const res = await send("health");
  if (!res || !res.ok) {
    setStatus("offline", "err");
    showResult(
      "Can't reach the Orion brain at http://127.0.0.1:5556.\n\n" +
      "Start it with:\n  python orion_brain_service.py\n\n" +
      "Then click Settings to paste your auth token.",
      "error"
    );
    return false;
  }
  const tools = res.data.tool_count;
  setStatus(`online · ${tools} tools`, "ok");
  return true;
}

$form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = $query.value.trim();
  if (!query) return;

  showResult("…thinking…");
  const res = await send("recall", { query, limit: 5 });

  if (!res || !res.ok) {
    const msg = (res && res.error) ? res.error : "unknown error";
    if ((res && res.status) === 401) {
      showResult(
        `Unauthorized — auth token missing or wrong.\n\n` +
        `Click Settings below and paste your token from\n  ~/.orion/auth-token`,
        "error"
      );
    } else {
      showResult(`Error: ${msg}`, "error");
    }
    return;
  }

  // /v1/call returns { content: [{ type: "text", text: "..." }, ...], elapsed_ms }
  const content = res.data.content || [];
  const text = content
    .filter(c => c && c.type === "text")
    .map(c => c.text)
    .join("\n\n") || "(no result)";
  const elapsed = res.data.elapsed_ms;
  showResult(elapsed ? `${text}\n\n— ${elapsed}ms` : text);
});

$openOptions.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

probeBrain();
