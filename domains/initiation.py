"""IN — initiation, charter, justification, stage gates (WF-01, WF-04). ProjectStage machine."""
from . import nid, upsert, decision_event


def charter_create(store, gov, args, occupant):
    pid = args["project_id"]
    cid = nid(store, "charter")
    evs = [
        upsert(store, "project", pid, {"name": args.get("name", pid), "stage": "initiation",
                                       "charter_id": cid, "status": "active", "created_ts": store.clock()}, pid),
        upsert(store, "charter", cid, {
            "project_id": pid, "authorization_ref": args["authorization_ref"],
            "objectives": args["objectives"], "success_criteria": args["success_criteria"],
            "stakeholders": args.get("stakeholders", []), "role_assignments": args.get("role_assignments", {}),
            "baselined": False, "baseline_seq": 0,
        }, pid),
    ]
    return evs, {"charter_id": cid, "project_id": pid}


def charter_update(store, gov, args, occupant):
    cid = args.get("charter_id") or args.get("id")
    data = {k: v for k, v in args.items() if k not in ("charter_id", "id", "cr_id", "project_id")}
    return [upsert(store, "charter", cid, data)], {"charter_id": cid}


def justification_record(store, gov, args, occupant):
    jid = nid(store, "justification")
    ev = upsert(store, "justification", jid, {
        "project_id": args["project_id"], "gate_id": args.get("gate_id"),
        "statement": args["statement"], "review_decision": args["review_decision"],
        "decided_by": occupant, "ts": store.clock(),
    }, args["project_id"])
    evs = [ev]
    if args["review_decision"] == "stop":
        evs.append(upsert(store, "project", args["project_id"],
                          {"status": "stopped", "stop_reason": "justification review: stop"}))
    return evs, {"justification_id": jid}


def charter_authorize(store, gov, args, occupant):
    cid = args["charter_id"]
    ch = store.get("charter", cid)
    if not store.find("justification", project_id=ch["project_id"]):
        from ..governance import Refusal
        raise Refusal("FR-IN-02", "justification_required", "gate authorization requires a justification review record (FR-IN-02)")
    evs = [upsert(store, "charter", cid, {"baselined": True, "baseline_seq": (ch.get("baseline_seq", 0) + 1)})]
    dev, did = decision_event(store, ch["project_id"], "gate", f"Charter {cid} authorized (G0)",
                              "Founder authorization recorded", occupant, [cid])
    evs.append(dev)
    return evs, {"charter_id": cid, "decision_id": did, "gate": "G0"}


def tolerance_set(store, gov, args, occupant):
    ev = upsert(store, "config", f"tolerances:{args['project_id']}",
                {"tolerances": args["tolerances"]}, args["project_id"])
    gov.settings["tolerances"] = {**gov.settings["tolerances"], **args["tolerances"]}
    dev, did = decision_event(store, args["project_id"], "config", "Tolerances set",
                              "FR-IN-05 tolerance configuration", occupant)
    return [ev, dev], {"decision_id": did}


def gate_evaluate(store, gov, args, occupant):
    gid = args["gate_id"]
    g = store.get("gate", gid) or {"id": gid, "project_id": args.get("project_id"),
                                   "stage_from": args.get("stage_from"), "stage_to": args.get("stage_to")}
    ev = upsert(store, "gate", gid, {**g, "evaluation": args.get("evaluation", "evaluated"),
                                     "evaluated_by": occupant, "evaluated_ts": store.clock()},
                g.get("project_id"))
    return [ev], {"gate_id": gid, "state": "evaluated"}


def gate_decide(store, gov, args, occupant):
    """O decides; stage transition ONLY on founder_authorize (I-04). Gate bypass refused by design."""
    gid = args["gate_id"]
    g = store.get("gate", gid) or {}
    evs = [upsert(store, "gate", gid, {**g, "decision": args["decision"], "decided_by": occupant,
                                       "decided_ts": store.clock(), "founder_authorized": False},
                  g.get("project_id"))]
    dev, did = decision_event(store, g.get("project_id"), "gate",
                              f"Gate {gid} decision: {args['decision']}", "O evaluation; F authorization required for transition", occupant, [gid])
    evs.append(dev)
    return evs, {"gate_id": gid, "decision": args["decision"], "transition": "pending_founder_authorization"}


def founder_authorize(store, gov, args, occupant):
    gid = args["gate_id"]
    g = store.get("gate", gid)
    if not g or g.get("decision") not in ("continue", "approve", "approved"):
        from ..governance import Refusal
        raise Refusal("I-04", "gate_sequence", "Founder authorization requires a prior gate decision (continue/approve)")
    pid = g.get("project_id")
    proj = store.get("project", pid)
    stage_to = g.get("stage_to") or args.get("stage_to")
    evs = [upsert(store, "gate", gid, {"founder_authorized": True, "authorized_by": occupant,
                                       "authorized_ts": store.clock()})]
    if stage_to and proj:
        if stage_to not in gov.settings["stages"]:
            from ..governance import Refusal
            raise Refusal("FR-IN-04", "stage_vocabulary", f"stage '{stage_to}' not in configured stages {gov.settings['stages']}")
        just = store.find("justification", project_id=pid, gate_id=gid)
        if not just:
            from ..governance import Refusal
            raise Refusal("FR-IN-02", "justification_required", "stage gate requires a justification review record (FR-IN-02)")
        if not store.get("risk_review", f"RR-{gid}"):
            from ..governance import Refusal
            raise Refusal("FR-RK-05", "risk_review_required", "gate authorization requires a recorded risk review (FR-RK-05)")
        evs.append(upsert(store, "project", pid, {"stage": stage_to}))
    dev, did = decision_event(store, pid, "gate", f"Gate {gid} Founder-authorized",
                              "I-04 Founder gate authority", occupant, [gid])
    evs.append(dev)
    return evs, {"gate_id": gid, "authorized": True, "stage": stage_to}


def stop_veto(store, gov, args, occupant):
    pid = args["project_id"]
    evs = [upsert(store, "project", pid, {"status": "stopped", "stop_reason": args["reason"],
                                          "stopped_by": occupant, "stopped_ts": store.clock()})]
    dev, did = decision_event(store, pid, "gate", "Founder STOP/VETO", args["reason"], occupant)
    evs.append(dev)
    return evs, {"project_id": pid, "status": "stopped"}


ACTIONS = {
    "charter_create": charter_create, "charter_update": charter_update,
    "justification_record": justification_record, "charter_authorize": charter_authorize,
    "tolerance_set": tolerance_set, "gate_evaluate": gate_evaluate, "gate_decide": gate_decide,
    "founder_authorize": founder_authorize, "stop_veto": stop_veto,
}
