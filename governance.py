"""starq-pm governance engine: pre-mutation guards, role resolution,
RACI authority, independence, tolerances/exceptions, WIP, evidence freshness.
Every refusal appends a 'refusal' event.
Identity-agnostic: occupants are opaque config-bound ids; transport metadata never grants authority."""
import copy
import re

from . import defaults

READ_ACTIONS = {
    "board", "metrics_compute", "variance", "delta_report", "cadence_report",
    "milestone_performance", "config_show", "chain_verify", "evidence_lookup", "export", "anchor",
    "wbs", "coverage", "mvp", "sequencing", "allocation", "sle_compute",
}

# action -> allowed roles
ACTION_ROLES = {
    "charter_create": {"O"}, "charter_update": {"O"}, "justification_record": {"O"},
    "charter_authorize": {"F"}, "tolerance_set": {"O", "F"},
    "requirement_upsert": {"O"}, "deliverable_decompose": {"O"}, "trace_link": {"O"},
    "scope_baseline": {"F"}, "prioritize": {"O"},
    "wp_create": {"O"}, "sequence": {"O"}, "milestone_plan": {"O"}, "estimate_flow": {"O"},
    "allocate_seat": {"O"}, "wip_set": {"O", "F"},
    "dispatch": {"O"}, "handoff": {"E"}, "status_record": {"E"}, "blocker_raise": {"E"},
    "blocker_clear": {"O"}, "stop_veto": {"F"}, "substitution_request": {"F"},
    "blocker_review": {"O"}, "milestone_complete": {"O"},
    "defect_verify": {"V"}, "treatment_implement": {"O", "E"}, "treatment_verify": {"V"},
    "issue_close": {"O", "V"}, "risk_review": {"O"}, "escalation_ack": {"O", "F"},
    "corrective_verify": {"O", "E", "V"}, "handover_ack": {"O", "E", "V", "F"}, "lessons_review": {"O"},
    "quality_profile": {"O"}, "ac_set": {"O"}, "dod_check": {"V"}, "verify_run": {"V"},
    "evidence_attach": {"E", "V"}, "acceptance_decide": {"O", "F"}, "defect_log": {"V"},
    "rework_open": {"V", "O"},
    "gate_evaluate": {"O"}, "gate_decide": {"O"}, "founder_authorize": {"F"},
    "cr_create": {"O", "E"}, "cr_assess": {"O"}, "cr_decide": {"F", "O"}, "rebaseline": {"O"},
    "decision_record": {"O"},
    "risk_identify": {"O", "E"}, "risk_assess": {"O"},
    "issue_log": {"O", "E"}, "escalate": {"O"}, "exception_raise": {"O", "E"},
    "treatment_plan": {"O", "E"},
    "exception_decide": {"O", "F"}, "corrective_action": {"O"},
    "baseline_set": {"O"}, "final_verify": {"V"}, "formal_accept": {"F"},
    "handover_docs": {"O"}, "lessons": {"O", "E"}, "archive": {"O"},
    "role_bind": {"F"}, "tolerance_update": {"F"}, "criteria_set": {"O"},
    "cadence_set": {"O"}, "autonomy_set": {"F"}, "freshness_set": {"O"},
}
for a in READ_ACTIONS:
    ACTION_ROLES.setdefault(a, {"O", "E", "V", "F"})

# actions that mutate a work package's quality path -> independence applies
INDEPENDENCE_ACTIONS = {"dod_check", "verify_run", "defect_log", "final_verify"}
ACCEPT_ACTIONS = {"acceptance_decide", "formal_accept"}


class Refusal(Exception):
    def __init__(self, code, guard, reason):
        self.code, self.guard, self.reason = code, guard, reason
        super().__init__(f"{code}: {reason}")


class Governance:
    def __init__(self, store, settings=None):
        self.store = store
        self.settings = copy.deepcopy(defaults.DEFAULTS)
        if settings:
            self.settings.update(copy.deepcopy(settings))

    # ---------- role resolution ----------
    def roles_of(self, occupant):
        return [r for r, b in self.settings["roles"].items() if occupant in b.get("occupants", [])]

    def seat_limit(self, occupant):
        wip = self.settings["wip"]
        return wip.get(occupant, wip.get("default", 2))

    # ---------- guards ----------
    def g_known_occupant(self, action, args, occupant):
        if not self.roles_of(occupant):
            raise Refusal("F-08", "known_occupant", f"occupant '{occupant}' has no role binding; substitution (GW-01) required")

    def g_role(self, action, args, occupant):
        allowed = ACTION_ROLES.get(action, set())
        if not (set(self.roles_of(occupant)) & allowed):
            raise Refusal("RACI-ROLE", "raci_role", f"role(s) {self.roles_of(occupant)} not authorized for {action} (needs {sorted(allowed)})")

    def g_banned_fields(self, action, args, occupant):
        blob = str(args).lower()
        for b in defaults.BANNED_FIELDS:
            if re.search(rf'["\']?{b}["\']?\s*[:=]', blob) or f'"{b}"' in blob:
                raise Refusal("C-03", "banned_fields", f"banned human-effort/velocity field '{b}' rejected (D1 constraint C-03)")

    def g_legacy_terms(self, action, args, occupant):
        if action == "quality_profile":
            chars = args.get("characteristics", {})
            names = [str(c).lower() for c in (chars.keys() if isinstance(chars, dict) else chars)]
            for t in defaults.LEGACY_25010_TERMS:
                if t in names:
                    raise Refusal("FR-QA-01", "legacy_25010", f"legacy ISO/IEC 25010 term '{t}' rejected; use 2023 vocabulary (interaction capability, flexibility, safety)")

    def g_charter_exists(self, action, args, occupant):
        if action != "wp_create":
            return
        pid = args.get("project_id")
        if not self.store.find("charter", project_id=pid):
            raise Refusal("FR-IN-01", "charter_required", "work package creation requires a project charter first")

    def g_charter_lock(self, action, args, occupant):
        if action != "charter_update":
            return
        ch = self.store.get("charter", args.get("charter_id") or args.get("id"))
        if ch and ch.get("baselined"):
            cr = self.store.get("change_request", args.get("cr_id")) if args.get("cr_id") else None
            if not cr or cr.get("state") not in ("approved", "rebaselined"):
                raise Refusal("FR-IN-01", "baseline_lock", "baselined charter changes only via an approved change request (FR-MC-02); direct edit rejected")

    def g_independence(self, action, args, occupant):
        if action not in INDEPENDENCE_ACTIONS:
            return
        wp = self.store.get("work_package", args.get("wp_id"))
        if wp and wp.get("executor_occupant") == occupant:
            raise Refusal("I-02", "independence", "verifier occupant == executor occupant; substitution (GW-01) required, independence never waived")

    def g_accept_authority(self, action, args, occupant):
        if action not in ACCEPT_ACTIONS:
            return
        wp = self.store.get("work_package", args.get("wp_id")) if args.get("wp_id") else None
        if wp and wp.get("executor_occupant") == occupant:
            raise Refusal("I-01", "no_self_acceptance", "executor cannot accept its own work package")
        if action == "acceptance_decide":
            if not (set(self.roles_of(occupant)) & {"O", "F"}):
                raise Refusal("I-01", "accept_authority", "acceptance authority is O or F only")
            ver = self.store.find("verification", wp_id=args.get("wp_id"), verdict="PASS")
            cycles = self.store.find("rework_cycle", wp_id=args.get("wp_id"))
            if cycles and not any(v.get("cycle_n", 0) > len(cycles) for v in ver):
                raise Refusal("FR-QA-07", "reverification", "re-acceptance requires re-verification evidence after rework")
            dod = self.store.get("dod_check", f"DOD-{args.get('wp_id')}")
            if dod and dod.get("verdict") != "PASS":
                missing = [k for k, v in dod.get("items", {}).items() if not v]
                raise Refusal("FR-QA-03", "dod_gate", f"acceptance requires DoD PASS; unsatisfied items: {missing}")
            open_defects = [d for d in self.store.find("defect", wp_id=args.get("wp_id")) if d.get("state") in ("open", "in_rework")]
            if open_defects:
                raise Refusal("FR-QA-06", "open_defects", f"open defects block acceptance: {[d['id'] for d in open_defects]}")
            if not ver:
                raise Refusal("I-03", "verified_evidence", "acceptance requires a verifier PASS record (no self-report/model-judge-only)")
            evd = self.store.find("evidence", wp_id=args.get("wp_id"))
            if not any(e.get("class") in ("test_output", "log", "screenshot", "report") for e in evd):
                raise Refusal("C-06", "evidence_class", "acceptance requires re-executed/inspected evidence; self-report/model-judge-only rejected")
        if action == "formal_accept":
            fv = self.store.find("verification", project_id=args.get("project_id"), kind="final", verdict="PASS")
            if not fv:
                raise Refusal("FR-CL-01", "final_verification", "formal acceptance requires final verification PASS")

    def g_wip(self, action, args, occupant):
        if action != "dispatch":
            return
        seat = args.get("to_occupant")
        active = [w for w in self.store.find("work_package")
                  if w.get("seat_id") == seat and w.get("state") in ("dispatched", "executing", "blocked")]
        if len(active) >= self.seat_limit(seat):
            raise Refusal("F-10", "wip_limit", f"WIP limit reached for seat '{seat}' ({len(active)} active); queue dispatch (FR-SCH-05)")

    def g_freshness(self, action, args, occupant):
        if action not in ("verify_run", "dod_check", "acceptance_decide"):
            return
        now = self.store.clock()
        max_age = self.settings["evidence_max_age"]
        evs = self.store.find("evidence", wp_id=args.get("wp_id"))
        if action in ("verify_run", "acceptance_decide") and not evs:
            raise Refusal("NFR-04", "evidence_required", "verification/acceptance requires evidence references; fail-closed")
        for ev in evs:
            if ev.get("available") is False:
                raise Refusal("F-06", "evidence_freshness", f"evidence {ev['id']} unavailable (content not present); fail-closed")
            cap = ev.get("captured_ts")
            if not cap:
                raise Refusal("F-06", "evidence_freshness", f"evidence {ev['id']} undated; fail-closed")
            from datetime import datetime
            try:
                age = (datetime.fromisoformat(now) - datetime.fromisoformat(cap)).total_seconds()
            except ValueError:
                raise Refusal("F-06", "evidence_freshness", f"evidence {ev['id']} invalid date; fail-closed")
            limit = max_age.get(ev.get("class", "test_output"), 86400)
            if age < 0:
                raise Refusal("F-06", "evidence_freshness", f"evidence {ev['id']} future-dated; fail-closed")
            if age > limit:
                raise Refusal("F-06", "evidence_freshness", f"evidence {ev['id']} stale (age {int(age)}s > {limit}s); fail-closed")

    def g_rework_bound(self, action, args, occupant):
        if action != "rework_open":
            return
        cycles = self.store.find("rework_cycle", wp_id=args.get("wp_id"))
        n = len(cycles)
        if n >= self.settings["rework_max_cycles"]:
            raise Refusal("FR-QA-07", "rework_bound", f"rework cycles ({n}) >= max ({self.settings['rework_max_cycles']}); escalation required, no further auto-rework")

    def g_exception_active(self, action, args, occupant):
        """Tolerance breach requires an approved, unexpired exception."""
        cls = args.get("breach_class")
        if not cls:
            return
        now = self.store.clock()
        from datetime import datetime
        for ex in self.store.find("exception", tolerance_class=cls, decision="approved"):
            exp = ex.get("expiry_ts")
            if exp and datetime.fromisoformat(now) <= datetime.fromisoformat(exp):
                return
        raise Refusal("F-09", "tolerance_exception", f"tolerance breach '{cls}' without approved unexpired exception; operation halted (FR-IN-05 / D6 §5 escalation)")

    def g_gate_authority(self, action, args, occupant):
        if action in ("founder_authorize", "stop_veto", "charter_authorize", "formal_accept", "scope_baseline"):
            if "F" not in self.roles_of(occupant):
                raise Refusal("I-04", "founder_gate", "Founder authority (F) required for this gate/authorization")

    def g_substitution_independence(self, action, args, occupant):
        if action != "substitution_request":
            return
        to = args.get("to_occupant")
        if args.get("role") == "V":
            for wp in self.store.find("work_package", state="verifying"):
                if wp.get("executor_occupant") == to:
                    raise Refusal("I-02", "substitution_independence", "incoming verifier occupies an executor seat with pending verification; independence conflict")

    def g_scope_lock(self, action, args, occupant):
        if action not in ("requirement_upsert", "prioritize", "deliverable_decompose"):
            return
        pid = args.get("project_id")
        if not pid and action == "prioritize":
            req = self.store.get("requirement", args.get("requirement_id"))
            pid = req.get("project_id") if req else None
        if pid and self.store.find("scope_baseline", project_id=pid) and not args.get("cr_id"):
            raise Refusal("FR-SR-04", "scope_lock", "baselined scope changes only via an approved CR (FR-SR-04/FR-MC-02)")

    def g_closure(self, action, args, occupant):
        if action != "formal_accept":
            return
        pid = args.get("project_id")
        wps = self.store.find("work_package", project_id=pid)
        gaps = [w["id"] for w in wps if w.get("state") not in ("accepted", "closed", "cancelled")]
        if gaps:
            raise Refusal("FR-CL-01", "closure_gaps", f"deliverables lacking PASS verification/acceptance: {gaps}")
        if not self.store.find("verification", project_id=pid, kind="validation", verdict="PASS"):
            raise Refusal("FR-CL-01", "validation_record", "closure requires a validation record (fitness for use) distinct from verification")
        open_defects = [d for d in self.store.find("defect", project_id=pid) if d.get("state") in ("open", "in_rework")]
        if open_defects:
            raise Refusal("FR-CL-01", "open_defects_closure", f"open defects block closure: {[d['id'] for d in open_defects]}")
        if not self.store.get("lessons_review", f"LR-{pid}"):
            raise Refusal("FR-CL-04", "lessons_review", "closure requires a lessons-review record")

    def g_config_tag(self, action, args, occupant):
        if action not in ("criteria_set", "tolerance_update", "tolerance_set"):
            return
        payload = args.get("criteria") or args.get("tolerances") or {}
        if not payload:
            return
        tag = args.get("class_tag")
        if tag not in ("ESTABLISHED", "STARQ-ADAPT", "EXPERIMENTAL"):
            raise Refusal("NFR-10", "class_tag", "normative methodology config requires a class tag [ESTABLISHED|STARQ-ADAPT|EXPERIMENTAL]")
        if tag == "EXPERIMENTAL":
            sf = args.get("safeguards") or {}
            if not all(sf.get(k) for k in ("failure_mode", "success_criterion", "fallback")):
                raise Refusal("NFR-10", "experimental_safeguards", "experimental entries require failure_mode, success_criterion, fallback")

    def g_ceremony(self, action, args, occupant):
        if action == "role_bind" and args.get("role") not in ("O", "E", "V", "F"):
            raise Refusal("C-01", "rejected_machinery", "floor roles are O/E/V/F only; Scrum role triple is rejected machinery (D1)")
        if action == "cadence_set":
            cad = args.get("cadence", {})
            banned = {"standup", "daily_scrum", "sprint_review", "retrospective_ceremony"}
            if cad.get("ceremony") or str(cad.get("tick", "")).lower() in banned:
                raise Refusal("C-02", "rejected_machinery", "Scrum ceremonies are rejected as floor machinery (D1); cadence is on-demand computation")

    def g_standards_currency(self, action, args, occupant):
        if action != "decision_record":
            return
        basis = args.get("standards_basis", "")
        if "12207:2017" in basis and "withdrawn" not in basis.lower():
            raise Refusal("NFR-10", "standards_currency", "ISO/IEC/IEEE 12207:2017 is WITHDRAWN (2026-04-29); cite 12207:2026")

    def g_schema(self, action, args, occupant):
        required = REQUIRED_ARGS.get(action, [])
        missing = [k for k in required if args.get(k) in (None, "")]
        if missing:
            raise Refusal("F-11", "schema", f"missing required args: {missing}")

    # ---------- runner ----------
    # invariant guards (I-01/I-02/I-04) run BEFORE the generic RACI role guard so the
    # specific governance refusal is the observable one (negative controls assert codes).
    GUARDS = [g_schema, g_known_occupant, g_independence, g_freshness, g_gate_authority,
              g_accept_authority, g_role, g_banned_fields, g_legacy_terms,
              g_charter_exists, g_charter_lock, g_scope_lock, g_wip, g_rework_bound,
              g_exception_active, g_substitution_independence, g_closure,
              g_config_tag, g_ceremony, g_standards_currency]

    def check(self, action, args, occupant):
        for g in self.GUARDS:
            # guards self-select by action; cheap no-ops elsewhere
            g(self, action, args, occupant)

    def refuse(self, action, args, occupant, refusal):
        self.store.append("refusal", ",".join(self.roles_of(occupant)) or "?", occupant,
                          args.get("wp_id") or args.get("project_id") or action,
                          {"action": action, "code": refusal.code, "guard": refusal.guard,
                           "reason": refusal.reason})
        return {"error": refusal.code, "refused_by": refusal.guard, "reason": refusal.reason}


REQUIRED_ARGS = {
    "charter_create": ["project_id", "authorization_ref", "objectives", "success_criteria"],
    "charter_authorize": ["charter_id"],
    "wp_create": ["project_id", "title", "deliverable_id"],
    "dispatch": ["wp_id", "to_occupant"],
    "handoff": ["wp_id", "artifacts"],
    "evidence_attach": ["wp_id", "path", "sha256", "captured_ts", "class"],
    "verify_run": ["wp_id", "test_ids"],
    "acceptance_decide": ["wp_id", "decision"],
    "quality_profile": ["deliverable_type", "characteristics"],
    "ac_set": ["wp_id", "text", "test_id"],
    "defect_verify": ["defect_id", "evidence_ids"],
    "treatment_implement": ["treatment_id", "evidence_ids"],
    "treatment_verify": ["treatment_id"],
    "issue_close": ["issue_id", "evidence_ids"],
    "risk_review": ["project_id", "summary"],
    "escalation_ack": ["issue_id"],
    "corrective_verify": ["corrective_id", "evidence_ids"],
    "handover_ack": ["handover_doc_id"],
    "lessons_review": ["project_id", "summary"],
    "risk_identify": ["project_id", "category", "description"],
    "risk_assess": ["risk_id", "likelihood", "impact"],
    "exception_raise": ["tolerance_class", "breach_ref"],
    "exception_decide": ["exception_id", "decision"],
    "milestone_complete": ["milestone_id", "evidence_ids"],
    "blocker_review": ["project_id"],
    "founder_authorize": ["gate_id"],
    "gate_decide": ["gate_id", "decision"],
    "cr_create": ["project_id", "scope", "description"],
    "cr_decide": ["cr_id", "decision"],
    "role_bind": ["role", "occupants"],
    "substitution_request": ["role", "from_occupant", "to_occupant"],
    "formal_accept": ["project_id"],
    "final_verify": ["project_id", "test_ids"],
    "requirement_upsert": ["project_id", "id", "statement", "priority"],
    "scope_baseline": ["project_id"],
    "milestone_plan": ["project_id", "name", "planned_ts"],
    "estimate_flow": ["wp_id", "sle_time"],
    "allocate_seat": ["wp_id", "seat_id"],
    "sequence": ["wp_id", "dependency_ids"],
    "blocker_raise": ["wp_id", "reason"],
    "blocker_clear": ["blocker_id"],
    "status_record": ["wp_id", "note"],
    "stop_veto": ["project_id", "reason"],
    "justification_record": ["project_id", "statement", "review_decision"],
    "tolerance_set": ["project_id", "tolerances"],
    "trace_link": ["from_ref", "to_ref", "kind"],
    "deliverable_decompose": ["project_id", "name", "type"],
    "prioritize": ["requirement_id", "priority", "rationale"],
    "wip_set": ["limits"],
    "dod_check": ["wp_id"],
    "defect_log": ["wp_id", "verification_id", "severity", "description"],
    "rework_open": ["wp_id", "defect_ids"],
    "gate_evaluate": ["gate_id"],
    "cr_assess": ["cr_id", "impact_assessment"],
    "rebaseline": ["cr_id"],
    "decision_record": ["project_id", "kind", "statement", "rationale"],
    "treatment_plan": ["risk_id", "kind", "actions"],
    "issue_log": ["project_id", "description", "severity"],
    "escalate": ["issue_id"],
    "corrective_action": ["issue_id", "action", "owner"],
    "baseline_set": ["project_id", "kind", "snapshot_hash"],
    "handover_docs": ["project_id", "doc_ref", "sha256"],
    "lessons": ["project_id", "category", "observation", "recommendation"],
    "archive": ["project_id"],
    "tolerance_update": ["tolerances"],
    "criteria_set": ["criteria"],
    "cadence_set": ["cadence"],
    "autonomy_set": ["class"],
    "freshness_set": ["max_age"],
}
