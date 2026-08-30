#!/usr/bin/env python3
"""
orion_imessage_adapter.py — the iMessage SENSE (Perception Contract §4; build §8 step 4).

The first channel built NATIVE to the contract, and the proof the contract holds: an adapter's
entire job is watch a source, normalize to the canonical §2 event, hand off. It does not decide
importance, does not write to the graph, and does not truncate.

    chat.db row -> normalize -> [ boundary validation ] -> raw stream -> (salience gate, step 5)

PROVENANCE (§3) IS FREE HERE. Apple stamps `is_from_me` at the moment the message is sent, so this
channel needs no efference ledger and no prefix matching — it has ground truth:
    is_from_me = 0  -> external, actor = the sender's handle   (James)
    is_from_me = 1  -> self,     actor = "orion"               (his own outbound)
Polarity PROVEN against real rows 2026-08-30 before a single event was written, because inverting
it would poison every event with backwards provenance — the exact failure this contract exists to
eliminate.

RANGE READER, NOT A TAILER — this is what makes §8.6 free. Backfill must go through the SAME path
as live events ("if backfill needs a special case, the contract is wrong"). So:
    live     = rows above the watermark
    backfill = rows below it
Same code, same boundary, same events. Backfill is a parameter, not a migration.

FAILURE MODE (§9.5) DISSOLVES HERE. chat.db IS the buffer — it is a database, not a stream. If the
pipeline is down the watermark simply does not advance and nothing is lost. The adapter stays dumb.

ATTACHMENTS (§9.3): paths only, never copied. modality becomes image/file; the path lives in meta.

CAPTURE ONLY. Nothing consumes the raw stream yet; no graph writes, no consolidation, no effect on
how replies are sent. Reading chat.db is read-only and does not touch the running monitor.

  --dry-run [N]   normalize the N most recent messages, write NOTHING, print what would be captured
  --live          capture rows above the watermark (the live sense)
  --backfill      capture the entire history through the same path (step 6)
  --status        watermark, coverage, what is left
  --init          set the watermark to now without capturing history
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/orion-code"))
sys.path.insert(0, os.path.expanduser("~/server_data/agents"))

import orion_perception as P                     # the boundary (step 1)

try:                                             # reuse the monitor's decoder, never reimplement it
    from imessage_monitor import _decode_attributed
except Exception:
    _decode_attributed = None

DB = os.path.expanduser("~/Library/Messages/chat.db")
WATERMARK = Path(os.path.expanduser("~/.orion/state/imessage_watermark.json"))
APPLE_EPOCH = 978307200                          # 2001-01-01 -> unix
SURFACE = "imessage"

_SQL = (
    "SELECT m.ROWID AS rowid, m.is_from_me, m.text, m.attributedBody, m.date, m.service, "
    "       m.cache_has_attachments, h.id AS handle, c.chat_identifier "
    "FROM message m "
    "LEFT JOIN handle h ON m.handle_id = h.ROWID "
    "LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID "
    "LEFT JOIN chat c ON c.ROWID = cmj.chat_id "
    "WHERE (m.text IS NOT NULL OR m.attributedBody IS NOT NULL) "
)


def _conn():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True)


def _body(row):
    """The message text, VERBATIM. Modern macOS puts it in attributedBody, not text."""
    if row["text"]:
        return row["text"]
    blob = row["attributedBody"]
    if blob is not None and _decode_attributed is not None:
        try:
            return _decode_attributed(blob) or ""
        except Exception:
            return ""
    return ""


def _attachments(conn, rowid):
    """Paths only (§9.3) — never copy content in."""
    try:
        cur = conn.execute(
            "SELECT a.filename, a.mime_type FROM attachment a "
            "JOIN message_attachment_join j ON j.attachment_id = a.ROWID "
            "WHERE j.message_id = ?", (rowid,))
        return [{"path": r[0], "mime": r[1]} for r in cur if r[0]]
    except Exception:
        return []


def to_event(conn, row):
    """chat.db row -> canonical §2 event. This function IS the adapter (§4: thin and dumb)."""
    text = _body(row)
    if not text.strip():
        return None                                    # nothing said; not an event
    from_me = bool(row["is_from_me"])
    atts = _attachments(conn, row["rowid"]) if row["cache_has_attachments"] else []
    modality = "text"
    if atts:
        modality = "image" if str(atts[0].get("mime") or "").startswith("image/") else "file"
    return P.make_event(
        text,                                          # verbatim, untruncated (§7.3)
        provenance="self" if from_me else "external",  # Apple's ground truth (§3)
        surface=SURFACE,
        direction="outbound" if from_me else "inbound",
        actor="orion" if from_me else (row["handle"] or "unknown"),
        modality=modality,
        thread=row["chat_identifier"] or row["handle"],
        ts=(row["date"] or 0) / 1e9 + APPLE_EPOCH,
        meta={"adapter": "imessage", "rowid": row["rowid"], "service": row["service"],
              "handle": row["handle"], "attachments": atts},
    )


def _read(lo=None, hi=None, limit=None, newest_first=False):
    conn = _conn()
    conn.row_factory = sqlite3.Row
    q = _SQL
    args = []
    if lo is not None:
        q += "AND m.ROWID > ? "
        args.append(lo)
    if hi is not None:
        q += "AND m.ROWID <= ? "
        args.append(hi)
    q += "ORDER BY m.ROWID " + ("DESC " if newest_first else "ASC")
    if limit:
        q += "LIMIT %d" % int(limit)
    for row in conn.execute(q, args):
        ev = to_event(conn, row)
        if ev:
            yield row["rowid"], ev


def _mark(default=0):
    try:
        return int(json.loads(WATERMARK.read_text()).get("rowid", default))
    except Exception:
        return default


def _set_mark(rowid):
    try:
        WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        tmp = WATERMARK.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"rowid": int(rowid), "ts": time.time()}))
        tmp.replace(WATERMARK)
    except Exception:
        pass


def _max_rowid():
    try:
        conn = _conn()
        return int(conn.execute("SELECT MAX(ROWID) FROM message").fetchone()[0] or 0)
    except Exception:
        return 0


def capture(lo=None, hi=None, limit=None, advance=True):
    """Push a ROWID range through the boundary. Live and backfill are the SAME call (§8.6).
    The watermark advances only on a successful capture, so a failure loses nothing."""
    n_ok = n_rej = 0
    last = lo or 0
    prov = {"external": 0, "self": 0}
    for rowid, ev in _read(lo, hi, limit):
        r = P.ingest(ev)
        if r.get("ok"):
            n_ok += 1
            prov[ev["provenance"]] += 1
        else:
            n_rej += 1
        last = rowid
    if advance and n_ok and last:
        _set_mark(last)
    return {"captured": n_ok, "rejected": n_rej, "last_rowid": last,
            "external": prov["external"], "self": prov["self"]}


def dry_run(n=10):
    print("DRY RUN — normalizing %d most recent messages, writing NOTHING\n" % n)
    rows = list(_read(limit=n, newest_first=True))
    ok = bad = 0
    for rowid, ev in rows:
        valid, why = P.validate(ev)
        ok, bad = (ok + 1, bad) if valid else (ok, bad + 1)
        stamp = time.strftime("%m-%d %H:%M", time.localtime(ev["ts"]))
        print("  #%-5s %s  prov=%-8s dir=%-8s actor=%-16s len=%-5d %s"
              % (rowid, stamp, ev["provenance"], ev["direction"],
                 str(ev["actor"])[:16], len(ev["content"]),
                 "" if valid else "INVALID: " + why))
        print("        %s" % ev["content"].replace("\n", " ")[:96])
    print("\n  valid=%d invalid=%d  (invalid must be 0)" % (ok, bad))
    print("  NOTHING WAS WRITTEN.")
    return bad == 0


def status():
    mark, mx = _mark(), _max_rowid()
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM message WHERE (text IS NOT NULL OR "
                         "attributedBody IS NOT NULL)").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM message WHERE ROWID > ? AND (text IS NOT NULL OR "
                           "attributedBody IS NOT NULL)", (mark,)).fetchone()[0]
    raw = 0
    try:
        raw = sum(1 for _ in P.RAW.open(encoding="utf-8"))
    except Exception:
        pass
    print("watermark rowid : %d  (db max %d)" % (mark, mx))
    print("messages in db  : %d" % total)
    print("pending capture : %d" % pending)
    print("raw stream      : %d events total (all surfaces)" % raw)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    if arg == "--dry-run":
        raise SystemExit(0 if dry_run(n) else 1)
    elif arg == "--status":
        status()
    elif arg == "--init":
        mx = _max_rowid()
        _set_mark(mx)
        print("watermark initialized at rowid %d — live capture starts from here" % mx)
    elif arg == "--live":
        print(json.dumps(capture(lo=_mark())))
    elif arg == "--backfill":
        print(json.dumps(capture(lo=0, hi=_mark() or None, advance=False)))
    else:
        print(__doc__)
