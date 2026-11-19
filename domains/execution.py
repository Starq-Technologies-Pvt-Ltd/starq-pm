"""EX — dispatch, handoff, status, blockers, substitution (WF-02, WF-07, GW-01).
Transport separation: dispatch records data; the plugin never sends pane/chat messages."""
from . import nid, upsert, transition, decision_event

# RACI step classes (dispatch step WF-02.2: R=O, A=O, C=E, I=V,F)
DISPATCH_RACI = {"R": "O", "A": "O", "C": ["E"], "I": ["V", "F"]}


def dispatch(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    if wp["state"] not in ("draft", "ready"):
        from ..governance import Refusal
        raise Refusal("FR-EX-02", "wp_state", f"cannot dispatch WP in state '{wp['state']}'")
    if not wp.get("ac_ids") or not wp.get("dod_profile_id"):
        from ..governance import Refusal
        raise Refusal("FR-EX-01", "wp_contract", "work package requires acceptance criteria and a DoD (evidence requirements) profile before dispatch")
    proj = store.get("project", wp.get("project_id"))
    if proj and proj.get("status") in ("stopped", "closed"):
        from ..governance import Refusal
        raise Refusal("FR-IN-02", "project_stopped", "project stopped/closed; dispatch prevented")
    ch = store.find("charter", project_id=wp.get("project_id"))
    if not ch or not ch[0].get("baselined"):
        from ..governance import Refusal
        raise Refusal("FR-IN-01", "charter_baselined", "dispatch requires a baselined (authorized) charter")
    seat = args["to_occupant"]
    if "E" not in gov.roles_of(seat):
        from ..governance import Refusal
        raise Refusal("FR-EX-02", "executor_seat", f"dispatch target '{seat}' is not an executor seat")
    did = nid(store, "dispatch")
    evs = [
        upsert(store, "dispatch", did, {
            "wp_id": wid, "from_role": "O", "to_occupant": seat, "to_role": "E",
            "raci": DISPATCH_RACI, "mode": args.get("mode", "assign"),
            "dispatched_ts": store.clock(), "transport_meta": args.get("transport_meta", {}),
        }, wp.get("project_id")),
        upsert(store, "work_package", wid, {"seat_id": seat, "executor_occupant": seat, "state": "ready"}),
    ]
    if wp["state"] == "draft":
        evs.append(transition(wid, "draft", "ready", "wp readied"))
    evs.append(transition(wid, "ready", "dispatched", "dispatch"))
    return evs, {"dispatch_id": did, "wp_id": wid, "state": "dispatched", "raci": DISPATCH_RACI}


def handoff(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    if wp.get("executor_occupant") != occupant:
        from ..governance import Refusal
        raise Refusal("FR-EX-05", "handoff_owner", "only the assigned executor may hand off")
    if not args.get("artifacts"):
        from ..governance import Refusal
        raise Refusal("FR-EX-05", "handoff_artifacts", "handoff requires artifact references with hashes")
    hid = nid(store, "handoff")
    evs = [
        upsert(store, "handoff", hid, {
            "wp_id": wid, "from_occupant": occupant, "from_role": "E", "to_role": args.get("to_role", "V"),
            "artifacts": args["artifacts"], "evidence_ids": args.get("evidence_ids", []),
            "notes": args.get("notes", ""), "ts": store.clock(),
        }, wp.get("project_id")),
        transition(wid, wp["state"], "handed_off", "handoff"),
    ]
    return evs, {"handoff_id": hid, "state": "handed_off"}


def status_record(store, gov, args, occupant):
    """Async status record — provenance only, no authority, no board transition."""
    wp = store.get("work_package", args["wp_id"])
    sid = nid(store, "handoff")
    evs = [upsert(store, "handoff", sid, {
        "wp_id": args["wp_id"], "from_occupant": occupant, "from_role": ",".join(gov.roles_of(occupant)),
        "to_role": "O", "artifacts": [], "evidence_ids": args.get("evidence_ids", []),
        "notes": args["note"], "ts": store.clock(), "kind": "status_record",
    }, wp.get("project_id"))]
    # executor acknowledgement: dispatched->executing (start) or rework->executing
    if wp.get("executor_occupant") == occupant and wp["state"] in ("dispatched", "rework"):
        evs.append(transition(args["wp_id"], wp["state"], "executing", "executor acknowledgement"))
    return evs, {"status_id": sid, "state": "executing" if len(evs) > 1 else wp["state"]}


def blocker_raise(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    bid = nid(store, "blocker")
    evs = [
        upsert(store, "blocker", bid, {
            "wp_id": wid, "reason": args["reason"], "blocking_seat": args.get("blocking_seat", ""),
            "owner_role": args.get("owner_role", "O"),
            "raised_ts": store.clock(), "cleared_ts": None, "escalation_id": None,
        }, wp.get("project_id")),
        transition(wid, wp["state"], "blocked", args["reason"]),
    ]
    return evs, {"blocker_id": bid, "state": "blocked"}


def blocker_clear(store, gov, args, occupant):
    b = store.get("blocker", args["blocker_id"])
    wp = store.get("work_package", b["wp_id"])
    evs = [
        upsert(store, "blocker", args["blocker_id"], {"cleared_ts": store.clock()}),
        transition(b["wp_id"], "blocked", "executing", "blocker cleared"),
    ]
    return evs, {"blocker_id": args["blocker_id"], "state": "executing"}


def substitution_request(store, gov, args, occupant):
    """GW-01: F-authorized role substitution; independence never waived (guard upstream)."""
    role, frm, to = args["role"], args["from_occupant"], args["to_occupant"]
    binding = gov.settings["roles"].get(role, {"occupants": [], "seats": 1})
    occupants = [to if o == frm else o for o in binding.get("occupants", [])]
    if to not in occupants:
        occupants.append(to)
    sid = nid(store, "substitution")
    evs = [
        upsert(store, "substitution", sid, {
            "role": role, "from_occupant": frm, "to_occupant": to, "authorized_by": occupant,
            "reason": args.get("reason", ""), "independence_check": True, "ts": store.clock(),
        }),
        upsert(store, "config", f"roles:{role}", {"occupants": occupants, "seats": binding.get("seats", 1)}),
    ]
    gov.settings["roles"][role] = {**binding, "occupants": occupants}
    dev, did = decision_event(store, args.get("project_id"), "substitution",
                              f"Role {role}: {frm} -> {to}", "GW-01 substitution, F authorized", occupant, [sid])
    evs.append(dev)
    return evs, {"substitution_id": sid, "role": role, "occupants": occupants}


def blocker_review(store, gov, args, occupant):
    """: aged open blockers create exception records + auto status."""
    from datetime import datetime
    now = datetime.fromisoformat(store.clock())
    threshold = gov.settings.get("blocker_age_threshold_s", 86400)
    evs, created = [], []
    for b in store.find("blocker", project_id=args.get("project_id")):
        if b.get("cleared_ts"):
            continue
        age = (now - datetime.fromisoformat(b["raised_ts"])).total_seconds()
        if age > threshold and not b.get("escalation_id"):
            from .risk import exception_raise
            xevs, xres = exception_raise(store, gov, {
                "project_id": args.get("project_id"), "tolerance_class": "schedule",
                "breach_ref": f"blocker:{b['id']}:age={int(age)}s",
            }, occupant)
            evs += xevs
            evs.append(upsert(store, "blocker", b["id"], {"escalation_id": xres["exception_id"]}))
            sid = nid(store, "handoff")
            evs.append(upsert(store, "handoff", sid, {
                "wp_id": b["wp_id"], "from_occupant": occupant, "from_role": "O", "to_role": "F",
                "artifacts": [], "evidence_ids": [], "notes": f"auto status: blocker {b['id']} aged {int(age)}s -> exception {xres['exception_id']}",
                "ts": store.clock(), "kind": "exception_status",
            }, args.get("project_id")))
            created.append(xres["exception_id"])
    return evs, {"exceptions_created": created}


ACTIONS = {
    "dispatch": dispatch, "handoff": handoff, "status_record": status_record,
    "blocker_raise": blocker_raise, "blocker_clear": blocker_clear,
    "substitution_request": substitution_request, "blocker_review": blocker_review,
}
