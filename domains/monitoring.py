"""MC — change control, decision log, baselines, reports, config surface.
Reports are deterministic DATA payloads; the plugin never sends them via any transport."""
import hashlib
import json

from . import nid, upsert, decision_event
from .. import defaults
from ..engine import canonical


def cr_create(store, gov, args, occupant):
    cid = nid(store, "change_request")
    ev = upsert(store, "change_request", cid, {
        "project_id": args["project_id"], "scope": args["scope"], "description": args["description"],
        "requested_by": occupant, "requested_by_role": ",".join(gov.roles_of(occupant)),
        "impact_assessment": None, "state": "proposed", "decided_by": None, "decision_ref": None,
    }, args["project_id"])
    return [ev], {"cr_id": cid, "state": "proposed"}


def cr_assess(store, gov, args, occupant):
    ev = upsert(store, "change_request", args["cr_id"],
                {"impact_assessment": args["impact_assessment"], "state": "assessed"})
    return [ev], {"cr_id": args["cr_id"], "state": "assessed"}


def cr_decide(store, gov, args, occupant):
    cr = store.get("change_request", args["cr_id"])
    if not cr.get("impact_assessment"):
        from ..governance import Refusal
        raise Refusal("FR-MC-02", "impact_assessment", "CR decision requires a completed impact assessment")
    baseline_affecting = cr["scope"] in ("charter", "scope", "schedule")
    if baseline_affecting and "F" not in gov.roles_of(occupant):
        from ..governance import Refusal
        raise Refusal("FR-MC-02", "cr_authority", "baseline-affecting change requires Founder (F) authorization")
    decision = args["decision"]
    dev, did = decision_event(store, cr["project_id"], "change",
                              f"CR {args['cr_id']} {decision}", cr["description"], occupant, [args["cr_id"]])
    evs = [
        upsert(store, "change_request", args["cr_id"],
               {"state": "approved" if decision == "approved" else "rejected",
                "decided_by": occupant, "decision_ref": did}),
        dev,
    ]
    return evs, {"cr_id": args["cr_id"], "decision": decision, "decision_id": did}


def rebaseline(store, gov, args, occupant):
    cr = store.get("change_request", args["cr_id"])
    if cr["state"] != "approved":
        from ..governance import Refusal
        raise Refusal("FR-MC-02", "cr_approved", "rebaseline requires an approved CR")
    from .requirements import scope_baseline
    evs, res = scope_baseline(store, gov, {"project_id": cr["project_id"], "cr_id": args["cr_id"]}, occupant)
    evs.append(upsert(store, "change_request", args["cr_id"], {"state": "rebaselined"}))
    return evs, {"cr_id": args["cr_id"], "scope_baseline_id": res["scope_baseline_id"], "seq": res["seq"]}


def decision_record(store, gov, args, occupant):
    ev, did = decision_event(store, args["project_id"], args["kind"], args["statement"],
                             args["rationale"], occupant, args.get("refs", []))
    if args.get("standards_basis"):
        ev[4]["data"]["standards_basis"] = args["standards_basis"]
    return [ev], {"decision_id": did}


def baseline_set(store, gov, args, occupant):
    bid = nid(store, "baseline")
    seq = len(store.find("baseline", project_id=args["project_id"], kind=args["kind"])) + 1
    evs = [upsert(store, "baseline", bid, {
        "project_id": args["project_id"], "kind": args["kind"], "snapshot_hash": args["snapshot_hash"],
        "value": args.get("value"), "metric_id": args.get("metric_id"),
        "set_by": occupant, "approved_by": args.get("approved_by"), "seq": seq, "set_ts": store.clock(),
    }, args["project_id"])]
    dev, did = decision_event(store, args["project_id"], "change",
                              f"Baseline {args['kind']} seq {seq} set", "FR-MC-01 measured baseline", occupant, [bid])
    evs.append(dev)
    return evs, {"baseline_id": bid, "seq": seq}


# ---------- config surface ----------
def _config_write(store, gov, key, value, occupant, project_id=None):
    ev = upsert(store, "config", key, {"value": value}, project_id)
    dev, did = decision_event(store, project_id, "config", f"Config '{key}' updated",
                              "NFR-06 governed configuration change", occupant)
    return [ev, dev], did


def role_bind(store, gov, args, occupant):
    role = args["role"]
    if role not in ("O", "E", "V", "F"):
        from ..governance import Refusal
        raise Refusal("NFR-02", "role_id", "role must be O|E|V|F")
    binding = {"occupants": args["occupants"], "seats": args.get("seats", 1)}
    gov.settings["roles"][role] = binding
    evs, did = _config_write(store, gov, f"roles:{role}", binding, occupant, args.get("project_id"))
    return evs, {"role": role, "binding": binding, "decision_id": did}


def tolerance_update(store, gov, args, occupant):
    gov.settings["tolerances"] = {**gov.settings["tolerances"], **args["tolerances"]}
    evs, did = _config_write(store, gov, "tolerances", args["tolerances"], occupant, args.get("project_id"))
    return evs, {"decision_id": did}


def criteria_set(store, gov, args, occupant):
    gov.settings["risk_criteria"] = {**gov.settings["risk_criteria"], **args["criteria"]}
    evs, did = _config_write(store, gov, "risk_criteria", args["criteria"], occupant, args.get("project_id"))
    return evs, {"decision_id": did}


def cadence_set(store, gov, args, occupant):
    gov.settings["cadence"] = {**gov.settings["cadence"], **args["cadence"]}
    evs, did = _config_write(store, gov, "cadence", args["cadence"], occupant, args.get("project_id"))
    return evs, {"decision_id": did}


def autonomy_set(store, gov, args, occupant):
    cls = args["class"]
    if cls not in gov.settings["autonomy"]["classes"]:
        from ..governance import Refusal
        raise Refusal("EXP-04", "autonomy_class", f"class must be one of {gov.settings['autonomy']['classes']}")
    gov.settings["autonomy"] = {**gov.settings["autonomy"], "class": cls}
    evs, did = _config_write(store, gov, "autonomy", {"class": cls}, occupant, args.get("project_id"))
    return evs, {"autonomy_class": cls, "decision_id": did}


def freshness_set(store, gov, args, occupant):
    gov.settings["evidence_max_age"] = {**gov.settings["evidence_max_age"], **args["max_age"]}
    evs, did = _config_write(store, gov, "evidence_max_age", args["max_age"], occupant, args.get("project_id"))
    return evs, {"decision_id": did}


def config_show(store, gov, args, occupant):
    return [], {"settings": gov.settings}


# ---------- reports (read-only; deterministic) ----------
def board(store, gov, args, occupant):
    wps = store.find("work_package", project_id=args.get("project_id"))
    seats = {}
    for w in wps:
        if w.get("state") in ("dispatched", "executing", "blocked"):
            seats.setdefault(w.get("seat_id"), []).append(w["id"])
    from datetime import datetime
    now = datetime.fromisoformat(store.clock())
    def age(ts):
        return (now - datetime.fromisoformat(ts)).total_seconds() if ts else None
    return [], {"board": [{"id": w["id"], "state": w["state"], "seat": w.get("seat_id"),
                           "started_ts": w.get("started_ts"), "block_ts": w.get("block_ts"),
                           "age_s": age(w.get("started_ts")), "blocked_age_s": age(w.get("block_ts")) if w.get("state") == "blocked" else None} for w in wps],
                "wip_per_seat": {s: len(v) for s, v in seats.items()}}


def metrics_compute(store, gov, args, occupant):
    from ..measurement import compute
    mid = args.get("metric_id", "MT-01")
    val = compute(store, mid, args.get("window"), gov.settings)
    sid = nid(store, "metric_snapshot")
    ev = upsert(store, "metric_snapshot", sid, {
        "metric_id": mid, "window": args.get("window"), "value": val["value"],
        "sample_size": val["sample_size"], "computed_ts": store.clock(),
    }, args.get("project_id"))
    return [ev], {"metric_id": mid, **val, "snapshot_id": sid}


def variance(store, gov, args, occupant):
    snaps = store.find("metric_snapshot", metric_id=args.get("metric_id", "MT-01"))
    if args.get("baseline_id"):
        bls = [store.get("baseline", args["baseline_id"])]
    else:
        bls = store.find("baseline", project_id=args.get("project_id"), kind="performance")
    out = []
    for s in snaps:
        b = next((b for b in bls if b and b.get("metric_id") == s["metric_id"]), None)
        out.append({"snapshot": s["id"], "value": s["value"], "baseline_id": b["id"] if b else None,
                    "baseline_seq": b.get("seq") if b else None, "baseline_value": b.get("value") if b else None,
                    "inputs": {"actual": s["value"], "baseline": b.get("value") if b else None},
                    "variance": (s["value"] - b["value"]) if b and isinstance(s["value"], (int, float)) and isinstance(b.get("value"), (int, float)) else None})
    return [], {"variances": out, "recomputable": True}


def _snapshot(store, project_id):
    kinds = ("work_package", "risk", "issue", "exception", "change_request", "decision", "milestone")
    snap = {}
    for k in kinds:
        for e in store.find(k, project_id=project_id):
            snap[f"{k}:{e['id']}"] = e
    return snap


def delta_report(store, gov, args, occupant):
    pid = args.get("project_id")
    snap = _snapshot(store, pid)
    prior = store.find("report", project_id=pid, kind="delta")
    base = prior[-1].get("snapshot", {}) if prior else {}
    added = sorted(set(snap) - set(base))
    removed = sorted(set(base) - set(snap))
    changed = sorted(k for k in set(snap) & set(base) if canonical(snap[k]) != canonical(base[k]))
    content = {"added": added, "removed": removed, "changed": changed, "clock": store.clock()}
    rid = nid(store, "report")
    chash = hashlib.sha256(canonical(content).encode()).hexdigest()
    ev = upsert(store, "report", rid, {
        "project_id": pid, "kind": "delta", "period": args.get("window"),
        "content_hash": chash, "delta_from": prior[-1]["id"] if prior else None,
        "generated_ts": store.clock(), "deterministic": True, "snapshot": snap, "content": content,
    }, pid)
    return [ev], {"report_id": rid, "content_hash": chash, **content}


def cadence_report(store, gov, args, occupant):
    from ..measurement import compute
    pid = args.get("project_id")
    metrics = {m: compute(store, m, args.get("window"), gov.settings) for m in
               ("MT-01", "MT-02", "MT-03", "MT-04", "MT-05", "MT-06", "MT-07", "MT-08", "MT-09", "MT-10", "MT-11", "MT-12", "MT-13")}
    from datetime import datetime
    now = datetime.fromisoformat(store.clock())
    overdue = [c["id"] for c in store.find("corrective_action", project_id=pid)
               if c.get("state") == "open" and c.get("due_ts") and datetime.fromisoformat(c["due_ts"]) < now]
    content = {"metrics": metrics, "risks": store.find("risk", project_id=pid),
               "issues": store.find("issue", project_id=pid),
               "overdue_corrective_actions": overdue, "clock": store.clock()}
    rid = nid(store, "report")
    chash = hashlib.sha256(canonical(content).encode()).hexdigest()
    ev = upsert(store, "report", rid, {
        "project_id": pid, "kind": "cadence", "period": args.get("window"),
        "content_hash": chash, "generated_ts": store.clock(), "deterministic": True, "content": content,
    }, pid)
    return [ev], {"report_id": rid, "content_hash": chash, "metrics": metrics}


def milestone_performance(store, gov, args, occupant):
    from datetime import datetime
    now = datetime.fromisoformat(store.clock())
    ms = store.find("milestone", project_id=args.get("project_id"))
    out = []
    for m in ms:
        delta = None
        if m.get("actual_ts") and m.get("planned_ts"):
            delta = (datetime.fromisoformat(m["actual_ts"]) - datetime.fromisoformat(m["planned_ts"])).total_seconds()
        derived = m["status"]
        if m["status"] == "planned" and m.get("planned_ts") and now > datetime.fromisoformat(m["planned_ts"]):
            derived = "missed"
        out.append({"id": m["id"], "name": m["name"], "status": m["status"],
                    "derived_status": derived, "variance_s": delta,
                    "baseline_ref": args.get("baseline_id")})
    return [], {"milestones": out}


ACTIONS = {
    "cr_create": cr_create, "cr_assess": cr_assess, "cr_decide": cr_decide, "rebaseline": rebaseline,
    "decision_record": decision_record, "baseline_set": baseline_set,
    "role_bind": role_bind, "tolerance_update": tolerance_update, "criteria_set": criteria_set,
    "cadence_set": cadence_set, "autonomy_set": autonomy_set, "freshness_set": freshness_set,
    "config_show": config_show, "board": board, "metrics_compute": metrics_compute,
    "variance": variance, "delta_report": delta_report, "cadence_report": cadence_report,
    "milestone_performance": milestone_performance,
}
