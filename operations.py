"""starq-pm operation runner: governance pre-mutation -> domain handler -> chain-first append.
Also audit actions + optional interop seams."""
import json

from .engine import Store, ChainBreak, canonical
from .governance import Governance, Refusal
from .domains import REGISTRY


class PM:
    def __init__(self, data_dir, settings=None, clock=None, plugin_probe=None, redactor=None):
        self.store = Store(data_dir, clock)
        self.gov = Governance(self.store, settings)
        self.plugin_probe = plugin_probe or (lambda pid: False)
        self.redactor = redactor or (lambda text: text)
        self._load_config()

    def _load_config(self):
        """Rebuild settings from chain-persisted config entities."""
        for c in self.store.find("config"):
            cid = c["id"]
            if cid.startswith("roles:"):
                role = cid.split(":", 1)[1]
                val = c.get("value") if isinstance(c.get("value"), dict) else c
                self.gov.settings["roles"][role] = {"occupants": val.get("occupants", []), "seats": val.get("seats", 1)}
            elif cid == "wip":
                self.gov.settings["wip"] = {**self.gov.settings["wip"], **c.get("limits", {})}
            elif cid == "tolerances":
                self.gov.settings["tolerances"] = {**self.gov.settings["tolerances"], **c.get("value", c.get("tolerances", {}))}
            elif cid == "risk_criteria":
                self.gov.settings["risk_criteria"] = {**self.gov.settings["risk_criteria"], **c.get("value", {})}
            elif cid == "cadence":
                self.gov.settings["cadence"] = {**self.gov.settings["cadence"], **c.get("value", {})}
            elif cid == "autonomy":
                self.gov.settings["autonomy"] = {**self.gov.settings["autonomy"], **c.get("value", {})}
            elif cid == "evidence_max_age":
                self.gov.settings["evidence_max_age"] = {**self.gov.settings["evidence_max_age"], **c.get("value", {})}

    def operate(self, action, args, occupant):
        args = dict(args or {})
        with self.store._lock:  # guard + commit atomic (WIP/independence safe under concurrent calls)
            return self._operate_locked(action, args, occupant)

    def _operate_locked(self, action, args, occupant):
        if action not in REGISTRY and action not in AUDIT_ACTIONS:
            return {"error": "F-11", "refused_by": "schema", "reason": f"unknown action '{action}'"}
        try:
            self.gov.check(action, args, occupant)
        except Refusal as r:
            return self.gov.refuse(action, args, occupant, r)
        except ChainBreak as cb:
            return {"error": "F-05", "refused_by": "chain_integrity", "reason": str(cb)}
        if action == "export" and args.get("target") in ("pm-bridge", "ledger-archive"):
            return self.seam_export(args["target"], args, occupant)
        handler = REGISTRY.get(action) or AUDIT_ACTIONS.get(action)
        if handler is None:
            return {"error": "F-11", "refused_by": "schema", "reason": f"unknown action '{action}'"}
        try:
            evs, result = handler(self.store, self.gov, args, occupant)
        except Refusal as r:
            return self.gov.refuse(action, args, occupant, r)
        except Exception as exc:
            # trust boundary: malformed args must never crash the runner (robustness fuzz)
            return {"error": "F-11", "refused_by": "handler", "reason": f"{type(exc).__name__}: {exc}"}
        dow = self.gov.settings.get("dow", {})
        legal = {tuple(x) for x in dow.get("transitions", [])}
        for (t, _r, _o, ref, p) in evs:
            if t == "board_transition" and legal and (p["from_state"], p["to_state"]) not in legal:
                r = Refusal("FR-EX-04", "dow_policy", f"transition {p['from_state']}->{p['to_state']} not permitted by DoW configuration")
                return self.gov.refuse(action, args, occupant, r)
        role = ",".join(self.gov.roles_of(occupant)) or "?"
        stamped = [(t, role, occupant, ref, p) for (t, _r, _o, ref, p) in evs]
        try:
            self.store.append_many(stamped)
        except ChainBreak as cb:
            return {"error": "F-05", "refused_by": "chain_integrity", "reason": str(cb)}
        except OSError as exc:
            return {"error": "F-04", "refused_by": "store_write", "reason": str(exc)}
        if action == "export" and isinstance(result, dict) and result.get("export") is not None:
            text = canonical(result["export"])
            red = self.redactor(text)
            result["export"] = json.loads(red)
            result["redacted"] = red != text
        return {"ok": True, **result}

    # ---------- optional interop seams (export-only; governed drafts for inbox) ----------
    def seam_export(self, target, args, occupant):
        try:
            present = self.plugin_probe(target)
        except Exception:
            present = False  # interop failure degrades to unavailable
        if not present:
            return {"ok": True, "seam": target, "status": "no-op", "reason": "sibling absent/unavailable (NFR-07)"}
        if target == "pm-bridge":
            board = self.operate("board", args, occupant)
            return {"ok": True, "seam": target, "status": "exported", "payload": board.get("board", [])}
        if target == "ledger-archive":
            head = self.store.head()
            return {"ok": True, "seam": target, "status": "exported",
                    "payload": {"chain_head": head, "events": self.store.count_events()}}
        return {"ok": True, "seam": target, "status": "no-op", "reason": "unknown seam target"}


def chain_verify(store, gov, args, occupant):
    ok, broken = store.verify_chain()
    return [], {"ok": ok, "broken_seq": broken, "head": store.head(), "events": store.count_events()}


def evidence_lookup(store, gov, args, occupant):
    import os
    from .domains import sha256_file
    def check(ev):
        if ev is None:
            return None
        out = dict(ev)
        if os.path.isfile(ev.get("path", "")):
            actual = sha256_file(ev["path"])
            out["hash_verified"] = actual == ev.get("sha256")
            if not out["hash_verified"]:
                out["integrity"] = "tamper/stale: stored hash does not match content"
        else:
            out["hash_verified"] = None
            out["integrity"] = "unavailable: content not present for re-verification"
        return out
    if args.get("evidence_id"):
        return [], {"evidence": check(store.get("evidence", args["evidence_id"]))}
    return [], {"evidence": [check(e) for e in store.find("evidence", wp_id=args.get("wp_id"))]}


def export(store, gov, args, occupant):
    """Redacted export."""
    target = args.get("target")
    kinds = args.get("kinds", ["work_package", "decision", "acceptance", "risk", "issue"])
    out = []
    for k in kinds:
        for e in store.find(k, project_id=args.get("project_id")):
            out.append({"kind": k, **e})
    text = canonical(out)
    return [], {"export": json.loads(text), "redacted": False, "count": len(out)}


def anchor(store, gov, args, occupant):
    """export audit anchor digest for Founder custody OUTSIDE agent-writable trees."""
    head = store.head()
    payload = {"seq": head["seq"], "hash": head["hash"], "exported_ts": store.clock()}
    p = store.dir / "exports" / f"anchor-{head['seq']}.json"
    p.write_text(canonical(payload), encoding="utf-8")
    return [], {"anchor": payload, "path": str(p),
                "custody_note": "Founder designates custody location outside agent-writable trees (WP-07)"}


AUDIT_ACTIONS = {
    "chain_verify": chain_verify, "evidence_lookup": evidence_lookup,
    "export": export, "anchor": anchor,
}
