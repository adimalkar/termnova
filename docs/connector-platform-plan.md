# Connector Platform and Workspace-App Plan

## Product role

Termnova should be an intelligence and control layer that connects to systems where contracts arrive, live, change, and turn into work. It should not require a customer to replace Drive, Microsoft 365, email, Slack/Teams, Jira, a CLM, procurement, CRM, or ERP.

“Connector” covers four product surfaces:

1. **Sources:** continuously ingest authorized documents, revisions, metadata, and contextual evidence.
2. **Signals:** receive events such as an email, file update, SLA incident, invoice, or vendor-risk change.
3. **Actions:** create reminders, tasks, approvals, calendar events, claims, and webhooks in the user's system of work.
4. **Embedded intelligence:** expose permission-aware Termnova search, effective terms, obligations, and actions inside other workspace or AI applications.

## High-value use cases

| External system | Input or trigger | Termnova value | Output/action |
| --- | --- | --- | --- |
| Google Drive / Shared Drives | New or changed file in selected folders | Version, diff, extract, find family, assess impact | Change review, owner alerts, source link |
| Gmail | Attachment or linked file in selected label/shared mailbox | Classify MSA/SOW/amendment, retain thread context, detect countersignature | Triage item, family suggestion, reply/task |
| OneDrive / SharePoint | Delta change in selected sites/libraries | Continuous repository synchronization and source ACL awareness | Review packet and freshness dashboard |
| Outlook | Message/attachment in authorized folder or shared mailbox | Intake, counterparty/thread correlation, evidence retention | Triage, obligation evidence, reminder |
| Slack / Teams | Contract link shared or Termnova command | Permission-aware unfurl, cited answer, deadline/owner lookup | Assign, acknowledge, request evidence, approve |
| Jira / work management | Linked issue, status, evidence attachment | Keep contractual duty and delivery work connected | Create/update issue, sync status and evidence |
| Calendar | Effective/expiry/notice/recurring due date | Prevent missed windows and show governing evidence | Managed event plus updates/cancellation |
| Generic webhook/API | Contract, change, control, incident, or business event | Trigger obligation/family/exposure evaluation | Signed callback and delivery log |
| CRM | Vendor/customer/account/opportunity context | Map commercial owner, segment, value, and renewal motion | Exposure and renewal alerts in account view |
| Procurement/ERP/AP | PO, invoice, spend, price, supplier record | Compare actual charges/commitments with effective terms | Leakage/credit finding and approval workflow |
| CLM/e-signature | Executed envelope, status, metadata, repository document | Complement authoring/repository with post-signature control | Version/family/obligation updates |
| Monitoring/security tools | SLA incident, certificate, risk finding | Match event to commitment and calculate remedy/control status | Claim/evidence pack and remediation task |

## Connector catalog and sequence

### Wave 1 — Contract sources

#### Google Drive and Shared Drives

- User or administrator connects an account and selects specific folders/shared drives through a picker.
- Initial backfill inventories metadata first, presents scope/volume/duplicates, then fetches authorized content.
- Change notifications wake a durable sync job; the job consumes the Drive change log and advances a stored page token only after processing is durable.
- Stable file IDs, revisions, ETags, hashes, moves, renames, deletions, and permission changes map into logical document/version events.
- Periodic reconciliation checks the cursor and samples content hashes.

#### Gmail

- Restrict intake to selected labels, user mailboxes, or approved shared mailboxes rather than mirroring all mail.
- Watch notifications provide a history cursor; Termnova fetches incremental history and renews watches before expiration.
- Process authorized attachments and Drive links. Store only necessary email body/thread context under retention policy.
- Correlate amendments, order forms, countersignatures, and fulfillment evidence from thread IDs and explicit references.
- Deduplicate an attachment already ingested from Drive while retaining both source/evidence links.

### Wave 2 — Microsoft 365

#### OneDrive and SharePoint

- Support administrator-approved sites/libraries and user-selected folders.
- Use Microsoft Graph delta tokens and stable item IDs; paths are mutable metadata.
- Use change notifications as wake-ups and delta reconciliation as the source of truth.
- Mirror access semantics or apply an explicitly configured snapshot policy; permission removal must be visible promptly.

#### Outlook and Teams

- Limit Outlook intake by folder/shared mailbox and use notifications plus incremental queries.
- Deliver Teams cards for review, assignment, deadline, and evidence actions after identity mapping.
- Do not expose a contract in a channel merely because a Termnova user pasted its URL; recheck the viewing user's Termnova permission.

### Wave 3 — Work and action systems

- Slack/Teams notifications, link unfurls, commands, and approval actions.
- Google/Microsoft calendar events owned by a Termnova-managed calendar or clearly identified service principal.
- Jira first for task synchronization, then ServiceNow/Asana/other systems based on customer demand.
- Signed generic outbound webhooks and an API for customers with internal orchestration.

### Wave 4 — Commercial and governance systems

- Salesforce/HubSpot for account, owner, opportunity, and renewal context.
- Coupa/SAP/NetSuite and AP tools for suppliers, POs, invoices, spend, credits, and price validation.
- CLM/e-signature repositories for executed-status and document metadata.
- Security, GRC, uptime, and incident platforms for SLA and vendor-control evidence.

## Embedded Termnova connector

After core tenancy and authorization are proven, expose Termnova itself to approved workspace and AI clients through scoped APIs and, where useful, an MCP server.

Initial read tools:

- Search authorized contracts and return source-backed passages.
- Get the effective term for a family, scope, and as-of date.
- List the user's upcoming, overdue, or unowned obligations.
- Explain an exposure calculation with source provisions.
- Retrieve connector freshness and unresolved change/conflict state.

Controlled write tools:

- Assign/acknowledge an obligation.
- Request or attach evidence through a pre-authorized link.
- Create a review task or draft an action.
- Approve only when the user has the required Termnova role and the client supports explicit confirmation.

Every tool call is user-delegated or service-account scoped, tenant-bound, rate-limited, audited, and citation-bearing. Bulk raw-document export is excluded by default.

## Common connector architecture

### Core records

`ConnectorDefinition`

- Provider, capabilities, supported auth modes, requested scopes, webhook support, rate-limit policy, and version.

`IntegrationConnection`

- Organization, authorized principal/admin, provider account/tenant, encrypted credential reference, state, consent time, last health check, and revocation state.

`SyncScope`

- Connection plus selected drive/folder/site/library/mailbox/label/project/calendar and organization destination workspace.
- Include/exclude rules, file types, size limits, retention, ACL mode, and initial-sync checkpoint.

`ExternalObject`

- Stable provider object ID, source container, URL, current metadata, ACL snapshot/hash, logical document/evidence mapping, and tombstone state.

`SyncCursor` and `WebhookSubscription`

- Provider cursor/token, subscription resource, expiry, renewal state, last durable advancement, and reconciliation time.

`ConnectorEvent`

- Immutable normalized envelope with provider event ID, organization, connection, object, event type, observed time, correlation/causation IDs, processing state, and dedup key.

`ActionDelivery`

- Destination, target object, payload version, idempotency key, attempts, response identifiers, status, error category, and audit actor.

### Connector interface

Each provider adapter implements a common contract:

- `authorize`, `refresh`, `revoke`, and `validate_scopes`.
- `discover_scopes` and `estimate_backfill`.
- `backfill`, `poll_changes`, `handle_webhook`, and `reconcile`.
- `fetch_metadata`, `fetch_content`, `fetch_revision`, and `fetch_permissions`.
- `map_identity`, `map_object`, and `map_event`.
- `deliver_action` and `check_health` where applicable.

Provider payloads remain available in a tightly retained diagnostic store, while domain services consume a versioned normalized event schema.

## Event and synchronization guarantees

- Webhooks are hints, not the sole source of truth. Acknowledge quickly, persist, enqueue, then consume provider change/delta feeds.
- Use `(organization_id, connection_id, provider_event_id)` and provider object/revision IDs for idempotency.
- Advance a cursor only after all events through that point are durably recorded. Processing can then retry independently.
- Expect duplicate, delayed, batched, and out-of-order events. Use source modified/revision values and optimistic document-version promotion.
- Run scheduled reconciliation, watch/subscription renewal, token refresh, permission-drift detection, and tombstone scans.
- Apply per-provider and per-tenant rate budgets, jittered retry, circuit breakers, backpressure, dead-letter queues, and replay.
- Keep a connector health state: `healthy`, `syncing`, `degraded`, `reauthorization_required`, `rate_limited`, `paused`, or `revoked`.

## Security and administration

- Request the narrowest scopes that support the selected capability; separate read-source consent from write-action consent.
- Support user-delegated and administrator-installed connections with clear ownership and offboarding behavior.
- Encrypt refresh tokens using a managed key service; never write tokens or document bodies to logs.
- Validate webhook authenticity, resource identity, replay window, and organization binding before enqueueing.
- Re-evaluate permissions at access time for live-source ACL mode. Clearly document snapshot/retention behavior where legal-hold evidence must outlive source access.
- Map provider identities to verified Termnova memberships before interactive actions.
- Expose connection scope, granted permissions, recent activity, data retained, token age, and revoke/delete controls to administrators.
- Add data-loss prevention hooks, configurable content exclusions, maximum file sizes, and region-aware routing.
- Complete provider verification/security-assessment requirements before requesting broad or restricted production scopes.

## Connector center UX

Administrators need one operational page with:

- Available connectors, capabilities, requested scopes, owner, and installation type.
- Scope picker and backfill estimate before sync.
- Last webhook, cursor advancement, successful object, reconciliation, token refresh, and action delivery.
- Queue depth, lag, rate-limit state, errors grouped by actionable cause, and affected documents.
- Pause/resume, reconnect, change scope, resync one object, reconcile scope, replay dead letter, revoke, and delete retained connector data.
- Per-connector audit export and test action.

Users should see source/freshness state on the document and family, not only in an admin console.

## Actions and conflict policy

- Termnova remains the system of record for contractual obligation state unless a connection explicitly chooses an external system as workflow authority.
- Field ownership is configured per integration. Avoid unrestricted last-write-wins synchronization.
- External edits become audited proposals or mapped state changes; external deletion cannot erase Termnova history.
- Idempotent upsert keys prevent duplicate Jira issues, calendar events, or Slack/Teams notifications.
- Store external object IDs and URLs for round-trip navigation.
- Recheck authorization before sensitive external actions and require explicit confirmation for approvals, waivers, or terminations.

## Developer platform

- Versioned REST API with organization-scoped OAuth clients/service accounts.
- Signed inbound/outbound webhooks with event schemas, replay protection, delivery logs, and sandbox endpoints.
- Connector SDK, contract tests, provider fixtures, local webhook tunnel guidance, and certification checklist.
- Marketplace packages only after least-privilege scopes, branding, privacy disclosures, installation/offboarding, and support runbooks are complete.
- OpenAPI and MCP schemas derive from the same authorization-aware application services to avoid inconsistent business rules.

## Evaluation and launch gates

- Backfill correctness for creates, updates, moves, renames, deletions, duplicates, permissions, and revisions.
- No lost events under duplicate, delayed, out-of-order, expired subscription, revoked token, rate limit, worker crash, and provider outage tests.
- Reconciliation reports zero unexplained drift on the pilot corpus.
- Source permission removal meets the agreed propagation SLO.
- Action delivery is idempotent and its audit trail round-trips to the external object.
- Connector freshness and errors are understandable and recoverable without engineering database access.
- Security review confirms scope minimization, credential handling, log redaction, deletion, and tenant binding.

## External design references

- Google Drive supports Shared Drive-aware change watches through [`changes.watch`](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/watch) and documents [change logs and revisions](https://developers.google.com/workspace/drive/api/guides/change-overview).
- Gmail push delivery uses `watch`, Pub/Sub, and incremental history; subscriptions expire and must be renewed. See the [Gmail push notification guide](https://developers.google.com/workspace/gmail/api/guides/push).
- Microsoft Graph provides [Drive item delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0) for OneDrive/SharePoint changes and documents [webhook delivery and lifecycle handling](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks).
- Slack exposes [`link_shared`](https://api.slack.com/events/link_shared) for domain-aware unfurls and [`file_shared`](https://api.slack.com/events/file_shared) for file events.
- Jira Cloud supports [dynamic webhooks](https://developer.atlassian.com/cloud/jira/platform/rest/v2/api-group-webhooks/) for installed applications.

## Non-goals

- Full bidirectional synchronization with every provider in the first release.
- Broad mailbox/drive access where a folder, label, site, or shared mailbox is sufficient.
- Using Slack/Teams as a replacement contract repository.
- Letting an external connector bypass Termnova authorization or evidence requirements.
- Promising exactly-once provider delivery; Termnova provides idempotent effects and reconciliation over at-least-once signals.
