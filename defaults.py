"""starq-pm config defaults — three-class tagged.
Values are [ADAPTED] unless marked; mechanisms [ESTABLISHED]. No identity hardcoded.
settings overlay (plugins.entries.starq-pm.settings.*) wins over these defaults."""

# [ADAPTED] role bindings — occupants are opaque ids, configured per floor
ROLES = {
    "O": {"occupants": [], "seats": 1},
    "E": {"occupants": [], "seats": 1},
    "V": {"occupants": [], "seats": 1},
    "F": {"occupants": [], "seats": 1},
}

# [ADAPTED] stage definitions; gates require F authorization (I-04)
STAGES = ["initiation", "planning", "execution", "closure"]

# [ADAPTED] tolerance values; mechanism [ESTABLISHED]. routing: authority role per class.
TOLERANCES = {
    "schedule": {"threshold": "sle_breach", "routing": "O"},
    "scope": {"threshold": "baseline_drift", "routing": "F"},
    "quality": {"threshold": "rework_cycles_exceeded", "routing": "O"},
    "capacity": {"threshold": "wip_breach", "routing": "O"},
    "cost_analogue": {"threshold": "resource_budget", "routing": "F"},
}

# [ADAPTED] ordinal risk criteria — no numeric probability claims
RISK_LIKELIHOOD = {1: "rare", 2: "unlikely", 3: "possible", 4: "likely", 5: "almost_certain"}
RISK_IMPACT = {1: "negligible", 2: "minor", 3: "moderate", 4: "major", 5: "severe"}
RISK_BANDS = [(1, 4, "low", "E"), (5, 9, "medium", "O"), (10, 14, "high", "O"), (15, 25, "critical", "F")]
AGENT_RISK_TAXONOMY = [
    "hallucinated_output", "context_loss_truncation", "model_provider_substitution",
    "capacity_exhaustion", "stale_forged_evidence", "concurrency_contention", "identity_confusion",
]

# [ESTABLISHED] ISO/IEC 25010:2023 characteristic vocabulary.
# LIMITATION: characteristic-level only; subcharacteristics require purchased full text.
QUALITY_CHARACTERISTICS_25010_2023 = [
    "functional suitability", "performance efficiency", "interaction capability",
    "reliability", "security", "maintainability", "flexibility", "safety", "compatibility",
]
LEGACY_25010_TERMS = ["usability", "portability"]  # rejected at validation

# [ADAPTED] quality profiles per deliverable type
QUALITY_PROFILES = {
    "software": {c: "target-set-at-gate" for c in QUALITY_CHARACTERISTICS_25010_2023},
    "document": {c: "target-set-at-gate" for c in QUALITY_CHARACTERISTICS_25010_2023},
}

# [ADAPTED] Definition of Done profiles; verifier-evidence item mandatory
DOD_PROFILES = {
    "software": ["all AC tests executed PASS", "evidence fresh + hash-identified", "verifier re-execution record"],
    "document": ["all AC checks PASS", "evidence fresh + hash-identified", "verifier inspection record"],
}

# [ADAPTED] WIP limits per seat — placeholders until host measurement + governance decision
WIP = {"default": 2}

# [ADAPTED] cadence + delta baseline policy
CADENCE = {"tick": "on_demand", "delta_baseline": "prior_report"}

# [EXPERIMENTAL] graduated autonomy — validation plan; never widens SDK capabilities
AUTONOMY = {"class": "supervised", "classes": ["supervised", "bounded", "delegated"]}

# [ADAPTED] evidence freshness max age seconds per class
EVIDENCE_MAX_AGE = {"test_output": 86400, "log": 86400, "screenshot": 3600, "report": 604800}

# [ADAPTED] flow estimation policy — SLE percentile, no human effort units
ESTIMATION = {"sle_percentile": 85, "min_sample": 10}

# [ADAPTED] bounded rework
REWORK_MAX_CYCLES = 3

# [ESTABLISHED] banned payload concepts
BANNED_FIELDS = ["velocity", "story_points", "man_hours", "effort_hours"]

# [ADAPTED] Definition of Workflow: states, start/finish points, legal transitions
DOW = {
    "states": ["draft", "ready", "dispatched", "executing", "blocked", "handed_off", "verifying", "rework", "accepted", "closed", "cancelled"],
    "started": "executing", "finished": ["accepted", "closed"],
    "transitions": [
        ["draft", "ready"], ["ready", "dispatched"], ["dispatched", "executing"],
        ["executing", "blocked"], ["blocked", "executing"], ["executing", "handed_off"],
        ["handed_off", "verifying"], ["verifying", "accepted"], ["verifying", "rework"],
        ["rework", "executing"], ["rework", "blocked"], ["accepted", "closed"],
        ["draft", "cancelled"], ["ready", "cancelled"], ["dispatched", "cancelled"],
        ["verifying", "handed_off"],
    ],
}

# [ADAPTED] blocker aging threshold seconds
BLOCKER_AGE_THRESHOLD_S = 86400

SCHEMA_VERSION = 1

DEFAULTS = {
    "roles": ROLES, "stages": STAGES, "tolerances": TOLERANCES,
    "risk_criteria": {"likelihood": RISK_LIKELIHOOD, "impact": RISK_IMPACT,
                      "bands": RISK_BANDS, "taxonomy": AGENT_RISK_TAXONOMY},
    "quality_profiles": QUALITY_PROFILES, "dod_profiles": DOD_PROFILES,
    "wip": WIP, "cadence": CADENCE, "autonomy": AUTONOMY,
    "evidence_max_age": EVIDENCE_MAX_AGE, "estimation": ESTIMATION,
    "rework_max_cycles": REWORK_MAX_CYCLES,
    "dow": DOW, "blocker_age_threshold_s": BLOCKER_AGE_THRESHOLD_S,
}
