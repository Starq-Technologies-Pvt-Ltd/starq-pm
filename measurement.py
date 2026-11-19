"""starq-pm measurement engine — MT-01.13, computation specs.
Deterministic: same events + same injected clock => same values. NO velocity.
Baselines measured from history; targets governance-set."""
from datetime import datetime


def _dt(s):
    return datetime.fromisoformat(s)


def _finished(store):
    return [w for w in store.find("work_package") if w.get("finished_ts") and w.get("started_ts")]


def _cycle(w):
    return (_dt(w["finished_ts"]) - _dt(w["started_ts"])).total_seconds()


def _pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round(p / 100 * (len(s) - 1)))))
    return s[k]


def _median(vals):
    return _pct(vals, 50)


def compute(store, mid, window, settings):
    now = store.clock()
    fin = _finished(store)
    if mid == "MT-01":  # throughput = finished count / window length (days)
        n = len(fin)
        if window and window.get("from") and window.get("to"):
            days = max(1e-9, (_dt(window["to"]) - _dt(window["from"])).total_seconds() / 86400)
            inwin = [w for w in fin if window["from"] <= w["finished_ts"] <= window["to"]]
            return {"value": len(inwin) / days, "sample_size": len(inwin), "unit": "items/day"}
        return {"value": n, "sample_size": n, "unit": "count (no window; rate baseline needs >=10 finished)"}
    if mid == "MT-02":  # cycle time median + p85
        cycles = [_cycle(w) for w in fin]
        return {"value": {"median_s": _median(cycles), "p85_s": _pct(cycles, 85)}, "sample_size": len(cycles)}
    if mid == "MT-03":  # WIP per seat + limit compliance
        active = [w for w in store.find("work_package") if w.get("state") in ("dispatched", "executing", "blocked")]
        per = {}
        for w in active:
            per[w.get("seat_id")] = per.get(w.get("seat_id"), 0) + 1
        limits = settings.get("wip", {})
        compliance = all(c <= limits.get(s, limits.get("default", 2)) for s, c in per.items())
        util = {}
        if window and window.get("from") and window.get("to"):
            wlen = max(1e-9, (_dt(window["to"]) - _dt(window["from"])).total_seconds())
            for w in store.find("work_package"):
                if w.get("started_ts") and w.get("seat_id"):
                    end = w.get("finished_ts") or now
                    active_s = max(0.0, (_dt(min(end, window["to"])) - _dt(max(w["started_ts"], window["from"]))).total_seconds())
                    util[w["seat_id"]] = util.get(w["seat_id"], 0.0) + active_s / wlen
        return {"value": {"wip": per, "compliant": compliance, "utilization": util}, "sample_size": len(active)}
    if mid == "MT-04":  # work item age + blocked age
        ages, blocked = [], []
        for w in store.find("work_package"):
            if w.get("state") in ("dispatched", "executing", "blocked") and w.get("started_ts"):
                ages.append((_dt(now) - _dt(w["started_ts"])).total_seconds())
            if w.get("state") == "blocked" and w.get("block_ts"):
                blocked.append((_dt(now) - _dt(w["block_ts"])).total_seconds())
        return {"value": {"age_median_s": _median(ages), "blocked_age_median_s": _median(blocked)}, "sample_size": len(ages)}
    if mid == "MT-05":  # SLE attainment
        ok = [w for w in fin if (w.get("estimate") or {}).get("sle_time") is not None and _cycle(w) <= w["estimate"]["sle_time"] * 86400]
        return {"value": (len(ok) / len(fin)) if fin else None, "sample_size": len(fin)}
    if mid == "MT-06":  # first-pass verification yield
        acc = store.find("acceptance", decision="accept")
        wpids = {a["wp_id"] for a in acc if a.get("wp_id")}
        first = [w for w in wpids if not store.find("verification", wp_id=w, verdict="FAIL")]
        return {"value": (len(first) / len(wpids)) if wpids else None, "sample_size": len(wpids)}
    if mid == "MT-07":  # rework rate
        verified = {v["wp_id"] for v in store.find("verification") if v.get("wp_id")}
        rw = len(store.find("rework_cycle"))
        return {"value": (rw / len(verified)) if verified else None, "sample_size": len(verified)}
    if mid == "MT-08":  # milestone variance
        ms = store.find("milestone")
        deltas = [(_dt(m["actual_ts"]) - _dt(m["planned_ts"])).total_seconds() for m in ms if m.get("actual_ts")]
        met = len([m for m in ms if m.get("status") == "met"])
        return {"value": {"variance_median_s": _median(deltas), "hit_rate": (met / len(ms)) if ms else None}, "sample_size": len(ms)}
    if mid == "MT-09":  # evidence completeness on accepted WPs
        acc = {a["wp_id"] for a in store.find("acceptance", decision="accept") if a.get("wp_id")}
        complete = 0
        for w in acc:
            acs = store.find("acceptance_criterion", wp_id=w)
            evd = store.find("evidence", wp_id=w)
            if acs and evd:
                complete += 1
        return {"value": (complete / len(acc)) if acc else None, "sample_size": len(acc)}
    if mid == "MT-10":  # fail-closed incidence = refusals / operations
        refusals = store.count_events("refusal")
        ops = store.count_events("entity_upsert") + store.count_events("board_transition")
        return {"value": (refusals / ops) if ops else 0.0, "sample_size": ops, "refusals": refusals}
    if mid == "MT-11":  # decision-log completeness — per-operation join fraction
        ops = [o for k in ("gate", "acceptance", "change_request", "exception", "substitution", "config")
               for o in store.find(k)]
        if not ops:
            return {"value": None, "sample_size": 0}
        refed = {r for d in store.find("decision") for r in d.get("refs", [])}
        n = sum(1 for o in ops if o["id"] in refed)
        return {"value": n / len(ops), "sample_size": len(ops), "with_decision_ref": n}
    if mid == "MT-12":  # exception resolution time (raised -> decided), from chain timestamps
        raised, decided = {}, {}
        for e in store.events():
            if e["type"] == "entity_upsert" and e["payload"].get("kind") == "exception":
                eid = e["payload"]["id"]
                d = e["payload"]["data"]
                if eid not in raised:
                    raised[eid] = e["ts"]
                if d.get("decision") and eid not in decided:
                    decided[eid] = e["ts"]
        durations = [(_dt(decided[i]) - _dt(raised[i])).total_seconds() for i in decided if i in raised]
        return {"value": {"median_s": _median(durations), "p85_s": _pct(durations, 85)}, "sample_size": len(durations)}
    if mid == "MT-13":  # lessons capture per closed project
        closed = store.find("project", status="closed")
        counts = {p["id"]: len(store.find("lessons", project_id=p["id"])) for p in closed}
        return {"value": counts, "sample_size": len(closed)}
    raise ValueError(f"unknown metric {mid}")
