"""RK — risk register, assessment, treatment, issues, escalation, exceptions, corrective actions
(WF-06). Ordinal scales only; agent-risk taxonomy."""
from datetime import datetime, timedelta

from . import nid, upsert, decision_event


def _band(score, gov):
    for lo, hi, label, authority in gov.settings["risk_criteria"]["bands"]:
        if lo <= score <= hi:
            return label, authority
    return "critical", "F"


def risk_identify(store, gov, args, occupant):
    tax = gov.settings["risk_criteria"]["taxonomy"]
    cat = args["category"]
    if cat not in tax and cat != "general":
        from ..governance import Refusal
        raise Refusal("FR-RK-01", "taxonomy", f"category '{cat}' not in risk taxonomy (or 'general')")
    rid = nid(store, "risk")
    ev = upsert(store, "risk", rid, {
        "project_id": args["project_id"], "category": cat, "description": args["description"],
        "likelihood": None, "impact": None, "score": None, "owner_role": args.get("owner_role", "O"),
        "state": "identified", "treatment_id": None,
    }, args["project_id"])
    return [ev], {"risk_id": rid, "state": "identified"}


def risk_assess(store, gov, args, occupant):
    lk, im = args["likelihood"], args["impact"]
    if not (isinstance(lk, int) and isinstance(im, int) and 1 <= lk <= 5 and 1 <= im <= 5):
        from ..governance import Refusal
        raise Refusal("FR-RK-02", "ordinal_scales", "likelihood/impact must be ordinal integers 1..5 (no false precision)")
    if args.get("measured_probability") is not None:
        from ..governance import Refusal
        raise Refusal("FR-RK-02", "estimate_label", "estimate-derived scores cannot claim measured probability (ordinal estimates only)")
    score = lk * im
    band, authority = _band(score, gov)
    import hashlib
    from ..engine import canonical
    cv = hashlib.sha256(canonical(gov.settings["risk_criteria"]).encode()).hexdigest()[:12]
    ev = upsert(store, "risk", args["risk_id"], {
        "likelihood": lk, "impact": im, "score": score, "band": band,
        "label": "estimate", "criteria_version": cv,
        "escalation_authority": authority, "state": "assessed",
    })
    return [ev], {"risk_id": args["risk_id"], "score": score, "band": band, "authority": authority,
                  "label": "estimate", "criteria_version": cv}


def treatment_plan(store, gov, args, occupant):
    kind = args["kind"]
    if kind not in ("mitigate", "contingency", "accept", "transfer"):
        from ..governance import Refusal
        raise Refusal("FR-RK-03", "treatment_kind", "kind must be mitigate|contingency|accept|transfer")
    if kind == "contingency" and not args.get("trigger"):
        from ..governance import Refusal
        raise Refusal("FR-RK-03", "contingency_trigger", "contingency treatment requires an explicit trigger")
    risk = store.get("risk", args["risk_id"])
    if kind == "accept":
        authority = (risk or {}).get("escalation_authority", "F")
        if authority not in gov.roles_of(occupant):
            from ..governance import Refusal
            raise Refusal("FR-RK-03", "accept_authority", f"risk acceptance requires authority role {authority}")
    tid = nid(store, "treatment")
    evs = [
        upsert(store, "treatment", tid, {
            "risk_id": args["risk_id"], "kind": kind, "actions": args["actions"],
            "trigger": args.get("trigger"), "owner": args.get("owner", occupant),
            "due": args.get("due"), "status": "planned",
        }),
        upsert(store, "risk", args["risk_id"], {"treatment_id": tid, "state": "treating"}),
    ]
    if kind == "accept":
        dev, _ = decision_event(store, (risk or {}).get("project_id"), "exception",
                                f"Risk {args['risk_id']} accepted", f"authority role {authority} approval", occupant, [tid])
        evs.append(dev)
    return evs, {"treatment_id": tid}


def issue_log(store, gov, args, occupant):
    iid = nid(store, "issue")
    ev = upsert(store, "issue", iid, {
        "project_id": args["project_id"], "risk_id": args.get("risk_id"),
        "description": args["description"], "severity": args["severity"],
        "wp_ids": args.get("wp_ids", []), "blocker_ids": args.get("blocker_ids", []),
        "state": "open", "corrective_id": None, "escalated": False,
    }, args["project_id"])
    evs = [ev]
    if args.get("risk_id"):
        evs.append(upsert(store, "risk", args["risk_id"], {"state": "occurred"}))
    return evs, {"issue_id": iid}


def escalate(store, gov, args, occupant):
    iid = args["issue_id"]
    issue = store.get("issue", iid)
    evs = [upsert(store, "issue", iid, {"state": "escalated", "escalated": True,
                                       "escalated_ts": store.clock()})]
    dev, did = decision_event(store, issue.get("project_id"), "exception",
                              f"Issue {iid} escalated", "FR-RK-05 escalation per criteria", occupant, [iid])
    evs.append(dev)
    return evs, {"issue_id": iid, "state": "escalated", "decision_id": did}


def exception_raise(store, gov, args, occupant):
    eid = nid(store, "exception")
    ev = upsert(store, "exception", eid, {
        "tolerance_class": args["tolerance_class"], "breach_ref": args["breach_ref"],
        "requested_by": occupant, "decided_by": None, "decision": None,
        "routing_authority": gov.settings["tolerances"].get(args["tolerance_class"], {}).get("routing", "F"),
        "expiry_ts": None, "state": "raised", "project_id": args.get("project_id"),
    }, args.get("project_id"))
    return [ev], {"exception_id": eid, "state": "raised",
                  "routing_authority": gov.settings["tolerances"].get(args["tolerance_class"], {}).get("routing", "F")}


def exception_decide(store, gov, args, occupant):
    eid = args["exception_id"]
    ex = store.get("exception", eid)
    cls = ex["tolerance_class"]
    routing = gov.settings["tolerances"].get(cls, {}).get("routing", "F")
    if routing not in gov.roles_of(occupant):
        from ..governance import Refusal
        raise Refusal("FR-IN-05", "exception_routing", f"exception class '{cls}' routes to {routing}; occupant lacks that role")
    decision = args["decision"]
    if decision == "approved" and not args.get("resolution"):
        from ..governance import Refusal
        raise Refusal("FR-IN-05", "exception_resolution", "exception approval requires a recorded resolution (corrective action or accepted deviation)")
    expiry = None
    if decision == "approved":
        secs = args.get("duration_s", 7 * 86400)
        expiry = (datetime.fromisoformat(store.clock()) + timedelta(seconds=secs)).isoformat(timespec="seconds")
    evs = [upsert(store, "exception", eid, {
        "decided_by": occupant, "decision": decision, "expiry_ts": expiry,
        "resolution": args.get("resolution"),
        "state": "applied" if decision == "approved" else "rejected",
    })]
    dev, did = decision_event(store, ex.get("project_id"), "exception",
                              f"Exception {eid} {decision}", f"FR-IN-05 routing={routing}", occupant, [eid])
    evs.append(dev)
    return evs, {"exception_id": eid, "decision": decision, "expiry_ts": expiry}


def corrective_action(store, gov, args, occupant):
    cid = nid(store, "corrective_action")
    pid = (store.get("issue", args["issue_id"]) or {}).get("project_id")
    evs = [
        upsert(store, "corrective_action", cid, {
            "issue_id": args["issue_id"], "action": args["action"], "owner": args["owner"],
            "trigger_ref": args.get("trigger_ref"),
            "due_ts": args.get("due_ts"), "verified_ts": None, "state": "open",
        }, pid),
        upsert(store, "issue", args["issue_id"], {"corrective_id": cid, "state": "corrective"}),
    ]
    return evs, {"corrective_id": cid}


def treatment_implement(store, gov, args, occupant):
    if not args.get("evidence_ids"):
        from ..governance import Refusal
        raise Refusal("FR-RK-03", "treatment_evidence", "implemented treatment requires evidence refs")
    ev = upsert(store, "treatment", args["treatment_id"],
                {"status": "implemented", "evidence_ids": args["evidence_ids"]})
    return [ev], {"treatment_id": args["treatment_id"], "status": "implemented"}


def treatment_verify(store, gov, args, occupant):
    ev = upsert(store, "treatment", args["treatment_id"],
                {"status": "verified", "verified_by": occupant, "verified_ts": store.clock()})
    return [ev], {"treatment_id": args["treatment_id"], "status": "verified"}


def issue_close(store, gov, args, occupant):
    if not args.get("evidence_ids"):
        from ..governance import Refusal
        raise Refusal("FR-RK-04", "issue_resolution_evidence", "issue closure requires resolution evidence")
    issue = store.get("issue", args["issue_id"])
    ca = store.get("corrective_action", issue.get("corrective_id")) if issue.get("corrective_id") else None
    if ca and ca.get("owner") == occupant:
        from ..governance import Refusal
        raise Refusal("I-02", "independent_closure", "issue closure requires an independent closer (not the corrective owner)")
    ev = upsert(store, "issue", args["issue_id"],
                {"state": "verified_closed", "closed_by": occupant, "closed_ts": store.clock(),
                 "evidence_ids": args["evidence_ids"]})
    return [ev], {"issue_id": args["issue_id"], "state": "verified_closed"}


def risk_review(store, gov, args, occupant):
    rid = nid(store, "decision")
    ev = upsert(store, "risk_review", f"RR-{args.get('gate_id') or args['project_id']}", {
        "project_id": args["project_id"], "gate_id": args.get("gate_id"),
        "summary": args["summary"], "reviewed_by": occupant, "ts": store.clock(),
        "risks_reviewed": [r["id"] for r in store.find("risk", project_id=args["project_id"])],
    }, args["project_id"])
    return [ev], {"risk_review_id": f"RR-{args.get('gate_id') or args['project_id']}"}


def escalation_ack(store, gov, args, occupant):
    issue = store.get("issue", args["issue_id"])
    if not issue.get("escalated"):
        from ..governance import Refusal
        raise Refusal("FR-RK-05", "escalation_state", "issue is not escalated")
    ev = upsert(store, "issue", args["issue_id"],
                {"acknowledged_by": occupant, "acknowledged_ts": store.clock(),
                 "ack_role": ",".join(gov.roles_of(occupant))})
    return [ev], {"issue_id": args["issue_id"], "acknowledged_by": occupant}


def corrective_verify(store, gov, args, occupant):
    if not args.get("evidence_ids"):
        from ..governance import Refusal
        raise Refusal("FR-MC-06", "effect_verification", "corrective closure requires effect-verification evidence")
    ca = store.get("corrective_action", args["corrective_id"])
    if ca.get("owner") == occupant:
        from ..governance import Refusal
        raise Refusal("I-02", "independent_verification", "corrective effect verification must be independent of the owner")
    evs = [upsert(store, "corrective_action", args["corrective_id"],
                  {"state": "verified", "verified_ts": store.clock(), "evidence_ids": args["evidence_ids"]})]
    return evs, {"corrective_id": args["corrective_id"], "state": "verified"}


ACTIONS = {
    "risk_identify": risk_identify, "risk_assess": risk_assess, "treatment_plan": treatment_plan,
    "issue_log": issue_log, "escalate": escalate, "exception_raise": exception_raise,
    "exception_decide": exception_decide, "corrective_action": corrective_action,
    "treatment_implement": treatment_implement, "treatment_verify": treatment_verify,
    "issue_close": issue_close, "risk_review": risk_review, "escalation_ack": escalation_ack,
    "corrective_verify": corrective_verify,
}
