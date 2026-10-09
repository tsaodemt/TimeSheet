# Approved-row immutability and direct-edit monitor (EPIC 07, S07.4)

Status 2026-10-09: **S07.4 BLOCKED** — `SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED`. The immutability rule is in force in the
deployed TS-SaveEntry (live LOCKED evidence from S07.2). SEC-Monitor detection is specified and tested offline. It is not
deployed: no approved operations-alert destination is configured.

| Artefact | Role |
|---|---|
| `tools/timesheet/entries.py` `ordinary_mutation_refusal` | Shared server-side invariant for every ordinary mutation of a stored entry |
| `tools/security/sec_monitor.py` | SEC-Monitor reference: classification, alert payload, dedupe, configured destination, SLA check |
| `tools/security/test_immutability_monitor.py` | IM01–IM26 |

## Rule

When the **stored** `EntryStatus` is `Approved`, ordinary business mutation is forbidden for every role and every client.
The service reads the row before it writes. Client values for status, owner, lock, role or scope are ignored. Check order
for one stored row: `NOT_FOUND` (missing or Deleted) → `FORBIDDEN` (not the caller's) → `LOCKED` (any non-Draft status) →
`CONFLICT` (ETag). Approved therefore wins over any client ETag, and the MERGE uses the stored ETag, so an approval that
lands between the read and the write gives `CONFLICT` with no write. The result code stays `LOCKED` (`MSG_LOCKED`); no new
code exists.

Approval state transitions are not ordinary mutations. TS-Approve (Draft → Approved) and TS-Unapprove (Approved → Draft,
S07.3 rules) keep their own guarded checks and are not blocked.

## Legacy parity matrix

| Operation | Draft | Approved | Legacy behaviour | Target behaviour |
|---|---|---|---|---|
| Edit | allowed after the confirm prompt | refused | Refused for every role with the message "Dữ liệu đã được phê duyệt"; nothing changes | TS-SaveEntry `LOCKED`, zero fields written (live in STAGING). Message text: see open point W-1 |
| Delete | removed after the confirm prompt | skipped | Multi-row delete removes the unlocked rows and **silently skips** the approved ones (no message) | `NOT_IMPLEMENTED_CURRENT_PATH`. The shared invariant returns `LOCKED` for an Approved row, so the row is kept and unchanged; soft delete only; the service has no Delete right |
| Reorder | position swapped | position swapped | ▲▼ swaps the row with its neighbour and saves. **There is no approval check.** Field values, including the lock, stay the same. The order has no business meaning, because the grid re-sorts by date when it loads | `NOT_IMPLEMENTED_CURRENT_PATH` (`SortOrder` is not provisioned). The backlog says an Approved row is refused. That differs from legacy: see open point R-1 |

Roles: the legacy edit and delete checks have no role exception, and neither does the target. Approve and unapprove follow
`docs/approval-capability-rules.md`.

### Open points (recorded, not chosen silently)

- **W-1 message wording.** The backlog and legacy wording is "Dữ liệu đã được phê duyệt". The current app catalogue
  shows an interim English text for `MSG_LOCKED`, because customer wording is still pending (R1-Q4). Only the text changes,
  never the code.
- **R-1 reorder of an Approved row.** Legacy allows it, because only the position changes. The backlog and the target
  rule ("Approved rows immutable") refuse it. This matters only when F-TS-15 is built. Default until the owner decides:
  the shared invariant (`LOCKED`).
- **D-1 delete feedback.** Legacy skips silently. The target batch contract returns a typed per-row result (`LOCKED`) and
  never fails silently (spec §11.7). The business outcome is the same: the row stays.

## SEC-Monitor (detection, not prevention)

- **Trigger:** TimesheetEntries item created or modified.
- **Trusted evidence:** SharePoint's own `Editor`, `Author`, `Modified` and version label. A write is trusted only if the
  editor of that version is the configured service identity (`ServiceAccountUpn`). For a new item, the author must also be
  the service identity. An unknown editor fails closed.
- **Never evidence:** row values that a direct editor can type (`ActorUpn`, `CorrelationId`, `SourceFlow`, any
  "trusted write" flag). No bypass marker exists.
- **Normal writes:** TS-SaveEntry, TS-Approve and TS-Unapprove all write through the service connection, so they are
  trusted and raise no alert.
- **Alert:** one per (list, item, version), so a re-delivered trigger is not alerted again. The alert carries only
  environment, event type, reason `OUT_OF_BAND_EDIT`, target list, item id, version, modified time, the editor
  identity, detection time and a reference. It carries no row content, tokens, headers or payloads.
- **No loop:** the monitor writes an AuditLog row (`SecurityMonitor`, operational sink, pending) and the alert, never
  TimesheetEntries, so it cannot trigger itself.
- **Destination:** configuration only (`OpsAlertRecipient`). If it is unset or unresolved, the run reports
  `SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED` and sends nothing. No recipient is ever assumed.
- **SLA:** alert ≤ 300 s after the change. This must be measured live (`sla_verdict`). It also depends on the trigger
  polling interval of the licence in use, which must leave headroom inside 300 s.
- **Residual risk:** an account with Full Control can overwrite `Editor` through the system-update APIs. Detecting that
  needs tenant audit (Purview), not this monitor.

## What unblocks S07.4

IT / owner decision **I-5**: who sends operations alerts and where they go. Service accounts may not use a mailbox
(NFR-SEC-06). Options already named: a shared mailbox, platform run-failure notification, or a separate identity. Once
decided, set `OpsAlertRecipient` (and the sender connection) for STAGING, deploy SEC-Monitor, and run LIVE-I4 / LIVE-I5
with a measured `ALERT_LATENCY_SECONDS`.
