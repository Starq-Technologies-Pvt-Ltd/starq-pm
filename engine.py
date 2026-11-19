"""starq-pm dual store: append-only SHA-256 hash-chained JSONL = truth;
SQLite projections = rebuildable query cache. Chain-first writes; fail-closed F-04/F-05/F-12.
stdlib only. Storage convention: plugins.plugin_storage.plugin_data_dir at the SDK boundary;
the core takes an explicit data_dir so it is testable without Hermes."""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(body):
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChainBreak(Exception):
    def __init__(self, seq):
        self.seq = seq
        super().__init__(f"chain break at seq {seq}")


class Store:
    """One directory per plugin: events.jsonl, data.db, quarantine, exports."""

    def __init__(self, data_dir, clock=None):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "quarantine").mkdir(exist_ok=True)
        (self.dir / "exports").mkdir(exist_ok=True)
        self.chain_path = self.dir / "events.jsonl"
        self.clock = clock or utcnow
        self._lock = threading.RLock()  # ponytail: one process-level reentrant lock; per-entity locks only if measured contention demands it
        self.degraded = False
        self.db = sqlite3.connect(str(self.dir / "data.db"), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self.seq, self.tail = self._read_tail()

    # ---------- schema ----------
    def _init_schema(self):
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS entities (
                kind TEXT, id TEXT, project_id TEXT, data TEXT, PRIMARY KEY (kind, id));
            CREATE TABLE IF NOT EXISTS board_events (
                seq INTEGER PRIMARY KEY, wp_id TEXT, from_state TEXT, to_state TEXT,
                actor_role TEXT, actor_occupant TEXT, ts TEXT, reason TEXT);
            CREATE INDEX IF NOT EXISTS ix_board_wp ON board_events (wp_id, ts);
            CREATE TABLE IF NOT EXISTS events_index (
                seq INTEGER PRIMARY KEY, type TEXT, ts TEXT, actor_role TEXT,
                actor_occupant TEXT, entity_ref TEXT);
            CREATE INDEX IF NOT EXISTS ix_events_type ON events_index (type);
            """
        )
        self.db.execute("INSERT OR IGNORE INTO meta (k, v) VALUES ('schema_version', '1')")
        self.db.commit()

    def _read_tail(self):
        seq, tail = 0, GENESIS
        if self.chain_path.exists():
            with open(self.chain_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    e = json.loads(line)
                    seq, tail = e["seq"], e["hash"]
        return seq, tail

    # ---------- chain ----------
    def _build(self, type, actor_role, actor_occupant, entity_ref, payload):
        body = {
            "seq": self.seq + 1, "ts": self.clock(), "type": type,
            "actor_role": actor_role, "actor_occupant": actor_occupant,
            "entity_ref": entity_ref, "payload": payload,
            "prev_hash": self.tail, "schema_version": 1,
        }
        body["hash"] = event_hash(body)
        return body

    def append(self, type, actor_role, actor_occupant, entity_ref, payload):
        """Chain-first (F-04): if the chain write fails nothing is committed.
 Tamper check before append (F-05): a broken chain refuses writes."""
        with self._lock:
            # ponytail: full O(n) verify per append (O(n^2) lifetime) — correct fail-closed F-05;
            # upgrade to cached verified-head + tail check if append latency measurably suffers at scale.
            ok, broken = self.verify_chain()
            if not ok:
                self._quarantine("chain_break", {"broken_seq": broken})
                raise ChainBreak(broken)
            e = self._build(type, actor_role, actor_occupant, entity_ref, payload)
            try:
                with open(self.chain_path, "a", encoding="utf-8") as f:
                    f.write(canonical(e) + "\n")
                    f.flush()
                    import os
                    os.fsync(f.fileno())
            except OSError as exc:
                raise OSError(f"F-04 store write failed: {exc}") from exc
            self.seq, self.tail = e["seq"], e["hash"]
            try:
                self._apply(e)
                self.db.commit()
            except sqlite3.Error:
                self.degraded = True  # F-12: truth exists; reads degrade until rebuild
            return e

    def append_many(self, events):
        """events: list of (type, actor_role, actor_occupant, entity_ref, payload)."""
        return [self.append(*ev) for ev in events]

    def _quarantine(self, kind, info):
        p = self.dir / "quarantine" / f"{kind}-{self.seq + 1}.json"
        p.write_text(canonical({"kind": kind, "ts": self.clock(), **info}), encoding="utf-8")

    def verify_chain(self):
        """Recompute every hash from genesis. O(n), on demand. Returns (ok, broken_seq|None)."""
        prev = GENESIS
        n = 0
        if not self.chain_path.exists():
            return True, None
        with open(self.chain_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    return False, n
                body = {k: v for k, v in e.items() if k != "hash"}
                if e.get("prev_hash") != prev or event_hash(body) != e.get("hash") or e.get("seq") != n:
                    return False, n
                prev = e["hash"]
        return True, None

    def head(self):
        return {"seq": self.seq, "hash": self.tail}

    def checkpoint(self):
        """Final-line gap recovery: a crash mid-append
 can leave a partial final line. If the ONLY defect is an incomplete final line,
 truncate to the last complete event (the checkpoint), quarantine the partial bytes,
 and re-read the tail. Earlier hash breaks are NOT auto-healed (F-05 fail-closed).
 Returns {"healed": bool, "seq": int, "broken_seq": int|None}."""
        if not self.chain_path.exists():
            return {"healed": False, "seq": 0, "broken_seq": None}
        raw = self.chain_path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        if not lines:
            return {"healed": False, "seq": 0, "broken_seq": None}
        try:
            json.loads(lines[-1])
            last_complete = True
        except json.JSONDecodeError:
            last_complete = False
        if last_complete:
            ok, broken = self.verify_chain()
            return {"healed": False, "seq": self.seq, "broken_seq": broken}
        prefix = "\n".join(lines[:-1]) + ("\n" if len(lines) > 1 else "")
        prev, n, ok = GENESIS, 0, True
        for line in lines[:-1]:
            if not line.strip():
                continue
            n += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                ok = False
                break
            body = {k: v for k, v in e.items() if k != "hash"}
            if e.get("prev_hash") != prev or event_hash(body) != e.get("hash") or e.get("seq") != n:
                ok = False
                break
            prev = e["hash"]
        if not ok:
            return {"healed": False, "seq": self.seq, "broken_seq": n or 1}
        self._quarantine("partial_final_line", {"partial": lines[-1][:500], "checkpoint_seq": n})
        self.chain_path.write_text(prefix, encoding="utf-8")
        self.seq, self.tail = self._read_tail()
        return {"healed": True, "seq": self.seq, "broken_seq": None}

    def events(self):
        if not self.chain_path.exists():
            return
        with open(self.chain_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # ---------- projections ----------
    def _apply(self, e):
        t, p = e["type"], e["payload"]
        self.db.execute(
            "INSERT INTO events_index (seq, type, ts, actor_role, actor_occupant, entity_ref) VALUES (?,?,?,?,?,?)",
            (e["seq"], t, e["ts"], e["actor_role"], e["actor_occupant"], e["entity_ref"]),
        )
        if t == "entity_upsert":
            self.db.execute(
                "INSERT INTO entities (kind, id, project_id, data) VALUES (?,?,?,?) "
                "ON CONFLICT(kind, id) DO UPDATE SET data=excluded.data, project_id=excluded.project_id",
                (p["kind"], p["id"], p.get("project_id"), canonical(p["data"])),
            )
        elif t == "board_transition":
            self.db.execute(
                "INSERT INTO board_events (seq, wp_id, from_state, to_state, actor_role, actor_occupant, ts, reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (e["seq"], p["wp_id"], p["from_state"], p["to_state"], e["actor_role"], e["actor_occupant"], e["ts"], p.get("reason", "")),
            )
            wp = self.get("work_package", p["wp_id"])
            if wp is not None:
                wp["state"] = p["to_state"]
                if p["to_state"] == "executing" and not wp.get("started_ts"):
                    wp["started_ts"] = e["ts"]
                if p["to_state"] in ("accepted", "closed"):
                    wp["finished_ts"] = e["ts"]
                if p["to_state"] == "blocked":
                    wp["block_ts"] = e["ts"]
                if p["to_state"] == "executing":
                    wp["block_ts"] = None
                self.db.execute(
                    "UPDATE entities SET data=? WHERE kind='work_package' AND id=?",
                    (canonical(wp), p["wp_id"]),
                )

    def rebuild(self):
        """Replay-as-migration: drop projections, replay chain. F-12 recovery."""
        with self._lock:
            # ponytail: full O(n) verify per append (O(n^2) lifetime) — correct fail-closed F-05;
            # upgrade to cached verified-head + tail check if append latency measurably suffers at scale.
            ok, broken = self.verify_chain()
            if not ok:
                raise ChainBreak(broken)
            self.db.executescript(
                "DELETE FROM entities; DELETE FROM board_events; DELETE FROM events_index;"
            )
            for e in self.events():
                self._apply(e)
            self.db.commit()
            self.degraded = False
            self.seq, self.tail = self._read_tail()

    # ---------- reads ----------
    def get(self, kind, id):
        row = self.db.execute(
            "SELECT data FROM entities WHERE kind=? AND id=?", (kind, id)
        ).fetchone()
        return json.loads(row["data"]) if row else None

    def find(self, _kind, project_id=None, **eq):
        q = "SELECT data FROM entities WHERE kind=?"
        args = [_kind]
        if project_id is not None:
            q += " AND project_id=?"
            args.append(project_id)
        out = []
        for row in self.db.execute(q, args):
            d = json.loads(row["data"])
            if all(d.get(k) == v for k, v in eq.items()):
                out.append(d)
        return out

    def board(self, wp_id=None):
        q = "SELECT * FROM board_events"
        args = []
        if wp_id:
            q += " WHERE wp_id=?"
            args.append(wp_id)
        return [dict(r) for r in self.db.execute(q + " ORDER BY seq", args)]

    def count_events(self, type=None):
        if type:
            return self.db.execute("SELECT count(*) c FROM events_index WHERE type=?", (type,)).fetchone()["c"]
        return self.db.execute("SELECT count(*) c FROM events_index").fetchone()["c"]

    def refusal_events(self):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM events_index WHERE type='refusal' ORDER BY seq")]

    def close(self):
        self.db.close()
