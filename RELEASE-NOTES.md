# starq-pm v0.1.0 — Release Notes

First public release · 2026-11-19 · Starq Technologies Pvt Ltd · Apache-2.0

## What's in this release

A complete, governed software project management plugin for Hermes agent floors:

- 12 action-based model tools, CLI (`hermes starq-pm`), and slash (`/starq-pm`) surfaces.
- 8 domain services: initiation, requirements, planning, execution, quality, risk,
  monitoring, closure.
- Stage-gated lifecycle with explicit Founder (F role) authorization; independent
  verification at occupant level (no self-acceptance); bounded rework; tolerance
  exceptions with automatic expiry re-blocking.
- Dual store: append-only SHA-256 hash-chained event log (source of truth) +
  rebuildable SQLite projections; every refusal recorded as an auditable event;
  checkpoint recovery for partial final lines; audit anchor export for custody.
- Flow measurement MT-01..13 — no velocity, no human-effort units; deterministic
  reports on frozen inputs.
- Identity-agnostic roles-as-configuration (O/E/V/F); transport separation;
  stdlib only; zero capabilities; zero hooks/daemons; zero third-party dependencies.

## Verification summary

- Full test suite: 264 tests = 219 passing (requirement tests, negative controls,
  robustness/fuzz, chain-edge and rebuild-idempotence tests) + 45 deferred-feature
  skips with reasons; 0 failures; warning-clean under `-W error::ResourceWarning`.
  The suite was re-run against this repository's code and is green.
- Independent verification of the release candidate: install/enable/CLI smoke,
  update-survival, disable/remove with data retention, all on isolated profiles.
- Managed-load stress test on Linux: a 1,700+ event chain built through the plugin's
  own tool surface — sequential and 8-thread concurrent appends, full work-package
  lifecycles across 4 executor seats with WIP limits, failure injections (tamper,
  stale evidence, expired exceptions, self-acceptance attempts) all observed as
  correct fail-closed refusals; projection rebuild idempotent; no host instability.
- Measured performance: append latency ~11 ms median sequential; ~400 ms median at
  ~1,300 events under 8-thread contention (documented O(n) ceiling, upgrade path
  noted below). Idle footprint: millisecond-scale init, single-digit MB data root
  at ~1,500 events.

## Official archive vs repository distribution

- The GitHub Release asset `starq-pm-0.1.0.zip` is the **original verified archive**,
  byte-identical to the accepted release:
  SHA-256 `0f156a51eb1ee19a4aa58ec8b573a5fd4ce004b1fdd6a7551b027b1b11f51e8f`
  (22 files, no bytecode).
- This repository is the **universal distribution**: plugin at repo root for
  `hermes plugins install Starq-Technologies-Pvt-Ltd/starq-pm`, with universalized
  documentation, author attribution, and comment/docstring sanitization (internal
  design-document citations removed from comments only). Executable code — including
  all runtime string literals — is hash-identical to the verified archive once
  comments/docstrings are stripped; runtime behavior is unchanged (suite green).

## Known limitations

1. O(n) chain verification per append (O(n²) lifetime); single-process append lock.
   Upgrade path: checkpointed/incremental verification.
2. Hash chain is tamper-EVIDENT, not tamper-proof against a hostile local writer;
   mitigate with anchor custody outside agent-writable trees (OPERATIONS.md section 3).
3. No evidence supersede/retract action yet: stale evidence permanently blocks
   work-package acceptance (fail-closed by design); governed supersede is deferred.
4. The cancelled work-package state is defined but has no reaching action yet.
5. Metrics with no samples report UNKNOWN (null/{}), never fabricated zeros.
   Cycle-time/age metrics reflect recorded timestamps — an injected/simulated clock
   produces a synthetic timeline; wall-clock latency is measured separately.
6. Consecutive report runs legitimately differ in operation-counting metrics because
   each report appends its own event; determinism holds on frozen inputs.
7. ISO/IEC 25010:2023 fixtures at characteristic level (full standard text paywalled).
8. Deferred features: feasibility assessment, timeboxes, receipt correlation,
   verification/validation distinction, safety assessment, risk-review cadence,
   benefits review, critical path, SOP steps, extended quality measurement, advanced
   risk techniques, earned value (conflicts with the no-velocity stance).

## Standards grounding

Tailored from current software lifecycle, quality, and management standards —
ISO/IEC/IEEE 12207:2026, ISO/IEC 25010:2023, ISO 21502:2020, ISO 31000:2018,
PMBOK 8th ed., PRINCE2 7, Kanban Guide 2025, Scrum Guide 2020 — adopted selectively,
not wholesale. Paywalled full texts were grounded via official previews/abstracts;
the characteristic-level limitation is marked above.

## Platform compatibility

Tested: Linux (Hermes v0.23.2, Python 3.14). Windows and macOS are untested;
no support is claimed for them.

## Install / rollback

See README.md (install + first-run configuration AFTER enable) and OPERATIONS.md
(backup/restore, chain verification, anchor custody, rebuild, refusal-code table,
isolated rehearsal). Rollback: `hermes plugins disable starq-pm` then
`hermes plugins remove starq-pm`; the data root is retained; explicit cleanup is a
separate deliberate act.
