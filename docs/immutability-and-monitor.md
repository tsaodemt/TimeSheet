# Approved-row immutability and direct-edit monitor (EPIC 07, S07.4)

Status 2026-10-09: **S07.4 DONE (STAGING).** The immutability rule is in force in the deployed TS-SaveEntry, with the legacy
wording now live. SEC-Monitor is deployed and enabled on STAGING and proven live: a normal service write raised no
alert, and one controlled out-of-band edit raised exactly one alert, received in well under 300 s. The STAGING alert
sender/recipient follows decision I-5 for STAGING only. The production alert owner is still a future IT/customer decision.

| Artefact | Role |
|---|---|
| `tools/timesheet/entries.py` `ordinary_mutation_refusal` | Shared server-side invariant for every ordinary mutation of a stored entry |
| `tools/security/sec_monitor.py` | SEC-Monitor reference: classification, alert payload, dedupe, configured destination, SLA check, `scan_versions` (runtime model) |
| `tools/powerautomate/build_sec_monitor_flow.py` | SEC-Monitor flow template (site, service identity, recipient and environment are build parameters from environment configuration) |
| `tools/security/test_immutability_monitor.py` | IM01–IM32 (IM28–IM32: generated flow vs reference in the WDL simulator) |

## Rule

When the **stored** `EntryStatus` is `Approved`, ordinary business mutation is forbidden for every role and every client.
The service reads the row before it writes. Client values for status, owner, lock, role or scope are ignored. Check order
for one stored row: `NOT_FOUND` (missing or Deleted) → `FORBIDDEN` (not the caller's) → `LOCKED` (any non-Draft status) →
`CONFLICT` (ETag). Approved therefore wins over any client ETag, and the MERGE uses the stored ETag, so an approval that
lands between the read and the write gives `CONFLICT` with no write. The result code stays `LOCKED` (`MSG_LOCKED`); no new
code exists. The message is the legacy wording **"Dữ liệu đã được phê duyệt"** (W-1).

Approval state transitions are not ordinary mutations. TS-Approve (Draft → Approved) and TS-Unapprove (Approved → Draft,
S07.3 rules) keep their own guarded checks and are not blocked.

## Legacy parity matrix

| Operation | Draft | Approved | Legacy behaviour | Target behaviour |
|---|---|---|---|---|
| Edit | allowed after the confirm prompt | refused | Refused for every role with the message "Dữ liệu đã được phê duyệt"; nothing changes | TS-SaveEntry `LOCKED` / "Dữ liệu đã được phê duyệt", zero fields written (live in STAGING) |
| Delete | removed after the confirm prompt | skipped | Multi-row delete removes the unlocked rows and **silently skips** the approved ones (no message) | `NOT_IMPLEMENTED_CURRENT_PATH`. The future guarded delete returns a typed per-row `LOCKED` / "Dữ liệu đã được phê duyệt" for an Approved row and keeps it unchanged (D-1); soft delete only; the service has no Delete right |
| Reorder | position swapped | position swapped | ▲▼ swaps the row with its neighbour and saves. **There is no approval check.** Field values, including the lock, stay the same. The order has no business meaning, because the grid re-sorts by date when it loads | `NOT_IMPLEMENTED_CURRENT_PATH` (`SortOrder` is not provisioned). An Approved row is not reorderable: the future reorder returns `LOCKED` (R-1, signed deviation) |

Roles: the legacy edit and delete checks have no role exception, and neither does the target. Approve and unapprove follow
`docs/approval-capability-rules.md`.

### Decisions (project owner, 2026-10-09)

| ID | Decision | Effect |
|---|---|---|
| R-1 | `SIGNED_DEVIATION_TARGET_HARDENING` | Legacy allows moving an Approved row (its move has no lock check). The target refuses it with `LOCKED`, because the position has no business meaning and Approved rows are immutable. Reorder is not built now |
| W-1 | `MSG_LOCKED` = "Dữ liệu đã được phê duyệt" | Legacy wording replaces the interim English text. The code stays `LOCKED` and the response schema is unchanged |
| D-1 | `TARGET_TYPED_FEEDBACK_APPROVED` | Legacy skips Approved rows silently. The target never fails silently: it returns a per-row `LOCKED` with the legacy message. Business parity holds: the Approved row is not deleted |

## SEC-Monitor (detection, not prevention)

- **Schedule:** a Recurrence every 2 minutes scans the half-open window [scheduled − 2 min, scheduled). It does not use the
  SharePoint item trigger: on the Microsoft 365 seeded licence in use, that trigger polls on the low-performance tier,
  and the designer itself defaults a Recurrence to 5 minutes, which leaves no headroom inside the 300 s SLA. A 1-minute
  schedule would put about 1,440 runs a day against the licence's daily request allowance, so 2 minutes was chosen
  (about 720 runs a day, 3 to 4 requests each). Only standard connectors are used: SharePoint and Office 365 Outlook.
- **Trusted evidence:** for every item modified since the window start, the monitor reads the item's version history.
  Each version created in the window is classified by SharePoint's own `Editor` of that version. Trusted means the
  editor is the configured service identity; an unknown editor fails closed. A version lies in exactly one window, so it
  is alerted exactly once, with no stored state. An out-of-band version that a service write later overwrites is still seen.
- **Never evidence:** row values that a direct editor can type (`ActorUpn`, `CorrelationId`, `SourceFlow`, any
  "trusted write" flag). No bypass marker exists.
- **Normal writes:** TS-SaveEntry, TS-Approve and TS-Unapprove all write through the service connection, so they are
  trusted and raise no alert.
- **Alert:** one per (list, item, version), so a re-delivered trigger is not alerted again. The alert carries only
  environment, event type, reason `OUT_OF_BAND_EDIT`, target list, item id, version, modified time, the editor
  identity, detection time and a reference. It carries no row content, tokens, headers or payloads.
- **No loop, read only:** the deployed monitor only reads TimesheetEntries and sends mail. The run history and the mail
  are the record. It writes no AuditLog row: on STAGING it runs under the alert identity's connection, and a write by
  that identity into a protected list would itself be an out-of-band write. The `SecurityMonitor` audit event type stays
  registered but disabled until a service-owned monitor exists.
- **Destination:** configuration only (`OpsAlertRecipient`). If it is unset or unresolved, the run reports
  `SEC_MONITOR_ALERT_DESTINATION_UNCONFIGURED` and sends nothing. No recipient is ever assumed.
- **SLA:** alert ≤ 300 s after the change. Worst case by design: about 120 s window + run time + mail delivery. The
  measured live latency is recorded privately and was well under 300 s.
- **Residual risk:** an account with Full Control can overwrite `Editor` through the system-update APIs. Detecting that
  needs tenant audit (Purview), not this monitor.

## Live proof (STAGING, 2026-10-09)

| Check | Result |
|---|---|
| Normal service write (Canvas → TS-SaveEntry on an own Draft) | `OK`. The monitor read the new version as a service write. No alert over several windows |
| One controlled out-of-band edit (admin direct REST, synthetic fixture, `TEST_SETUP_OUT_OF_BAND_MUTATION`) | Exactly one `OUT_OF_BAND_EDIT` mail received; latency ≈ 109 s; no duplicate over the following windows |
| Save of an own Approved row through the published Canvas | `LOCKED`, "Dữ liệu đã được phê duyệt", nothing written |
| Security baseline (ordinary user / service / role assignments) | Unchanged vs the S07.3 post-check |
