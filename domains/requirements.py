"""SR — requirements register, WBS, traceability, scope baseline (WF-01.3, WF-05)."""
from . import nid, upsert, decision_event

MOSCOW = {"Must", "Should", "Could", "Wont"}
CLASS_TAGS = {"ESTABLISHED", "STARQ-ADAPT", "EXPERIMENTAL"}


def requirement_upsert(store, gov, args, occupant):
    rid = args["id"]
    if store.get("requirement", rid) and not args.get("update"):
        from ..governance import Refusal
        raise Refusal("FR-SR-01", "duplicate_id", f"requirement ID '{rid}' already exists in project; duplicate rejected")
    if args["priority"] not in MOSCOW:
        from ..governance import Refusal
        raise Refusal("FR-SR-05", "moscow", f"priority must be MoSCoW {sorted(MOSCOW)}")
    tag = args.get("class_tag", "ESTABLISHED")
    if tag not in CLASS_TAGS:
        from ..governance import Refusal
        raise Refusal("NFR-10", "class_tag", f"class_tag must be one of {sorted(CLASS_TAGS)}")
    ev = upsert(store, "requirement", rid, {
        "project_id": args["project_id"], "domain": args.get("domain", rid.split("-")[1] if "-" in rid else ""),
        "statement": args["statement"], "priority": args["priority"],
        "mvp": args["priority"] == "Must", "class_tag": tag,
        "source_ref": args.get("source_ref", ""), "status": args.get("status", "active"),
    }, args["project_id"])
    return [ev], {"requirement_id": rid}


def deliverable_decompose(store, gov, args, occupant):
    did = nid(store, "deliverable")
    ev = upsert(store, "deliverable", did, {
        "project_id": args["project_id"], "parent_id": args.get("parent_id"),
        "name": args["name"], "type": args["type"],
        "dod_profile_id": args.get("dod_profile_id", args["type"]),
        "requirement_ids": args.get("requirement_ids", []),
    }, args["project_id"])
    return [ev], {"deliverable_id": did}


def trace_link(store, gov, args, occupant):
    if args["kind"] not in ("satisfies", "verifies", "derives"):
        from ..governance import Refusal
        raise Refusal("FR-SR-03", "trace_kind", "kind must be satisfies|verifies|derives")
    lid = nid(store, "trace_link")
    ev = upsert(store, "trace_link", lid, {
        "from_ref": args["from_ref"], "to_ref": args["to_ref"], "kind": args["kind"],
        "created_by": occupant,
    }, args.get("project_id"))
    return [ev], {"trace_link_id": lid}


def scope_baseline(store, gov, args, occupant):
    pid = args["project_id"]
    reqs = store.find("requirement", project_id=pid)
    import hashlib, json
    snap = hashlib.sha256(json.dumps(sorted(r["id"] for r in reqs)).encode()).hexdigest()
    sbid = nid(store, "scope_baseline")
    seq = len(store.find("scope_baseline", project_id=pid)) + 1
    evs = [upsert(store, "scope_baseline", sbid, {
        "project_id": pid, "seq": seq, "requirement_snapshot_hash": snap,
        "approved_by": occupant, "cr_id": args.get("cr_id"),
    }, pid)]
    dev, did = decision_event(store, pid, "change", f"Scope baseline seq {seq} approved",
                              "FR-SR-04 immutable snapshot", occupant, [sbid])
    evs.append(dev)
    return evs, {"scope_baseline_id": sbid, "seq": seq, "snapshot_hash": snap}


def prioritize(store, gov, args, occupant):
    if args["priority"] not in MOSCOW:
        from ..governance import Refusal
        raise Refusal("FR-SR-05", "moscow", f"priority must be MoSCoW {sorted(MOSCOW)}")
    ev = upsert(store, "requirement", args["requirement_id"],
                {"priority": args["priority"], "mvp": args["priority"] == "Must"})
    return [ev], {"requirement_id": args["requirement_id"], "priority": args["priority"]}


def wbs(store, gov, args, occupant):
    pid = args.get("project_id")
    dlvs = store.find("deliverable", project_id=pid)
    wps = store.find("work_package", project_id=pid)
    linked = {w["deliverable_id"] for w in wps}
    tree = [{"deliverable": d["id"], "name": d["name"], "parent_id": d.get("parent_id"),
             "work_packages": [w["id"] for w in wps if w.get("deliverable_id") == d["id"]]} for d in dlvs]
    orphans = [w["id"] for w in wps if w.get("deliverable_id") not in {d["id"] for d in dlvs}]
    return [], {"wbs": tree, "orphan_work_packages": orphans}


def coverage(store, gov, args, occupant):
    pid = args.get("project_id")
    reqs = store.find("requirement", project_id=pid)
    dlvs = store.find("deliverable", project_id=pid)
    wps = store.find("work_package", project_id=pid)
    links = store.find("trace_link", project_id=pid)
    out, unlinked = [], []
    for r in reqs:
        rw = [w["id"] for w in wps for d in dlvs
              if w.get("deliverable_id") == d["id"] and r["id"] in d.get("requirement_ids", [])]
        tl = [l for l in links if l["from_ref"] == r["id"] or l["to_ref"] == r["id"]]
        tests, evidence = [], []
        for w in rw:
            tests += [a["test_id"] for a in store.find("acceptance_criterion", wp_id=w)]
            evidence += [e["id"] for e in store.find("evidence", wp_id=w)]
        entry = {"requirement": r["id"], "work_packages": rw,
                 "trace_links": [l["id"] for l in tl], "tests": tests, "evidence": evidence}
        out.append(entry)
        if not rw and not tl:
            unlinked.append(r["id"])
    return [], {"coverage": out, "requirements_without_wp_link": unlinked}


def mvp(store, gov, args, occupant):
    reqs = store.find("requirement", project_id=args.get("project_id"), priority="Must")
    return [], {"mvp": sorted(r["id"] for r in reqs)}


ACTIONS = {
    "requirement_upsert": requirement_upsert, "deliverable_decompose": deliverable_decompose,
    "trace_link": trace_link, "scope_baseline": scope_baseline, "prioritize": prioritize,
    "wbs": wbs, "coverage": coverage, "mvp": mvp,
}
