# Security Policy — starq-pm

## Security model (what the plugin does and does not guarantee)

- **Fail-closed governance**: every mutating operation passes pre-mutation guards
  (role/RACI authorization, verifier independence, gate sequence, evidence freshness
  and integrity, WIP limits, tolerance exceptions). A failed guard refuses the
  operation and records an auditable refusal event; nothing is committed.
- **Tamper-evident audit, not tamper-proof storage**: the append-only SHA-256
  hash-chained event log detects modification, deletion, and reordering of history.
  It does NOT prevent a hostile local writer with filesystem access from rewriting
  the whole chain. Mitigation: export audit anchors (`starq_pm_audit anchor`) and
  custody the digest OUTSIDE agent-writable trees (owner-held storage, root-owned
  directory, or a separate trusted host); verify the live chain head against the
  custodied anchor at every stage gate. Where agents hold broad privilege-escalation
  rights (e.g. passwordless sudo), same-host root ownership is friction, not
  isolation — prefer an off-machine or offline anchor copy.
- **No secrets**: the plugin stores no credentials, tokens, or personal data; it
  requires no environment secrets and makes no network calls. Occupant ids are
  opaque configuration values, not identities.
- **Minimal attack surface**: Python stdlib only; zero third-party dependencies;
  zero declared capabilities; zero hooks, daemons, or scheduled jobs; no core
  runtime overrides. Evidence is hash-identified; exports pass a redaction hook.
- **Evidence integrity**: acceptance requires fresh, hash-identified evidence and
  independent verification; self-acceptance and verifier/executor identity overlap
  are refused. Stale or undated evidence fails closed.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.0   | Yes       |

## Reporting a vulnerability

Please report security issues **privately** via GitHub Security Advisories on this
repository (Security → Report a vulnerability). Do not open public issues for
security reports. Include reproduction steps, affected versions, and impact.
We aim to acknowledge reports within 7 days.

## Operational guidance

- Rehearse installs/upgrades on isolated profiles (`HERMES_HOME=<dir>`), never
  directly on production (OPERATIONS.md section 6).
- Back up the data root with writes quiesced; verify backup chains before relying
  on them (OPERATIONS.md section 1).
- Never hand-edit `events.jsonl`; a broken chain refuses writes by design. Recover
  from verified backups or use the documented checkpoint procedure for partial
  final lines only (OPERATIONS.md section 2).
