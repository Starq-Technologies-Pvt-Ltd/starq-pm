"""QA — quality profiles, AC binding, DoD, independent verification, evidence, acceptance,
defects, bounded rework (WF-03). ISO/IEC 25010:2023 vocabulary; no self-acceptance (I-01/I-02).
"""
import json
import os
from datetime import datetime, timedelta

from . import nid, upsert, transition, decision_event
from .. import defaults

# test register binding: bundled frozen reference copy (233 IDs).
_REG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "test_register.json")
try:
    with open(_REG_PATH, encoding="utf-8") as _f:
        TEST_REGISTER = set(json.load(_f))
except (OSError, ValueError):
    TEST_REGISTER = set()


def quality_profile(store, gov, args, occupant):
    chars = args["characteristics"]
    names = list(chars.keys()) if isinstance(chars, dict) else list(chars)
    for n in names:
        if str(n).lower() not in defaults.QUALITY_CHARACTERISTICS_25010_2023:
            from ..governance import Refusal
            raise Refusal("FR-QA-01", "quality_vocabulary", f"'{n}' not in ISO/IEC 25010:2023 characteristic vocabulary")
    vals = chars if isinstance(chars, dict) else {c: "" for c in chars}
    for c, v in vals.items():
        if not v:
            from ..governance import Refusal
            raise Refusal("FR-QA-01", "characteristic_measure", f"targeted characteristic '{c}' requires a measure or acceptance rationale")
    exclusions = args.get("exclusions", {})
    for c, r in exclusions.items():
        if not r:
            from ..governance import Refusal
            raise Refusal("FR-QA-01", "exclusion_rationale", f"excluded characteristic '{c}' requires a recorded rationale")
    qid = nid(store, "quality_profile")
    ev = upsert(store, "quality_profile", qid, {
        "deliverable_type": args["deliverable_type"], "characteristics": chars,
        "exclusions": exclusions, "class_tag": args.get("class_tag", "STARQ-ADAPT"),
    }, args.get("project_id"))
    return [ev], {"quality_profile_id": qid}


def ac_set(store, gov, args, occupant):
    tid = args["test_id"]
    if TEST_REGISTER and tid not in TEST_REGISTER:
        from ..governance import Refusal
        raise Refusal("FR-QA-02", "test_binding", f"test_id '{tid}' not in D2 test register (233 IDs); binding rejected")
    if not args.get("requirement_ids"):
        from ..governance import Refusal
        raise Refusal("FR-QA-02", "ac_requirement_link", "criterion must link to >=1 requirement ID")
    if not args.get("dod_item"):
        from ..governance import Refusal
        raise Refusal("FR-QA-02", "ac_dod_link", "criterion must link to >=1 DoD checklist item")
    if not args.get("predicate"):
        from ..governance import Refusal
        raise Refusal("FR-QA-02", "ac_predicate", "criterion requires a non-empty checkable predicate (given/when/then)")
    aid = nid(store, "acceptance_criterion")
    wp = store.get("work_package", args["wp_id"])
    evs = [
        upsert(store, "acceptance_criterion", aid, {
            "wp_id": args["wp_id"], "text": args["text"], "test_id": tid,
            "requirement_ids": args["requirement_ids"], "dod_item": args["dod_item"],
            "predicate": args["predicate"],
            "dod_profile_id": args.get("dod_profile_id", "software"),
        }, wp.get("project_id")),
        upsert(store, "work_package", args["wp_id"], {"ac_ids": wp.get("ac_ids", []) + [aid]}),
    ]
    return evs, {"ac_id": aid, "test_id": tid}


def evidence_attach(store, gov, args, occupant):
    path = args["path"]
    declared = args["sha256"]
    if os.path.isfile(path):
        from . import sha256_file
        actual = sha256_file(path)
        if declared != actual:
            from ..governance import Refusal
            raise Refusal("F-06", "evidence_integrity", f"sha256 mismatch for {path}; fail-closed")
    eid = nid(store, "evidence")
    ev = upsert(store, "evidence", eid, {
        "wp_id": args["wp_id"], "path": path, "sha256": declared,
        "captured_ts": args["captured_ts"], "class": args["class"],
        "producer_role": ",".join(gov.roles_of(occupant)),
        "available": os.path.isfile(path),
        "max_age_s": gov.settings["evidence_max_age"].get(args["class"], 86400),
        "redacted": False,
    }, args.get("project_id") or (store.get("work_package", args["wp_id"]) or {}).get("project_id"))
    return [ev], {"evidence_id": eid}


def dod_check(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    profile = gov.settings["dod_profiles"].get(args.get("deliverable_type", "software"),
                                               gov.settings["dod_profiles"]["software"])
    ver = store.find("verification", wp_id=wid, verdict="PASS")
    evd = store.find("evidence", wp_id=wid)
    items = {item: bool(ver and evd) for item in profile}
    verdict = "PASS" if all(items.values()) else "FAIL"
    did = nid(store, "quality_profile")
    ev = upsert(store, "dod_check", f"DOD-{wid}", {
        "wp_id": wid, "verdict": verdict, "items": items, "verifier_occupant": occupant,
        "ts": store.clock(),
    }, wp.get("project_id"))
    return [ev], {"wp_id": wid, "dod_verdict": verdict, "items": items}


def verify_run(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    acs = store.find("acceptance_criterion", wp_id=wid)
    bound = {a["test_id"] for a in acs}
    tids = args["test_ids"]
    if bound and not set(tids) <= bound:
        from ..governance import Refusal
        raise Refusal("FR-QA-02", "test_binding", f"test_ids {sorted(set(tids) - bound)} not bound to WP acceptance criteria")
    verdicts = args.get("verdicts", {})
    evd = store.find("evidence", wp_id=wid)
    per = {}
    for t in tids:
        v = verdicts.get(t, "INSUFFICIENT-EVIDENCE")
        if not evd:
            v = "INSUFFICIENT-EVIDENCE"
        per[t] = v
    verdict = "PASS" if per and all(v == "PASS" for v in per.values()) else "FAIL"
    vid = nid(store, "verification")
    cycle = len(store.find("verification", wp_id=wid)) + 1
    if cycle > 1 and not args.get("regression_evidence_id"):
        from ..governance import Refusal
        raise Refusal("FR-QA-07", "regression_evidence", "re-verification (cycle>1) requires unchanged-scope regression evidence ref")
    evs = [
        upsert(store, "verification", vid, {
            "wp_id": wid, "verifier_occupant": occupant, "kind": args.get("kind", "verification"),
            "test_ids": tids, "verdict": verdict, "per_criterion": per, "cycle_n": cycle,
            "evidence_ids": [e["id"] for e in evd],
            "regression_evidence_id": args.get("regression_evidence_id"), "ts": store.clock(),
        }, wp.get("project_id")),
    ]
    if wp["state"] == "handed_off":
        evs.append(transition(wid, "handed_off", "verifying", "verification started"))
    if verdict == "FAIL":
        for t, v in per.items():
            if v != "PASS":
                did = nid(store, "defect")
                ac = next((a for a in acs if a["test_id"] == t), None)
                evs.append(upsert(store, "defect", did, {
                    "wp_id": wid, "verification_id": vid, "criterion_id": ac["id"] if ac else None,
                    "test_id": t, "severity": "major", "description": f"criterion {t} verdict {v}",
                    "state": "open", "rework_id": None,
                }, wp.get("project_id")))
    return evs, {"verification_id": vid, "verdict": verdict, "per_criterion": per, "cycle_n": cycle}


def acceptance_decide(store, gov, args, occupant):
    wid = args["wp_id"]
    wp = store.get("work_package", wid)
    decision = args["decision"]
    ver = store.find("verification", wp_id=wid, verdict="PASS")
    dod = store.get("dod_check", f"DOD-{wid}")
    if decision == "accept":
        if not dod or dod.get("verdict") != "PASS":
            from ..governance import Refusal
            raise Refusal("FR-QA-03", "dod_gate", "acceptance requires DoD gate PASS (FR-QA-03)")
    aid = nid(store, "acceptance")
    evs = [
        upsert(store, "acceptance", aid, {
            "wp_id": wid, "acceptor_role": ",".join(gov.roles_of(occupant)), "acceptor_occupant": occupant,
            "verdict_ref": ver[-1]["id"] if ver else None,
            "verifier_occupant": ver[-1]["verifier_occupant"] if ver else None,
            "executor_occupant": wp.get("executor_occupant"),
            "independence_ok": wp.get("executor_occupant") != occupant,
            "decision": decision, "evidence_ids": [e["id"] for e in store.find("evidence", wp_id=wid)],
            "ts": store.clock(),
        }, wp.get("project_id")),
    ]
    if decision == "accept":
        evs.append(transition(wid, wp["state"], "accepted", "acceptance on verified evidence"))
        dev, _ = decision_event(store, wp.get("project_id"), "acceptance",
                                f"WP {wid} accepted", "I-01/I-03 acceptance on verified evidence", occupant, [aid])
        evs.append(dev)
    return evs, {"acceptance_id": aid, "decision": decision, "state": "accepted" if decision == "accept" else wp["state"]}


def defect_log(store, gov, args, occupant):
    did = nid(store, "defect")
    ev = upsert(store, "defect", did, {
        "wp_id": args["wp_id"], "verification_id": args["verification_id"],
        "severity": args["severity"], "description": args["description"],
        "state": "open", "rework_id": None,
    }, args.get("project_id") or (store.get("work_package", args["wp_id"]) or {}).get("project_id"))
    return [ev], {"defect_id": did}


def rework_open(store, gov, args, occupant):
    wid = args["wp_id"]
    if not args.get("defect_ids"):
        from ..governance import Refusal
        raise Refusal("FR-QA-07", "bounded_list", "rework requires a bounded defect/criterion list (no open-ended scope)")
    wp = store.get("work_package", wid)
    n = len(store.find("rework_cycle", wp_id=wid)) + 1
    rid = nid(store, "rework_cycle")
    evs = [
        upsert(store, "rework_cycle", rid, {
            "wp_id": wid, "defect_ids": args["defect_ids"], "cycle_n": n,
            "opened_ts": store.clock(), "closed_ts": None,
            "max_cycles": gov.settings["rework_max_cycles"],
        }, wp.get("project_id")),
        transition(wid, wp["state"], "rework", f"bounded rework cycle {n}"),
    ]
    for d in args["defect_ids"]:
        evs.append(upsert(store, "defect", d, {"state": "in_rework", "rework_id": rid}))
    return evs, {"rework_id": rid, "cycle_n": n, "state": "rework"}


def defect_verify(store, gov, args, occupant):
    """Defect 'verified' state requires a verifier-seat action."""
    d = store.get("defect", args["defect_id"])
    if not args.get("evidence_ids"):
        from ..governance import Refusal
        raise Refusal("FR-QA-06", "defect_evidence", "defect verification requires evidence refs")
    ev = upsert(store, "defect", args["defect_id"],
                {"state": "verified", "verified_by": occupant, "verified_ts": store.clock(),
                 "evidence_ids": args["evidence_ids"]})
    return [ev], {"defect_id": args["defect_id"], "state": "verified"}


ACTIONS = {
    "quality_profile": quality_profile, "ac_set": ac_set, "evidence_attach": evidence_attach,
    "dod_check": dod_check, "verify_run": verify_run, "acceptance_decide": acceptance_decide,
    "defect_log": defect_log, "rework_open": rework_open, "defect_verify": defect_verify,
}
