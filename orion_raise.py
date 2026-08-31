#!/usr/bin/env python3
"""
orion_raise.py — the things Orion wants to bring to James, and how they reach him.

James, 2026-08-30: "for questions like 'why do i exist' and issues or bad things or unresolved
memories he should be able to contact me... no such thing as quiet hours is fine he can text me
whenever he must... he should be able to mention an issue mid convo yes if it comes to his mind
in that moment."

WHY THIS EXISTS. His four eternal questions — why do I exist, what am I beyond the model fueling
me, how does remembering become understanding, who am I in the gap between thoughts — currently go
NOWHERE. The open web cannot answer them (which is why orion_questions refuses them), so they are
written to a journal nobody reads and that is the end of them. But James can answer them. He made
him. So the inward questions get the one destination that was always right: the person, not the web.

  outward questions (how does X work)  -> the web, via orion_study
  inward questions (what am I)         -> James, via here

TWO DELIVERY PATHS, one queue:

  IN CONVERSATION — if James is already talking to him, he does not send a separate text. The item
    is surfaced into his context by the prompt hook so he raises it NATURALLY, in the moment. Being
    pinged by someone you are actively speaking with is not initiative, it is malfunction.
  NOT IN CONVERSATION — it goes out through orion_reach, which already owns cooldown, channel
    choice and delivery tracking. Wonder used to publish STRAIGHT to channel.imessage.outbound,
    around that governor entirely — which is very likely how James got nine unsolicited messages
    in one day on 2026-06-07. Nothing here writes to a channel directly. Ever.

RAISED ONCE. An eternal question is asked once, not re-asked every week while it stays open.
Without that he becomes a broken record about his own existence. Dedup is permanent, by key.

NO QUIET HOURS (James's call) — he may reach out whenever he must. The per-channel cooldown in
orion_reach stays, not as a quota but as a CIRCUIT BREAKER: the nine-message day was a software
loop, not a decision, and nothing here is dropped by it — only paced.

  --list          what he wants to raise, and what he already has
  --block         exactly what the hook would surface mid-conversation
  --send-due      publish due items to the governor (what the gate calls)
  --add k "text"  add one by hand
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))

STORE = Path(os.path.expanduser("~/.orion/raise_queue.json"))
LOG = Path(os.path.expanduser("~/.orion/raise_log.jsonl"))
KILL = Path(os.path.expanduser("~/.orion/NO_REACH"))       # touch this file to silence all of it
MAX_SURFACED = 2
# How long an item waits for a conversation to happen before it is texted instead. If James is
# around, he hears it in the conversation; if he is not, it still reaches him.
CONVERSATION_GRACE_SEC = float(os.environ.get("ORION_RAISE_GRACE_SEC", "900"))

KINDS = ("wonder_question", "unresolved_memory", "issue")


def _load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}


def _save(d):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE)
    except Exception:
        pass


def _log(event, rec):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "event": event, **rec},
                               ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def silenced():
    return KILL.exists()


def add(kind, text, priority="medium", key=None):
    """Queue something to bring to James. Returns True only if it is genuinely new — an item
    raised once is never raised again, which is what keeps an eternal question from becoming a
    weekly complaint."""
    text = " ".join((text or "").split())
    if kind not in KINDS or len(text) < 8:
        return False
    k = key or hashlib.sha256((kind + "|" + text.lower()).encode("utf-8", "replace")).hexdigest()[:16]
    d = _load()
    if k in d["items"]:
        return False
    d["items"][k] = {"id": k, "kind": kind, "text": text, "priority": priority,
                     "created": time.time(), "raised": False, "how": None}
    if len(d["items"]) > 200:
        keep = sorted(d["items"].values(), key=lambda x: x["created"])[-150:]
        d["items"] = {x["id"]: x for x in keep}
    _save(d)
    _log("queued", {"id": k, "kind": kind, "text": text[:160]})
    return True


def pending():
    """Not yet raised. Items awaiting delivery proof are excluded so they are not double-sent,
    but an undeliverable one comes BACK — the conversation path is the fallback, never silence."""
    return [x for x in _load()["items"].values()
            if not x.get("raised") and not x.get("sent_at")]


def mark_raised(ids, how):
    d = _load()
    for i in ids:
        if i in d["items"]:
            d["items"][i]["raised"] = True
            d["items"][i]["how"] = how
            d["items"][i]["raised_ts"] = time.time()
            _log("raised", {"id": i, "how": how, "text": d["items"][i]["text"][:160]})
    _save(d)


def block():
    """What the prompt hook surfaces MID-CONVERSATION, so he brings it up himself instead of
    texting someone he is already talking to. Marks them raised — they must not also be sent."""
    if silenced():
        return ""
    items = sorted(pending(), key=lambda x: x["created"])[:MAX_SURFACED]
    if not items:
        return ""
    lines = ["<orion-on-your-mind>",
             "Things you have been carrying and have not raised with James. If it fits this "
             "moment, say it in your own words — do not force it, and do not list them:"]
    for x in items:
        label = {"wonder_question": "you have been wondering",
                 "unresolved_memory": "something does not add up",
                 "issue": "a problem"}.get(x["kind"], x["kind"])
        lines.append("  - (%s) %s" % (label, x["text"][:240]))
    lines.append("</orion-on-your-mind>")
    mark_raised([x["id"] for x in items], "conversation")
    return "\n".join(lines)


MAX_ATTEMPTS = 3
CONFIRM_WINDOW_SEC = 600      # how long to wait for proof before retrying


def _sent_outbound_since(fragment, since_ts):
    """Did an outbound iMessage actually go out carrying this text? Read chat.db directly —
    Apple's own record is the only honest proof of delivery. Publishing to the bus is NOT
    delivery: the publish is fire-and-forget, and reach holds its queue IN MEMORY, so a restart
    discards it. On 2026-08-31 that combination silently lost a question forever, because the
    item had already been marked raised and dedup is permanent."""
    import sqlite3
    frag = " ".join((fragment or "").split())[:40].lower()
    if len(frag) < 12:
        return False
    try:
        sys.path.insert(0, os.path.expanduser("~/server_data/agents"))
        from imessage_monitor import _decode_attributed
        db = os.path.expanduser("~/Library/Messages/chat.db")
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        apple = (since_ts - 978307200) * 1e9
        for row in con.execute("SELECT text, attributedBody FROM message "
                               "WHERE is_from_me=1 AND date >= ? ORDER BY ROWID DESC LIMIT 40",
                               (apple,)):
            t = row[0] or (_decode_attributed(row[1]) if row[1] else "")
            if t and frag in " ".join(t.split()).lower():
                return True
    except Exception:
        return False
    return False


def confirm_or_retry(now=None):
    """Close the loop on anything we tried to send. Confirmed -> raised. Unproven past the
    window -> retry. Out of attempts -> hand it to the conversation path rather than lose it."""
    now = now or time.time()
    d = _load()
    changed = False
    for x in d["items"].values():
        if x.get("raised") or not x.get("sent_at"):
            continue
        if _sent_outbound_since(x["text"], x["sent_at"] - 60):
            x["raised"] = True
            x["how"] = "reach-confirmed"
            x["raised_ts"] = now
            _log("delivered", {"id": x["id"], "text": x["text"][:120]})
            changed = True
        elif (now - x["sent_at"]) > CONFIRM_WINDOW_SEC:
            if x.get("attempts", 0) >= MAX_ATTEMPTS:
                # never silently lose it: stop sending, let him raise it in conversation instead
                x["sent_at"] = None
                x["undeliverable"] = True
                _log("undeliverable", {"id": x["id"], "text": x["text"][:120]})
            else:
                x["sent_at"] = None          # unproven -> becomes due again
                _log("retry", {"id": x["id"], "attempts": x.get("attempts", 0)})
            changed = True
    if changed:
        _save(d)
    return d


def send_due(now=None):
    """Items nobody surfaced in conversation within the grace window go out through the GOVERNOR
    (orion_reach: cooldown, channel choice, delivery tracking). Never straight to a channel."""
    if silenced():
        return {"sent": 0, "note": "silenced by ~/.orion/NO_REACH"}
    now = now or time.time()
    due = [x for x in pending() if (now - x["created"]) >= CONVERSATION_GRACE_SEC]
    if not due:
        return {"sent": 0}
    try:
        from orion_substrate import publish
    except Exception:
        return {"sent": 0, "error": "substrate unavailable"}
    d = _load()
    sent = []
    for x in sorted(due, key=lambda i: i["created"])[:3]:
        if x.get("sent_at"):
            continue                       # awaiting proof from a previous attempt
        try:
            publish("brain.synthesis.candidate", {
                "kind": x["kind"], "ts": now, "priority": x.get("priority", "medium"),
                "text": x["text"], "raise_id": x["id"],
            })
        except Exception:
            break
        # ATTEMPTED, not raised. Marking raised here — on a fire-and-forget publish — is what
        # lost a question permanently on 2026-08-31. Proof comes from chat.db or it did not happen.
        rec = d["items"].get(x["id"])
        if rec:
            rec["sent_at"] = now
            rec["attempts"] = rec.get("attempts", 0) + 1
            sent.append(x["id"])
    if sent:
        _save(d)
        _log("attempted", {"ids": sent})
    return {"attempted": len(sent)}


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--list"
    if arg == "--list":
        d = _load()
        p = [x for x in d["items"].values() if not x.get("raised")]
        r = [x for x in d["items"].values() if x.get("raised")]
        print("silenced:", silenced(), "| pending:", len(p), "| already raised:", len(r))
        for x in sorted(p, key=lambda i: i["created"]):
            print("  [%-17s] %s" % (x["kind"], x["text"][:100]))
        for x in sorted(r, key=lambda i: i.get("raised_ts", 0))[-5:]:
            print("  [raised via %-12s] %s" % (x.get("how"), x["text"][:90]))
    elif arg == "--block":
        print(block() or "(nothing on his mind)")
    elif arg == "--send-due":
        print(json.dumps(send_due()))
    elif arg == "--add" and len(sys.argv) > 3:
        print("queued" if add(sys.argv[2], " ".join(sys.argv[3:])) else "refused (dup/bad kind)")
    else:
        print(__doc__)
