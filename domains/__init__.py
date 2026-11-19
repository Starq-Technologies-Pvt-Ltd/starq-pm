"""starq-pm domain services: pure event-emitting handlers over projections.
Cross-domain effects happen only via events. No service imports another's internals.
Handler signature: fn(store, gov, args, occupant) -> (events, result).
events: list of (type, actor_role, actor_occupant, entity_ref, payload)."""
import hashlib
import json

PREFIX = {
    "project": "PRJ", "charter": "CH", "justification": "JUS", "requirement": "REQ",
    "deliverable": "DLV", "trace_link": "TL", "scope_baseline": "SB", "work_package": "WP",
    "milestone": "MS", "dispatch": "DSP", "handoff": "HO", "blocker": "BLK",
    "substitution": "SUB", "quality_profile": "QP", "acceptance_criterion": "AC",
    "verification": "VER", "evidence": "EV", "defect": "DEF", "rework_cycle": "RW",
    "acceptance": "ACC", "risk": "R", "treatment": "TRT", "issue": "I", "exception": "EXC",
    "corrective_action": "CA", "change_request": "CR", "decision": "D", "baseline": "BL",
    "metric_snapshot": "MET", "report": "RPT", "closure_record": "CLO", "lessons": "LES",
    "handover_doc": "HD", "gate": "GATE", "config": "CFG",
}


def nid(store, kind):
    # ponytail: count-based sequential ids (single-process plugin); uuid4 if multi-writer ever matters
    n = len(store.find(kind)) + 1
    return f"{PREFIX.get(kind, kind.upper())}-{n:03d}"


def upsert(store, kind, id, data, project_id=None):
    old = store.get(kind, id) or {}
    merged = {**old, **data, "id": id}
    if project_id is not None:
        merged["project_id"] = project_id
    return ("entity_upsert", None, None, id, {"kind": kind, "id": id, "project_id": merged.get("project_id"), "data": merged})


def transition(wp_id, frm, to, reason=""):
    return ("board_transition", None, None, wp_id, {"wp_id": wp_id, "from_state": frm, "to_state": to, "reason": reason})


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def decision_event(store, project_id, kind, statement, rationale, occupant, refs=None):
    did = nid(store, "decision")
    ev = upsert(store, "decision", did, {
        "project_id": project_id, "kind": kind, "statement": statement, "rationale": rationale,
        "decided_by_occupant": occupant, "ts": store.clock(), "refs": refs or [],
    }, project_id)
    return ev, did


from . import initiation, requirements, planning, execution, quality, risk, monitoring, closure  # noqa: E402

REGISTRY = {}
for mod in (initiation, requirements, planning, execution, quality, risk, monitoring, closure):
    REGISTRY.update(mod.ACTIONS)
