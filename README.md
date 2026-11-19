# starq-pm

**Software project management for Hermes agent floors** — stage-gated lifecycle,
independent verification, flow measurement, and a tamper-evident audit chain.
Identity-agnostic. Python stdlib only. Zero third-party dependencies.

Version 0.1.0 · Apache-2.0 · Starq Technologies Pvt Ltd · Linux (tested)

## What it does

starq-pm turns a Hermes agent floor into a governed software project organization:

- **Stage-gated lifecycle** — charter → requirements → planning → execution →
  verification → closure, with stage gates that require explicit authorization.
- **Governance enforced in code, before any mutation** — roles as configuration
  (O = orchestrator, E = executor, V = verifier, F = Founder/owner), RACI-checked
  actions, independent verification (no self-acceptance), bounded rework,
  tolerance exceptions with expiry, and fail-closed refusal modes.
- **Tamper-evident audit** — every operation is appended to a SHA-256 hash-chained
  event log (the source of truth). SQLite projections are a rebuildable query cache.
  Refusals are recorded as auditable events, not silent failures.
- **Flow measurement** — 13 metrics (throughput, cycle time, WIP compliance, item
  age, SLE attainment, first-pass verification yield, rework rate, milestone
  variance, evidence completeness, fail-closed incidence, decision-log
  completeness, exception resolution time, lessons capture). No velocity, no
  human-effort units.
- **Identity-agnostic** — occupants are opaque ids bound to roles by configuration.
  Any agent or human can fill any seat; nothing depends on a particular agent
  identity or infrastructure.

## Requirements

- Hermes Agent (tested with v0.23.2; standard plugin SDK surface).
- Python 3 standard library only — no third-party packages, no capabilities,
  no hooks, no daemons, no network access, no secrets.
- Tested platform: **Linux** (Hermes v0.23.2, Python 3.14). Windows and macOS are
  untested; no support is claimed for them.

## Installation

From the official repository (plugin sits at the repo root):

    hermes plugins install Starq-Technologies-Pvt-Ltd/starq-pm

Local alternative (from a checkout or the release archive):

    cp -a starq-pm "$HERMES_HOME/plugins/starq-pm"
    hermes plugins validate "$HERMES_HOME/plugins/starq-pm"
    hermes plugins doctor "$HERMES_HOME/plugins/starq-pm"
    hermes plugins enable starq-pm

The v0.1.0 GitHub Release asset `starq-pm-0.1.0.zip` is the **original verified
archive** (SHA-256 `0f156a51eb1ee19a4aa58ec8b573a5fd4ce004b1fdd6a7551b027b1b11f51e8f`).
The repository distribution is distinct: universalized documentation, author
attribution, and comment/docstring sanitization only — executable code and runtime
behavior are identical (see RELEASE-NOTES.md).

## First-run configuration (AFTER enable)

The host `enable` step rewrites `config.yaml`, so apply plugin settings **after**
enabling. Bind roles under `plugins.entries.starq-pm.settings.roles`:

    plugins:
      entries:
        starq-pm:
          settings:
            roles:
              O: {occupants: [orchestrator], seats: 1}
              E: {occupants: [executor], seats: 2}
              V: {occupants: [verifier], seats: 1}
              F: {occupants: [owner], seats: 1}

Unbound occupants are refused fail-closed (`F-08`). Durable role changes go through
the `role_bind` action (persisted in the event chain); `config.yaml` is a load-time
overlay. All 14 configuration keys: `roles`, `stages`, `tolerances`, `risk_criteria`,
`quality_profiles`, `dod_profiles`, `wip`, `cadence`, `autonomy`, `evidence_max_age`,
`estimation`, `rework_max_cycles`, `dow`, `blocker_age_threshold_s`. Normative
configuration writes require a classification tag (`[ESTABLISHED]`, `[ADAPTED]`,
`[EXPERIMENTAL]`) and produce a decision record.

## Usage

Three surfaces, same actions:

- **12 model-facing tools**: `starq_pm_initiate`, `starq_pm_requirements`,
  `starq_pm_plan`, `starq_pm_execute`, `starq_pm_verify`, `starq_pm_gates`,
  `starq_pm_change`, `starq_pm_risk`, `starq_pm_report`, `starq_pm_close`,
  `starq_pm_config`, `starq_pm_audit`. Each takes `occupant`, `action`, `args`.
- **CLI**: `hermes starq-pm <action> --occupant ID [--args JSON] [--project ID]`
- **Slash**: `/starq-pm <action> [JSON args]`

Example workflow (CLI):

    hermes starq-pm charter_create --occupant orchestrator --args '{"project_id":"PRJ-1","authorization_ref":"AUTH-1","objectives":["deliver v1"],"success_criteria":["all tests green"]}'
    hermes starq-pm justification_record --occupant orchestrator --args '{"project_id":"PRJ-1","statement":"viable","review_decision":"continue"}'
    hermes starq-pm charter_authorize --occupant owner --args '{"charter_id":"CH-001"}'
    hermes starq-pm deliverable_decompose --occupant orchestrator --args '{"project_id":"PRJ-1","name":"core","type":"software"}'
    hermes starq-pm wp_create --occupant orchestrator --args '{"project_id":"PRJ-1","title":"build","deliverable_id":"DLV-001"}'
    hermes starq-pm ac_set --occupant orchestrator --args '{"wp_id":"WP-001","text":"criterion","test_id":"T-1","requirement_ids":["R-1"],"dod_item":"tests pass","predicate":"given build when tested then green"}'
    hermes starq-pm dispatch --occupant orchestrator --args '{"wp_id":"WP-001","to_occupant":"executor"}'
    hermes starq-pm status_record --occupant executor --args '{"wp_id":"WP-001","note":"start"}'
    hermes starq-pm handoff --occupant executor --args '{"wp_id":"WP-001","artifacts":[{"path":"/tmp/out.bin","sha256":"<64-hex>"}]}'
    hermes starq-pm evidence_attach --occupant verifier --args '{"wp_id":"WP-001","path":"/tmp/out.bin","sha256":"<64-hex>","captured_ts":"2026-01-01T00:00:00+00:00","class":"test_output"}'
    hermes starq-pm verify_run --occupant verifier --args '{"wp_id":"WP-001","test_ids":["T-1"],"verdicts":{"T-1":"PASS"}}'
    hermes starq-pm dod_check --occupant verifier --args '{"wp_id":"WP-001"}'
    hermes starq-pm acceptance_decide --occupant orchestrator --args '{"wp_id":"WP-001","decision":"accept"}'
    hermes starq-pm board --occupant orchestrator --args '{"project_id":"PRJ-1"}'
    hermes starq-pm chain_verify --occupant orchestrator --args '{}'

Verification is independent: the verifier must not be the executor, and acceptance
requires fresh, hash-identified evidence plus a Definition-of-Done pass. CLI
commands print their JSON result to stdout.

## Architecture

- **8 domain services**: initiation, requirements, planning, execution, quality,
  risk, monitoring, closure — pure event-emitting handlers.
- **Dual store**: append-only hash-chained JSONL event log (truth) + rebuildable
  SQLite projections (boards, reports, metrics). Chain-first writes: if the chain
  write fails, nothing is committed.
- **Governance engine**: pre-mutation guards (role/RACI, independence, gates,
  freshness, WIP, tolerances) with auditable refusal events.
- **Deterministic reports**: same input events + same clock ⇒ identical content
  hashes. Reports append their own events, so consecutive runs legitimately differ
  in metrics that count operations; determinism is defined on frozen inputs.

## Measurement notes

- Metrics with no samples report `null` / `{}` — **UNKNOWN, never fabricated zero**.
- Cycle-time and age metrics are computed from recorded event timestamps. If you
  operate with an injected/simulated clock, values reflect that synthetic timeline;
  wall-clock latency is a separate measurement.
- Decision-log completeness (MT-11) is the fraction of governance operations
  carrying a decision reference, in [0, 1].

## Limitations (honest)

- **O(n) chain verification per append** (O(n²) lifetime): append latency grows with
  chain length — measured ~400 ms median at ~1,300 events under 8-thread contention
  on a Linux test host (~11 ms sequential). Upgrade path: checkpointed/incremental
  verification. Single-process append lock.
- **Tamper detection, not prevention**: the hash chain detects history rewrite; it
  cannot prevent a hostile local rewrite. Mitigation: anchor custody (OPERATIONS.md).
- **No evidence supersede/retract action yet**: stale evidence permanently blocks
  work-package acceptance (fail-closed by design). A governed supersede action is
  deferred.
- **Cancelled work-package state** is defined but has no reaching action yet (deferred).
- **Deferred features**: feasibility assessment, timeboxed planning, receipt
  correlation, verification/validation distinction, safety assessment, risk-review
  cadence, benefits review, critical path, SOP-encoded steps, extended quality
  measurement, advanced risk techniques, earned value (conflicts with the
  no-velocity stance).
- ISO/IEC 25010:2023 quality fixtures operate at characteristic level (the full
  standard text is paywalled).

## Rollback

    hermes plugins disable starq-pm
    hermes plugins remove starq-pm

The data root survives removal: `<hermes home>/plugin-data/starq-pm/`. Explicit
cleanup is a separate, deliberate act. Reinstalling restores service over the same
event chain (update-survival is tested).

## Security

See SECURITY.md. No secrets are stored; no credentials are required.

## License

Apache License 2.0 — see LICENSE. Copyright 2026 Starq Technologies Pvt Ltd.
