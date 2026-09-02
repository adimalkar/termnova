# Termnova Enterprise Product Roadmap

## Product position

Termnova should enter the market as a **Vendor Contract Obligation and Exposure Control Tower** for mid-market legal operations, procurement, finance, security, and vendor-management teams.

The product promise is:

> Connect the places where agreements arrive and change. Termnova identifies what must happen, who owns it, when it is due, what money or risk is involved, which provision is currently effective, and the source evidence behind every conclusion through completion.

Document chat remains a supporting interface. The product's primary outcomes are preventing missed obligations, recovering contractual value, maintaining an accurate view as documents change, and proving completion.

## Product principles

1. **The original is authoritative.** Every answer, field, task, calculation, and translated view resolves to an immutable source version, page, clause, and character span.
2. **A contract is a living record.** New revisions never overwrite old ones. Changes trigger a scoped impact analysis across obligations, families, workflows, and exposure.
3. **Uncertainty is visible.** Termnova may suggest relationships or effective terms, but ambiguous legal effects go to a human reviewer instead of being silently resolved.
4. **Corrections improve quality.** Reviewer decisions are versioned organization data and become evaluation examples; they do not directly train a shared model.
5. **Permissions follow the source.** Tenant isolation, source ACLs, least-privilege connector scopes, and auditable actions are product behavior, not deployment options.
6. **Language does not weaken evidence.** Users can search and work in their preferred language, while citations remain anchored to the original-language text.
7. **Value must be measurable.** The product tracks money protected, recovered, avoided, or still at risk with explainable calculations.

## Delivery sequence

### Phase 0 — Trust, tenancy, and operational foundation

**Outcome:** a production-safe platform on which every later workflow can be trusted.

#### Platform and security

- Complete indexed hybrid retrieval, durable object storage, asynchronous ingestion, bounded model calls, deterministic cache keys, and deployment health checks.
- Add organizations, workspaces, tenant IDs on every stored and derived artifact, PostgreSQL row-level security, and automated cross-tenant isolation tests.
- Add OIDC first, followed by SAML, SCIM, group-to-role mapping, service accounts, and roles for administrator, legal reviewer, procurement reviewer, obligation owner, auditor, and read-only user.
- Replace user-controlled identity headers with verified actor context. Enforce authorization at both route and data-access layers.
- Add encrypted connector credentials, configurable data/model routing, customer-managed retention, deletion workflows, legal holds, and regional storage controls.
- Store originals, rendered pages, OCR output, translations, and evidence in versioned object storage. Add malware scanning, MIME validation, upload quarantine, and signed download URLs.

#### Reliability and AI governance

- Add idempotent jobs, an outbox/inbox event pattern, retry budgets, dead-letter queues, replay tools, and a visible ingestion/synchronization status timeline.
- Version prompts, schemas, models, OCR engines, parsers, and extraction runs. Persist the exact processing snapshot behind every result.
- Establish gold evaluation sets by contract type, obligation type, language, scan quality, and risk tier. Measure extraction precision/recall, citation correctness, retrieval recall, and false-negative rate.
- Add per-organization usage controls, concurrency limits, cost budgets, rate limits, tracing, redacted logs, and SLO dashboards.

#### Foundations added for later phases

- Introduce logical documents, immutable document versions, stable clause identities, external-source identities, and normalized language tags.
- Create the connector control plane: OAuth connections, scopes, sync cursors, webhook subscriptions, event ledger, and health state. Provider connectors launch in Phase 1.
- Create a language service boundary for detection, OCR selection, translation, multilingual embeddings, and reviewer-language routing.

#### Exit gate

- Tenant-isolation, restore, delete, legal-hold, token-revocation, job-replay, and source-permission tests pass.
- Extraction and citation benchmarks are published internally with release thresholds and regression gates.
- No processing result can exist without an organization, source version, processing snapshot, and audit actor.

### Phase 1 — Living-document intake, extraction, and verification

**Outcome:** connect real contract sources and turn continuously changing documents into verified, source-backed facts.

#### Continuous intake and version control

- Launch secure upload, bulk ZIP import, and a Google Drive/Shared Drive connector; add Gmail scoped-label intake next. OneDrive/SharePoint and Outlook follow once the connector substrate is proven.
- Represent one business document as a logical record with immutable versions. Detect exact duplicates, renamed/moved files, source revisions, replacement files, and cross-source duplicates without collapsing records across tenants.
- Process provider webhooks quickly into a durable event queue, then use change cursors and periodic reconciliation to recover missed, duplicated, or out-of-order events.
- Compare versions at paragraph and clause level. Classify changes as metadata-only, formatting/no-op, minor wording, material clause change, signature/status change, or whole-document replacement.
- Reprocess only changed clauses plus dependent context. Atomically promote a completed version; keep the last valid version active while a new version is processing or quarantined.
- Show a document activity feed, side-by-side/redline comparison, changed-term summary, processing status, sync health, and downstream impact preview.

#### Structured contract intelligence

- Extract contract identity, parties, roles, contract type, effective/expiration dates, value/currency, governing law, and referenced agreements.
- Extract typed renewals, notice windows, payment milestones, price escalators, SLAs, service credits, security commitments, reporting duties, termination rights, audit rights, and customer/supplier obligations.
- Store every field with logical document ID, exact document version, page, clause, source span, extractor version, confidence, and verification status.
- Add deterministic validation for dates, currencies, percentages, notice arithmetic, inconsistent party roles, and contradictions between extracted fields.

#### Human verification and language support

- Route low-confidence, high-impact, newly changed, contradictory, and unsupported fields to the existing inbox for approve, correct, reject, duplicate, and defer actions.
- Preserve reviewer corrections as organization-scoped labeled examples and evaluation cases. Add sampling of high-confidence fields to detect silent model drift.
- Detect language at document, page, and clause level using BCP 47 tags. Preserve original text as authoritative and create optional, separately versioned translations.
- Support cross-language search and answers, mixed-language documents, language-aware OCR, locale-aware date/number parsing, terminology glossaries, and bilingual evidence review.
- Display citations in the original language with an optional translated view and translation confidence; never present machine translation as the executed legal text.

#### Real-contract readiness

- Seed a read-only demo organization with lawfully licensed, attributable real public contracts. Keep demo, evaluation, synthetic, and customer data physically and logically separated.
- Add a corpus manifest recording source URL, publisher, license, attribution, hash, contract type, language, extraction permission, and ingestion date.
- Provide a customer onboarding flow for folder selection, metadata mapping, duplicate preview, quarantine review, processing estimates, and sampled acceptance checks.

#### Exit gate

- Agreed precision and recall targets are met per obligation type, language, scan-quality tier, and monetary-risk tier.
- A source change is detected, versioned, diffed, re-extracted, reviewed, and promoted without losing history or showing partially updated results.
- No extracted fact can be displayed without exact evidence from an immutable original version.

### Phase 2 — Ownership, fulfillment, and value recovery

**Outcome:** convert verified terms into accountable work and auditable commercial outcomes.

#### Obligation operations

- Add accountable owner, contributors, due date, recurrence rule, lead time, escalation policy, business unit, state, comments, tags, and evidence requirements.
- Distinguish obligations, entitlements, options, conditions precedent, recurring controls, one-time milestones, and event-triggered duties.
- Add templates by obligation type, bulk assignment rules, workload balancing, segregation-of-duties approvals, delegation/absence handling, and owner acknowledgements.
- Add calendar views, saved queues, daily/weekly digests, overdue escalations, approval queues, and portfolio-level owner coverage.

#### Fulfillment and evidence

- Attach invoices, reports, security certificates, service reports, emails, tickets, approvals, or API events as fulfillment evidence.
- Require type-specific evidence and independent acceptance for high-value or regulated obligations.
- Emit append-only activity events for extraction, verification, assignment, reminder, escalation, status transition, waiver, evidence submission, evidence acceptance, and reopening.
- Produce an evidence package for SLA credit claims, audits, renewals, or disputes, with source provisions and completion history.

#### Change-aware workflows

- Bind every task to the provision version that created it. When source text changes, show the proposed due-date/owner/value impact before rebasing active work.
- Automatically close, supersede, preserve, or send affected obligations for review according to explicit policy; never silently rewrite completed history.
- Maintain recurring obligation instances independently from the rule that generated them so future changes do not alter past attestations.

#### Action integrations

- Deliver notifications and actionable cards through email, calendar, Slack/Teams, Jira, and generic webhooks with idempotency keys and delivery logs.
- Support acknowledge, assign, snooze, request evidence, approve, and complete actions from approved external surfaces while enforcing Termnova authorization.
- Synchronize Jira/ServiceNow-style work items bidirectionally without allowing an external deletion to erase Termnova's audit trail.

#### Exit gate

- A reviewer can take an extracted obligation from unverified to completed with a reconstructable, exportable activity and evidence history.
- Changed source language produces a reviewer-approved workflow impact, not duplicate or silently stale tasks.
- Pilot teams meet owner-coverage, on-time completion, and reminder-delivery SLOs.

### Phase 3 — Contract-family effective-term workbench

**Outcome:** replace a low-value document graph with an evidence-backed answer to “what governs now, and why?”

#### Family assembly

- Suggest MSA, SOW, order form, DPA, amendment, renewal, assignment, and termination relationships from explicit references, agreement IDs, parties, dates, connector folders, and email threads.
- Put suggestions in a family inbox with confidence, evidence, duplicate detection, merge/split actions, and reviewer confirmation.
- Model relationship type, effective date, scope, precedence evidence, and confidence. A force graph remains an optional exploration view, not the primary product surface.

#### Effective-term engine

- Extract stable provisions and explicit effects such as amends, replaces, supersedes, restates, incorporates, extends, terminates, or applies only to a named SOW/product/region.
- Resolve effective terms by category and as-of date using reviewer-approved rules. Handle partial amendments, multiple active SOWs, restatements, future effective dates, and terminated branches.
- Mark ambiguity as unresolved when documents do not provide enough evidence. Show competing provisions side by side instead of inventing precedence.
- Maintain an effective-term ledger that identifies the governing document, clause, modification chain, effective interval, review state, and confidence.

#### Decision workspace

- Lead with family health, current commercial summary, document chronology, effective terms, unresolved conflicts, obligations, exposure, and recent changes.
- Add “as of date” and “for this SOW/product/region” filters, family-level source-backed Q&A, side-by-side evidence, and downloadable family summaries.
- Run change blast-radius analysis: when an amendment arrives, identify displaced provisions, changed obligations, altered renewal/exposure, and required human decisions.

#### Exit gate

- Curated family scenarios resolve to the lawyer-approved effective provision with measured accuracy and explicit unresolved cases.
- Reviewers can explain every effective-term decision through a source-backed modification chain.
- The workbench enables a concrete action—resolve a conflict, update an obligation, act on a deadline, or export an evidence pack—rather than merely displaying relationships.

### Phase 4 — Commercial exposure, controls, and ROI

**Outcome:** quantify what the contract estate can cost, recover, or protect and make the numbers actionable.

#### Exposure control tower

- Aggregate auto-renewal value, notice windows, price escalators, committed spend, minimums, termination fees, service-credit opportunities, unfulfilled supplier duties, ownerless obligations, and disputed terms.
- Add renewal and termination scenario planning, including “do nothing,” renegotiate, consolidate, and terminate-by-window outcomes.
- Normalize currencies using dated rates while preserving contract currency and the exact rate/source used in each calculation.
- Build explainable calculations for value at risk, protected, claimed, recovered, avoided, and forecast. Every total drills down to governing terms and workflow evidence.

#### Commercial controls

- Compare invoice charges, price increases, consumed entitlements, and SLA/service data against effective contractual terms once ERP, AP, procurement, or monitoring integrations are available.
- Detect out-of-contract increases, missed credits, unused entitlements, duplicate commitments, conflicting renewal dates, and spend without an effective agreement.
- Add vendor scorecards that combine contractual commitments, fulfillment, incidents, exceptions, credits, and trend—not only static risk scores.

#### Portfolio analytics

- Add filters and saved views by owner, counterparty, business unit, family, contract type, obligation type, language, date, confidence, review state, and connector health.
- Provide role-specific dashboards for legal operations, procurement, finance, security, executives, and obligation owners.
- Add scheduled board/audit reports and a complete calculation lineage export.

#### Exit gate

- Pilot customers validate dashboard totals against a manually reviewed portfolio within an agreed tolerance.
- At least one workflow demonstrates realized savings or protected value with evidence and finance-approved calculation logic.
- Exposure is recomputed correctly after a version or family-effective-term change.

### Phase 5 — Negotiation intelligence and vendor governance

**Outcome:** use verified post-signature facts and outcomes to improve future agreements and manage vendor controls.

#### Negotiation playbook copilot

- Define preferred, acceptable, fallback, and prohibited positions by contract type, jurisdiction, value, data sensitivity, vendor tier, and language.
- Detect clause deviations, route approvals, recommend grounded fallback language, track concession budgets, and retain the reason and approver for each exception.
- Generate DOCX-native tracked changes and comments while preserving document formatting and a complete version history.
- Use organization-approved examples and observed post-signature outcomes to show why a playbook position matters; do not learn from confidential cross-customer data.
- Add multilingual playbooks, terminology controls, and bilingual redline review with original-language authority.

#### Vendor governance modules

- Add DPA, security addendum, AI-use, subprocessor, audit-right, breach-notification, data-residency, records-retention, and regulatory-flow-down controls.
- Map contractual controls to security questionnaires, risk findings, certificates, incidents, and recurring attestations.
- Detect changes to subprocessors, policies incorporated by URL, product terms, and external schedules where monitoring is lawful and authorized.
- Provide vendor onboarding/offboarding packs, exception expiry, control-owner workflows, and audit-ready evidence exports.

#### Exit gate

- Suggested redlines are grounded only in approved playbook language and pass lawyer review on the supported contract types.
- A negotiated deviation flows into the effective family, obligations, controls, and exposure without re-entry.
- Vendor governance reports trace every control state to an effective provision and current evidence.

## Cross-cutting workstreams

| Workstream | Phase 0 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
| --- | --- | --- | --- | --- | --- | --- |
| Living documents | Version model and event ledger | Sync, diff, incremental extraction | Workflow rebasing | Family blast radius | Exposure recompute | Redline-to-executed continuity |
| Multilingual | Language/OCR/translation boundaries | Bilingual extraction and review | Locale-aware workflows | Cross-language effective terms | Currency/locale reporting | Multilingual playbooks |
| Real documents | Provenance and data separation | Demo corpus and customer onboarding | Evidence examples | Curated real families | Validated portfolio scenarios | Approved negotiation examples |
| Connectors | OAuth, events, scopes, secrets | Drive/Gmail then Microsoft sources | Slack/Teams/Jira/calendar actions | Folder/thread-assisted families | ERP/AP/CRM enrichment | Word and governance systems |
| Evaluation | Harness and gold-set registry | Extraction/citation slices | Workflow correctness | Effective-term scenarios | Calculation reconciliation | Redline and control accuracy |

Detailed plans:

- [Living-document and multilingual architecture](document-lifecycle-and-language-plan.md)
- [Contract-family workbench rework](contract-family-workbench-plan.md)
- [Connector platform and workspace-app plan](connector-platform-plan.md)
- [Real-contract corpus and onboarding plan](real-contract-corpus-plan.md)

## Initial domain model

The core aggregates are:

- Identity and control: `Organization`, `Workspace`, `Membership`, `RoleBinding`, `AuditEvent`, `RetentionPolicy`.
- Source and processing: `LogicalDocument`, `DocumentVersion`, `DocumentArtifact`, `ClauseIdentity`, `ClauseVersion`, `ProcessingSnapshot`, `DocumentChange`.
- Contract intelligence: `ContractFamily`, `FamilyMembership`, `Provision`, `ProvisionEffect`, `EffectiveTerm`, `ExtractionRun`, `ExtractedFact`, `ReviewDecision`.
- Operations and value: `Obligation`, `ObligationInstance`, `ObligationEvidence`, `ObligationEvent`, `ExposureCalculation`, `ValueOutcome`.
- Integrations: `IntegrationConnection`, `SyncScope`, `ExternalObject`, `SyncCursor`, `WebhookSubscription`, `ConnectorEvent`, `ActionDelivery`.

Every aggregate is organization-scoped. Extracted facts, translations, effective-term decisions, and calculations are versioned rather than overwritten.

## Release packaging

1. **Foundation release:** Phase 0, internal evaluation corpus, security controls, and operations tooling.
2. **Connected intelligence pilot:** Phase 1 with uploads, Google Drive, version history, English plus one customer-selected pilot language, extraction, and verification.
3. **Obligation operations pilot:** Phase 2 with owners, reminders, evidence, calendar/email, and one work-management integration.
4. **Family intelligence release:** Phase 3 workbench and amendment blast-radius workflow.
5. **Commercial control release:** Phase 4 renewal, SLA-credit, escalation, and explainable ROI workflows.
6. **Expansion release:** Phase 5 negotiation and vendor-governance packs, chosen from pilot demand.

Each release should remain behind organization feature flags until its data migrations, audit behavior, evaluation thresholds, runbooks, and rollback plan have passed staging.

## Metrics that determine product-market fit

- Extraction precision and recall by obligation type, contract type, language, scan quality, and monetary-risk tier.
- Citation correctness, clause localization accuracy, and unsupported-answer rate.
- Median source-change detection time, version processing time, and percentage of changes reconciled without manual re-upload.
- Reviewer correction rate, material-change false-negative rate, and repeated-error rate after organization adaptation.
- Median time from intake to verified obligation and percentage of obligations with an owner before the due date.
- On-time fulfillment, accepted-evidence rate, overdue escalation response, and reopened-task rate.
- Family suggestion acceptance, effective-term accuracy, unresolved-conflict age, and amendment-impact review time.
- Renewal exposure acted on before notice, credits claimed/recovered, spend avoided, and value protected.
- Connector freshness, webhook lag, reconciliation drift, action delivery success, and permission-denial rate.
- Active portfolios, weekly active reviewers/owners, time-to-first-value, expansion by connector/module, and retained protected value.

## Explicit non-goals for the first market release

- Replacing a customer's entire CLM, e-signature, procurement, ERP, or ticketing platform.
- Providing autonomous legal advice or silently deciding ambiguous precedence.
- Claiming support for every language before per-language evaluations exist.
- Treating machine translation as authoritative contract text.
- Mirroring an entire mailbox or drive when a narrower folder, label, or shared mailbox scope is sufficient.
- Using customer documents to train shared models without an explicit, separately governed agreement.
