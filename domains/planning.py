"""SCH — work packages, sequencing, milestones, flow estimation, seats, WIP (WF-01.4, WF-02.1)."""
from . import nid, upsert, decision_event


def wp_create(store, gov, args, occupant):
    wid = nid(store, "work_package")
    dlv = store.get("deliverable", args["deliverable_id"]) or {}
    ev = upsert(store, "work_package", wid, {
        "project_id": args["project_id"], "deliverable_id": args["deliverable_id"],
        "title": args["title"], "scope": args.get("scope", ""),
        "dod_profile_id": args.get("dod_profile_id", dlv.get("dod_profile_id", "software")),
        "ac_ids": args.get("ac_ids", []), "estimate": args.get("estimate"),
        "seat_id": None, "executor_occupant": None, "dependency_ids": args.get("dependency_ids", []),
        "state": "draft", "started_ts": None, "finished_ts": None, "block_ts": None,
    }, args["project_id"])
    return [ev], {"wp_id": wid, "state": "draft"}


def sequence(store, gov, args, occupant):
    wid = args["wp_id"]
    deps = args["dependency_ids"]
    # cycle check
    graph = {w["id"]: set(w.get("dependency_ids", [])) for w in store.find("work_package")}
    graph[wid] = set(deps)
    seen, stack = set(), [(wid, [wid])]
    while stack:
        node, path = stack.pop()
        for d in graph.get(node, ()):
            if d == wid:
                from ..governance import Refusal
                raise Refusal("FR-SCH-01", "dag_cycle", f"dependency cycle: {' -> '.join(path + [d])}")
            if d not in seen:
                seen.add(d)
                stack.append((d, path + [d]))
    ev = upsert(store, "work_package", wid, {"dependency_ids": deps})
    return [ev], {"wp_id": wid, "dependency_ids": deps}


def milestone_plan(store, gov, args, occupant):
    mid = nid(store, "milestone")
    ev = upsert(store, "milestone", mid, {
        "project_id": args["project_id"], "name": args["name"], "planned_ts": args["planned_ts"],
        "completion_criteria": args.get("completion_criteria", "all linked work packages accepted"),
        "actual_ts": None, "wp_ids": args.get("wp_ids", []), "status": "planned",
    }, args["project_id"])
    return [ev], {"milestone_id": mid}


def estimate_flow(store, gov, args, occupant):
    """SLE-based flow estimate — no human-effort units."""
    ev = upsert(store, "work_package", args["wp_id"], {
        "estimate": {"sle_time": args["sle_time"], "percentile": args.get("percentile", gov.settings["estimation"]["sle_percentile"]),
                     "basis": args.get("basis", "flow_history")},
    })
    return [ev], {"wp_id": args["wp_id"], "estimate": "sle"}


def allocate_seat(store, gov, args, occupant):
    ev = upsert(store, "work_package", args["wp_id"], {"seat_id": args["seat_id"]})
    return [ev], {"wp_id": args["wp_id"], "seat_id": args["seat_id"]}


def wip_set(store, gov, args, occupant):
    ev = upsert(store, "config", "wip", {"limits": args["limits"]})
    gov.settings["wip"] = {**gov.settings["wip"], **args["limits"]}
    dev, did = decision_event(store, args.get("project_id"), "config", "WIP limits set",
                              "FR-SCH-05 capacity configuration", occupant)
    return [ev, dev], {"decision_id": did, "wip": gov.settings["wip"]}


def sequencing(store, gov, args, occupant):
    pid = args.get("project_id")
    wps = store.find("work_package", project_id=pid)
    byid = {w["id"]: w for w in wps}
    out = []
    for w in wps:
        deps = w.get("dependency_ids", [])
        complete = all(byid.get(d, {}).get("state") in ("accepted", "closed") for d in deps)
        out.append({"wp_id": w["id"], "dependencies": deps,
                    "ready": complete and w["state"] in ("draft", "ready"),
                    "flag": "ready" if complete else "not-ready: predecessors incomplete"})
    return [], {"sequencing": out}


def allocation(store, gov, args, occupant):
    wps = store.find("work_package", project_id=args.get("project_id"))
    per = {}
    for w in wps:
        if w.get("seat_id"):
            per.setdefault(w["seat_id"], []).append({"wp_id": w["id"], "state": w["state"]})
    return [], {"allocation": per, "roles": gov.settings["roles"]}


def sle_compute(store, gov, args, occupant):
    """SLE from recorded cycle times (time + probability); no history => best-guess flagged unmeasured."""
    from ..measurement import _finished, _cycle, _pct
    fin = _finished(store)
    p = gov.settings["estimation"]["sle_percentile"]
    min_sample = gov.settings["estimation"]["min_sample"]
    if len(fin) >= min_sample:
        cycles = sorted(_cycle(w) / 86400 for w in fin)
        return [], {"sle_time_days": _pct(cycles, p), "sle_probability": p / 100,
                    "measured": True, "sample_size": len(fin)}
    guess = args.get("best_guess_days", 2)
    return [], {"sle_time_days": guess, "sle_probability": p / 100,
                "measured": False, "flag": "unmeasured-best-guess", "sample_size": len(fin)}


def milestone_complete(store, gov, args, occupant):
    if not args.get("evidence_ids"):
        from ..governance import Refusal
        raise Refusal("FR-SCH-02", "milestone_evidence", "marking a milestone complete requires evidence references")
    m = store.get("milestone", args["milestone_id"])
    wps = [store.get("work_package", w) for w in m.get("wp_ids", [])]
    derivable = all(w and w.get("state") in ("accepted", "closed") for w in wps) if wps else True
    ev = upsert(store, "milestone", args["milestone_id"], {
        "actual_ts": store.clock(), "status": "met", "evidence_ids": args["evidence_ids"],
        "status_derivable_from_wps": derivable,
    })
    return [ev], {"milestone_id": args["milestone_id"], "status": "met", "derivable": derivable}


ACTIONS = {
    "wp_create": wp_create, "sequence": sequence, "milestone_plan": milestone_plan,
    "estimate_flow": estimate_flow, "allocate_seat": allocate_seat, "wip_set": wip_set,
    "sequencing": sequencing, "allocation": allocation, "sle_compute": sle_compute,
    "milestone_complete": milestone_complete,
}
