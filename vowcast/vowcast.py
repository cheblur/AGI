#!/usr/bin/env python3
"""Vowcast: a trusted-local-operator authenticated SQLite mailbox."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time
import uuid
from pathlib import Path


class VowcastError(Exception):
    pass


class AuthError(VowcastError):
    pass


class IntegrityError(VowcastError):
    pass


class ReplayError(VowcastError):
    pass


class ExpiredError(VowcastError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
  agent_id TEXT PRIMARY KEY, enrolled_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
  body TEXT NOT NULL, bodyhash TEXT NOT NULL, sent_at INTEGER NOT NULL,
  expiry INTEGER NOT NULL, signature TEXT NOT NULL,
  FOREIGN KEY(sender) REFERENCES agents(agent_id),
  FOREIGN KEY(recipient) REFERENCES agents(agent_id)
);
CREATE TABLE IF NOT EXISTS acknowledgements (
  ack_id TEXT PRIMARY KEY, message_id TEXT UNIQUE NOT NULL,
  recipient TEXT NOT NULL, acked_at INTEGER NOT NULL, signature TEXT NOT NULL,
  FOREIGN KEY(message_id) REFERENCES messages(id)
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL,
  occurred_at INTEGER NOT NULL, actor TEXT, object_id TEXT,
  details TEXT NOT NULL
);
"""


def _connect(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _validate_agent(agent_id):
    if not isinstance(agent_id, str) or not agent_id or len(agent_id) > 100 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in agent_id):
        raise VowcastError("agent id must use 1-100 letters, digits, dot, underscore, or hyphen")


def _key_path(key_dir, agent_id):
    _validate_agent(agent_id)
    return Path(key_dir) / (agent_id + ".key")


def _load_key(key_dir, agent_id):
    path = _key_path(key_dir, agent_id)
    try:
        key = bytes.fromhex(path.read_text(encoding="ascii").strip())
        if len(key) != 32:
            raise ValueError("invalid key length")
        return key
    except (OSError, UnicodeError, ValueError):
        raise AuthError("no usable credential for agent") from None


def _canonical(envelope):
    fields = {k: envelope[k] for k in ("id", "from", "to", "body", "bodyhash", "time", "expiry")}
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign(key, payload):
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _event(con, event, when, actor=None, object_id=None, details=None):
    con.execute("INSERT INTO events(event,occurred_at,actor,object_id,details) VALUES(?,?,?,?,?)",
                (event, when, actor, object_id, json.dumps(details or {}, sort_keys=True, separators=(",", ":"))))


def init_store(db_path, key_dir):
    db = Path(db_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    keys = Path(key_dir).expanduser()
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(keys, 0o700)
    with _connect(db) as con:
        con.executescript(SCHEMA)
    return str(db)


def enroll_agent(db_path, key_dir, agent_id):
    _validate_agent(agent_id)
    path = _key_path(key_dir, agent_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    now = int(time.time())
    try:
        with _connect(db_path) as con:
            con.execute("INSERT INTO agents(agent_id,enrolled_at) VALUES(?,?)", (agent_id, now))
            _event(con, "agent.enrolled", now, agent_id, agent_id)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(secrets.token_hex(32) + "\n")
        os.chmod(path, 0o600)
    except sqlite3.IntegrityError:
        raise ReplayError("agent already enrolled") from None
    except Exception:
        with _connect(db_path) as con:
            con.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        raise
    return str(path)


def _envelope(row):
    return {"id": row["id"], "from": row["sender"], "to": row["recipient"],
            "body": row["body"], "bodyhash": row["bodyhash"],
            "time": row["sent_at"], "expiry": row["expiry"]}


def _verify_message(row, key_dir, now=None):
    env = _envelope(row)
    actual = hashlib.sha256(env["body"].encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual, env["bodyhash"]):
        raise IntegrityError("message body hash mismatch")
    expected = _sign(_load_key(key_dir, env["from"]), _canonical(env))
    if not hmac.compare_digest(expected, row["signature"]):
        raise IntegrityError("message signature mismatch")
    if (int(time.time()) if now is None else int(now)) >= env["expiry"]:
        raise ExpiredError("message expired")
    return env


def _ack_payload(ack_id, message_id, recipient, when):
    return json.dumps({"ack_id": ack_id, "message_id": message_id, "recipient": recipient,
                       "time": when}, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _verify_ack(row, key_dir):
    if row["ack_id"] is None:
        return
    if row["ack_recipient"] != row["recipient"]:
        raise IntegrityError("acknowledgement recipient mismatch")
    expected = _sign(_load_key(key_dir, row["recipient"]),
                     _ack_payload(row["ack_id"], row["id"], row["ack_recipient"], row["acked_at"]))
    if not hmac.compare_digest(expected, row["ack_signature"]):
        raise IntegrityError("acknowledgement signature mismatch")


def send_message(db_path, key_dir, sender, recipient, body, expiry_seconds=3600, now=None, message_id=None):
    _validate_agent(sender); _validate_agent(recipient)
    if not isinstance(body, str) or not body:
        raise VowcastError("body must be a non-empty string")
    when = int(time.time()) if now is None else int(now)
    ttl = int(expiry_seconds)
    if ttl <= 0:
        raise VowcastError("ttl must be positive")
    mid = str(uuid.uuid4()) if message_id is None else message_id
    if not isinstance(mid, str) or not mid or len(mid) > 200:
        raise VowcastError("invalid message id")
    key = _load_key(key_dir, sender)
    env = {"id": mid, "from": sender, "to": recipient, "body": body,
           "bodyhash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
           "time": when, "expiry": when + ttl}
    sig = _sign(key, _canonical(env))
    try:
        with _connect(db_path) as con:
            enrolled_sender = con.execute("SELECT 1 FROM agents WHERE agent_id=?", (sender,)).fetchone()
            if not enrolled_sender:
                raise AuthError("sender is not enrolled")
            known = con.execute("SELECT 1 FROM agents WHERE agent_id=?", (recipient,)).fetchone()
            if not known:
                raise AuthError("recipient is not enrolled")
            con.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)",
                        (mid, sender, recipient, env["body"], env["bodyhash"], when, env["expiry"], sig))
            _event(con, "message.delivered", when, sender, mid,
                   {"id": mid, "from": sender, "to": recipient,
                    "bodyhash": env["bodyhash"], "time": when, "expiry": env["expiry"]})
    except sqlite3.IntegrityError:
        raise ReplayError("message id already used") from None
    return mid


def list_inbox(db_path, key_dir, recipient, include_read=False, now=None):
    _load_key(key_dir, recipient)
    sql = ("SELECT m.*, a.ack_id, a.acked_at, a.recipient AS ack_recipient, "
           "a.signature AS ack_signature FROM messages m "
           "LEFT JOIN acknowledgements a ON a.message_id=m.id "
           "WHERE m.recipient=? ORDER BY m.sent_at,m.id")
    out = []
    with _connect(db_path) as con:
        for row in con.execute(sql, (recipient,)):
            try:
                env = _verify_message(row, key_dir, now)
            except ExpiredError:
                continue
            _verify_ack(row, key_dir)
            if row["ack_id"] is not None and not include_read:
                continue
            env.update({"ack_id": row["ack_id"], "acked_at": row["acked_at"]})
            out.append(env)
    return out


def acknowledge_message(db_path, key_dir, recipient, message_id, now=None):
    key = _load_key(key_dir, recipient)
    when = int(time.time()) if now is None else int(now)
    with _connect(db_path) as con:
        row = con.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not row:
            raise VowcastError("message not found")
        if row["recipient"] != recipient:
            raise AuthError("only the intended recipient may acknowledge")
        _verify_message(row, key_dir, when)
        ack_id = str(uuid.uuid4())
        payload = _ack_payload(ack_id, message_id, recipient, when)
        sig = _sign(key, payload)
        try:
            con.execute("INSERT INTO acknowledgements VALUES(?,?,?,?,?)", (ack_id, message_id, recipient, when, sig))
        except sqlite3.IntegrityError:
            raise ReplayError("message already acknowledged") from None
        _event(con, "message.read", when, recipient, message_id, {"ack_id": ack_id, "recipient": recipient})
    return ack_id


def export_events(db_path, output_path):
    with _connect(db_path) as con:
        rows = [dict(r) for r in con.execute("SELECT seq,event,occurred_at,actor,object_id,details FROM events ORDER BY seq")]
    for row in rows:
        row["details"] = json.loads(row["details"])
    Path(output_path).write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(rows)


def _parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="vowcast.db")
    p.add_argument("--keys", default=str(Path.home() / ".local/share/vowcast/keys"))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    e = sub.add_parser("enroll"); e.add_argument("agent")
    s = sub.add_parser("send"); s.add_argument("--from", dest="sender", required=True); s.add_argument("--to", required=True); s.add_argument("--body", required=True); s.add_argument("--ttl", type=int, default=3600); s.add_argument("--id")
    i = sub.add_parser("inbox"); i.add_argument("agent"); i.add_argument("--all", action="store_true")
    a = sub.add_parser("ack"); a.add_argument("agent"); a.add_argument("message_id")
    x = sub.add_parser("export"); x.add_argument("output")
    return p


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "init": result = init_store(args.db, args.keys)
    elif args.command == "enroll": result = enroll_agent(args.db, args.keys, args.agent)
    elif args.command == "send": result = send_message(args.db, args.keys, args.sender, args.to, args.body, args.ttl, message_id=args.id)
    elif args.command == "inbox": result = list_inbox(args.db, args.keys, args.agent, args.all)
    elif args.command == "ack": result = acknowledge_message(args.db, args.keys, args.agent, args.message_id)
    else: result = export_events(args.db, args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (VowcastError, sqlite3.Error, OSError) as exc:
        print("error: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
