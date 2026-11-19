# starq-pm OPERATIONS Guide

Operator procedures for the starq-pm plugin (v0.1.0). All commands assume a configured
profile; rehearsal/verification procedures use an ISOLATED profile (`HERMES_HOME=<dir>`),
never production. The plugin adds no daemons, hooks, or scheduled jobs — every operation
is on-demand.

## 1. Data root and backup

Data root: `<hermes home>/plugin-data/starq-pm/`
- `events.jsonl` — append-only SHA-256 hash-chained event log. THIS IS THE TRUTH.
- `data.db` — SQLite projections (WAL). Rebuildable cache; never the authority.
- `quarantine/` — chain-break alerts and partial-line recovery records.
- `exports/` — redacted exports and audit anchor digests.

Backup (consistent snapshot):
1. Quiesce writes (no agent operations against the plugin during copy).
2. `cp -a "<hermes home>/plugin-data/starq-pm" "<backup location>/starq-pm-$(date +%Y%m%d)"`
3. Verify the backup chain: run `chain_verify` against the backup copy (isolated profile
   pointed at the backup data root) or recompute hashes offline.
The install tree (`plugins/starq-pm/`) is replaceable code; back it up via the release
archive, not the data root. Plugin update/remove NEVER deletes the data root.

Restore:
1. Stop writes; copy the backed-up `plugin-data/starq-pm/` into the target profile's
   `<hermes home>/plugin-data/`.
2. Start the plugin; if projections are stale or corrupt, run rebuild (section 4).
3. `chain_verify` must return ok=true; compare head against the custodied anchor (section 3).

## 2. Chain verification

    hermes starq-pm chain_verify --occupant <orch-occupant>

Recomputes every hash from genesis: returns {ok, broken_seq, head{seq,hash}, events}.
- ok=true: chain intact.
- ok=false: tamper/corruption at broken_seq. Writes are REFUSED (F-05) and a
  `quarantine/chain_break-*.json` alert is written. Do not edit the chain by hand.
  Recovery: restore from a verified backup (section 1), or if the ONLY defect is a
  partial final line (crash mid-append), run the checkpoint procedure:
  `Store.checkpoint()` truncates to the last complete event, quarantines the partial
  bytes, and resumes. Earlier breaks are never auto-healed.
Tamper semantics: the chain DETECTS modification/deletion/reordering; it does not
PREVENT a hostile local writer from rewriting history. Anchor custody (section 3)
mitigates full-history rewrite. This limitation is documented, not hidden.

## 3. Audit anchor export + custody (concept)

    hermes starq-pm anchor --occupant <orch-occupant>

Exports `exports/anchor-<seq>.json` = {seq, hash, exported_ts} — a digest of the chain head.
Custody procedure (generic; adapt to your organization's trust model):
1. The owner (F role) designates a custody location OUTSIDE any agent-writable tree
   (e.g. owner-held storage, a root-owned directory, a printed digest, or a separate
   trusted host). Agents cannot designate it themselves. Where agents hold broad
   privilege-escalation rights (e.g. passwordless sudo), a root-owned directory on the
   same host is friction, not isolation — prefer an off-machine or offline copy.
2. The operator exports the anchor and delivers the digest to the custody location;
   the delivery receipt (path/hash/timestamp) is recorded as evidence.
3. Verification: compare the live chain head (`chain_verify`) against the custodied
   anchor. A mismatch at or below the anchored seq means history was rewritten after
   anchoring — escalate to the owner (stop/veto is always available).
4. Cadence: at every stage gate and at major milestones; set by governance.

## 4. Projection rebuild

Projections are a cache. If `data.db` is corrupt, missing, or schema-mismatched:
- The plugin degrades to read-only-empty views and flags degraded mode (F-12).
- Rebuild replays the chain: `Store.rebuild()` (drop projections, replay every event).
  Via a fresh PM instance on the data root, rebuild runs automatically on schema mismatch.
- Rebuild is idempotent (tested: double rebuild identical; wipe-and-rebuild restores
  board and states exactly). The chain is never modified by rebuild.
- After rebuild: `chain_verify` ok=true and board/metrics match pre-corruption values.

## 5. Troubleshooting (fail-closed refusal codes)

Every refusal is an audited chain event ({action, code, guard, reason}). Read refusals:
`hermes starq-pm evidence_lookup` / chain events type=refusal. The codes below are the
plugin's functional failure-mode taxonomy; requirement-level codes (FR-*/NFR-*) name
the specific contract guard that refused.

| Code | Meaning | Operator action |
|------|---------|-----------------|
| F-04 | store write failed (disk/lock) | free disk / resolve lock; retry; nothing was committed |
| F-05 | chain break detected | section 2 recovery; never hand-edit |
| F-06 | evidence unavailable/undated/stale/future-dated/hash-mismatch | re-capture fresh evidence; check clock; verify file integrity |
| F-08 | unknown occupant | configure role binding or run a governed substitution (F-authorized) |
| F-09 | tolerance breach without approved unexpired exception | raise exception; route to authority; expiry re-blocks automatically |
| F-10 | WIP limit reached | queue dispatch (pull); free capacity or governance-adjust limit |
| F-11 | schema/args invalid or unknown action | correct args; see tool schema |
| F-12 | projection corrupt | rebuild (section 4) |
| I-01 | self-acceptance attempt | acceptance by O/F only, never the executor |
| I-02 | independence conflict | substitute verifier occupant; never waive independence |
| I-03 | acceptance without verifier PASS | run independent verification first |
| I-04 | gate authorization without F role | obtain Founder (F) authorization; stop/veto always available |
| RACI-ROLE | role not authorized for action | check settings.roles and the action's RACI |
| EXP-04 | operation outside configured autonomy class | keep supervised class or govern the change |
| C-03 | velocity/human-effort field injected | remove banned fields (flow metrics only) |
| C-06 | self-report/model-judge-only evidence | provide re-executed/inspected evidence |
| FR-QA-07 | rework bound exceeded | escalate to O/F; no further auto-rework |

## 6. Isolated-profile rehearsal (never production)

    ISO=$(mktemp -d)
    mkdir -p "$ISO/plugins"
    cp -a <plugin-dir> "$ISO/plugins/starq-pm"
    HERMES_HOME="$ISO" hermes plugins validate "$ISO/plugins/starq-pm"
    HERMES_HOME="$ISO" hermes plugins doctor "$ISO/plugins/starq-pm"
    HERMES_HOME="$ISO" hermes plugins enable starq-pm
    # apply role settings AFTER enable (host enable rewrites config.yaml)
    HERMES_HOME="$ISO" hermes starq-pm chain_verify --occupant <orch-occupant>
    HERMES_HOME="$ISO" hermes plugins disable starq-pm
    HERMES_HOME="$ISO" hermes plugins remove starq-pm   # data root retained

No gateway restart is needed or performed; the production gateway does not serve
isolated homes. `hermes plugins install` takes catalog/Git/owner-repo only — local
install is `cp -a` into `$HERMES_HOME/plugins/`.
