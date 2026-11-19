"""starq-pm model-facing tool surface: 12 action-based tools, one per workflow family.
SDK contract: schema {name, description, parameters}; handler(args, **kwargs) -> JSON string;
exceptions caught into error JSON. Caller context kwargs are provenance only, never authority."""
import json

FAMILIES = {
    "starq_pm_initiate": ["charter_create", "charter_update", "justification_record", "charter_authorize", "tolerance_set"],
    "starq_pm_requirements": ["requirement_upsert", "deliverable_decompose", "trace_link", "scope_baseline", "prioritize", "wbs", "coverage", "mvp"],
    "starq_pm_plan": ["wp_create", "sequence", "milestone_plan", "estimate_flow", "allocate_seat", "wip_set", "sequencing", "allocation", "sle_compute", "milestone_complete"],
    "starq_pm_execute": ["dispatch", "handoff", "status_record", "blocker_raise", "blocker_clear", "stop_veto", "substitution_request", "blocker_review"],
    "starq_pm_verify": ["quality_profile", "ac_set", "dod_check", "verify_run", "evidence_attach", "acceptance_decide", "defect_log", "rework_open", "defect_verify"],
    "starq_pm_gates": ["gate_evaluate", "gate_decide", "founder_authorize"],
    "starq_pm_change": ["cr_create", "cr_assess", "cr_decide", "rebaseline", "decision_record"],
    "starq_pm_risk": ["risk_identify", "risk_assess", "treatment_plan", "issue_log", "escalate", "exception_raise", "exception_decide", "corrective_action", "treatment_implement", "treatment_verify", "issue_close", "risk_review", "escalation_ack", "corrective_verify"],
    "starq_pm_report": ["board", "baseline_set", "metrics_compute", "variance", "delta_report", "cadence_report", "milestone_performance"],
    "starq_pm_close": ["final_verify", "formal_accept", "handover_docs", "lessons", "archive", "handover_ack", "lessons_review"],
    "starq_pm_config": ["role_bind", "tolerance_update", "criteria_set", "cadence_set", "autonomy_set", "freshness_set", "config_show"],
    "starq_pm_audit": ["chain_verify", "evidence_lookup", "export", "anchor"],
}

DESCRIPTIONS = {
    "starq_pm_initiate": "Project initiation: charter, business justification, Founder authorization, tolerances (WF-01).",
    "starq_pm_requirements": "Requirements register, WBS deliverables, trace links, scope baseline, MoSCoW prioritization (WF-01).",
    "starq_pm_plan": "Work packages, sequencing, milestones, SLE flow estimates, seat allocation, WIP limits (WF-01/WF-02).",
    "starq_pm_execute": "Dispatch, handoff, async status, blockers, Founder stop/veto, role substitution (WF-02/WF-07/GW-01).",
    "starq_pm_verify": "Quality profiles (ISO/IEC 25010:2023), acceptance criteria bound to test IDs, DoD, independent verification, evidence, acceptance, defects, bounded rework (WF-03).",
    "starq_pm_gates": "Stage-gate evaluation and decision; stage transitions require Founder authorization (WF-04).",
    "starq_pm_change": "Change requests, impact assessment, decision, rebaseline, decision log (WF-05).",
    "starq_pm_risk": "Risk register (ordinal assessment), treatments, issues, escalation, tolerance exceptions, corrective actions (WF-06).",
    "starq_pm_report": "Execution board, performance baselines, flow metrics MT-01..13, variance, deterministic delta/cadence reports, milestone performance (WF-08).",
    "starq_pm_close": "Final verification, Founder formal acceptance, documentation handover, lessons learned, archive (WF-09).",
    "starq_pm_config": "Governed configuration: role bindings, tolerances, risk criteria, cadence, autonomy class, evidence freshness (D6, NFR-06).",
    "starq_pm_audit": "Hash-chain verification, evidence lookup, redacted export, audit anchor for Founder custody (NFR-03/04).",
}


def _schema(name, actions):
    return {
        "name": name,
        "description": DESCRIPTIONS[name] + " Pass occupant (your configured role-binding id), action, and args.",
        "parameters": {
            "type": "object",
            "properties": {
                "occupant": {"type": "string", "description": "Caller occupant id bound to a governance role (O/E/V/F) in settings.roles."},
                "action": {"type": "string", "enum": actions, "description": "Workflow action to perform."},
                "args": {"type": "object", "description": "Action arguments (see design D4/D5/D7)."},
            },
            "required": ["occupant", "action"],
        },
    }


TOOLS = {name: {"schema": _schema(name, actions), "actions": actions} for name, actions in FAMILIES.items()}


def make_handler(pm, tool_name):
    allowed = set(FAMILIES[tool_name])

    def handler(args, **kwargs):
        try:
            action = args.get("action")
            occupant = args.get("occupant", "")
            inner = dict(args.get("args") or {})
            if action not in allowed:
                return json.dumps({"error": "F-11", "refused_by": "schema",
                                   "reason": f"action '{action}' not in {tool_name}"})
            # transport provenance only; never grants authority
            meta = {k: kwargs.get(k) for k in ("task_id", "session_id") if kwargs.get(k)}
            if meta:
                inner.setdefault("transport_meta", meta)
            result = pm.operate(action, inner, occupant)
            return json.dumps(result)
        except Exception as exc:  #: never raise into the dispatcher
            return json.dumps({"error": "F-11", "refused_by": "handler", "reason": str(exc)})

    return handler
