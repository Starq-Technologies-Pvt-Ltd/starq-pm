"""CL — final verification, formal acceptance, handover, lessons, archive (WF-09)."""
import hashlib

from . import nid, upsert, decision_event


def final_verify(store, gov, args, occupant):
    pid = args["project_id"]
    vid = nid(store, "verification")
    verdicts = args.get("verdicts", {})
    tids = args["test_ids"]
    per = {t: verdicts.get(t, "PASS") for t in tids}
    verdict = "PASS" if per and all(v == "PASS" for v in per.values()) else "FAIL"
    ev = upsert(store, "verification", vid, {
        "project_id": pid, "wp_id": None, "verifier_occupant": occupant,
        "kind": args.get("kind", "final"),
        "test_ids": tids, "verdict": verdict, "per_criterion": per, "cycle_n": 1,
        "evidence_ids": args.get("evidence_ids", []), "ts": store.clock(),
    }, pid)
    return [ev], {"verification_id": vid, "verdict": verdict, "kind": "final"}


def formal_accept(store, gov, args, occupant):
    pid = args["project_id"]
    cid = nid(store, "closure_record")
    fv = store.find("verification", project_id=pid, kind="final", verdict="PASS")
    from ..measurement import compute
    perf = {m: compute(store, m, None, gov.settings)["value"] for m in ("MT-01", "MT-02", "MT-06")}
    bls = store.find("baseline", project_id=pid)
    evs = [upsert(store, "closure_record", cid, {
        "project_id": pid, "final_verification_id": fv[-1]["id"] if fv else None,
        "formal_acceptance_id": cid, "archive_ref": None, "closed_ts": store.clock(),
        "accepting_role": "F", "accepting_occupant": occupant,
        "verifier_evidence_refs": [e["id"] for e in store.find("evidence", project_id=pid)],
        "performance_evaluation": {"metrics": perf, "baselines": [b["id"] for b in bls]},
    }, pid)]
    evs.append(upsert(store, "project", pid, {"status": "closed", "stage": "closure"}))
    dev, did = decision_event(store, pid, "acceptance", "Project formally accepted and closed",
                              "FR-CL-02 Founder formal acceptance", occupant, [cid])
    evs.append(dev)
    return evs, {"closure_id": cid, "status": "closed", "decision_id": did}


def handover_docs(store, gov, args, occupant):
    import hashlib
    from ..engine import canonical
    pid = args["project_id"]
    hid = nid(store, "handover_doc")
    package = {"doc_refs": [args["doc_ref"]],
               "evidence_index": [e["id"] for e in store.find("evidence", project_id=pid)],
               "operating_procedures": args.get("operating_procedures", [])}
    ph = hashlib.sha256(canonical(package).encode()).hexdigest()
    ev = upsert(store, "handover_doc", hid, {
        "project_id": pid, "doc_ref": args["doc_ref"], "sha256": args["sha256"],
        "recipient_role": args.get("recipient_role", "O"), "ts": store.clock(),
        "package": package, "package_hash": ph, "acknowledged_by": None,
    }, pid)
    return [ev], {"handover_doc_id": hid, "package_hash": ph, "package": package}


def handover_ack(store, gov, args, occupant):
    ev = upsert(store, "handover_doc", args["handover_doc_id"],
                {"acknowledged_by": occupant, "acknowledged_ts": store.clock()})
    return [ev], {"handover_doc_id": args["handover_doc_id"], "acknowledged_by": occupant}


def lessons_review(store, gov, args, occupant):
    pid = args["project_id"]
    lid = nid(store, "lessons")
    entries = store.find("lessons", project_id=pid)
    ev = upsert(store, "lessons_review", f"LR-{pid}", {
        "project_id": pid, "summary": args["summary"], "reviewed_by": occupant,
        "ts": store.clock(), "lessons_reviewed": [e["id"] for e in entries],
    }, pid)
    return [ev], {"lessons_review_id": f"LR-{pid}", "count": len(entries)}


def lessons(store, gov, args, occupant):
    lid = nid(store, "lessons")
    ev = upsert(store, "lessons", lid, {
        "project_id": args["project_id"], "category": args["category"],
        "observation": args["observation"], "recommendation": args["recommendation"],
        "tags": args.get("tags", []),
    }, args["project_id"])
    return [ev], {"lessons_id": lid}


def archive(store, gov, args, occupant):
    pid = args["project_id"]
    clo = store.find("closure_record", project_id=pid)
    manifest = {"closure": clo[-1]["id"] if clo else None,
                "evidence": [e["id"] for e in store.find("evidence", project_id=pid)],
                "handover": [h["id"] for h in store.find("handover_doc", project_id=pid)]}
    from ..engine import canonical
    ah = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    evs = [upsert(store, "closure_record", clo[-1]["id"] if clo else nid(store, "closure_record"),
                  {"archive_ref": f"archive:{pid}:{ah}", "archive_hash": ah}, pid)]
    return evs, {"project_id": pid, "archive_hash": ah, "manifest": manifest}


ACTIONS = {
    "final_verify": final_verify, "formal_accept": formal_accept, "handover_docs": handover_docs,
    "lessons": lessons, "archive": archive, "handover_ack": handover_ack, "lessons_review": lessons_review,
}
