# Termnova Control Tower Roadmap

## Product position

Termnova should enter the market as a vendor contract obligation and exposure control tower for mid-market legal operations and procurement teams. The primary outcome is not document chat; it is preventing missed obligations, recovering contractual value, and proving completion with source-backed evidence.

## Delivery sequence

### Phase 0 — Trustworthy platform foundation

- Complete indexed retrieval, durable originals, asynchronous ingestion, bounded model calls, and measurable extraction evaluation.
- Add OIDC/SAML, SCIM, organization membership, RBAC, tenant IDs, and PostgreSQL row-level security before multi-tenant production use.
- Add immutable audit events, retention/deletion controls, malware scanning, customer model-routing controls, and ingestion dead-letter operations.
- Exit gate: tenant-isolation tests pass; restore/delete drills pass; extraction benchmark and citation benchmark are published internally.

### Phase 1 — Obligation extraction and verification

- Define typed schemas for renewal, notice, payment, escalation, SLA, service-credit, security, reporting, termination, and party obligations.
- Store every extracted field with document ID, page, clause span, extractor version, confidence, and verification status.
- Route low-confidence and high-impact fields to the existing triage inbox for approve, correct, reject, and duplicate actions.
- Preserve reviewer corrections as labeled evaluation examples, separated by organization.
- Exit gate: agreed precision and recall targets are met per obligation type; no obligation can be displayed without source evidence.

### Phase 2 — Ownership and fulfillment

- Add assignee, due date, recurrence, escalation policy, state, comments, and evidence attachments.
- Emit append-only activity events for extraction, verification, assignment, reminders, status changes, and evidence acceptance.
- Add email, calendar, Slack/Teams, Jira, and generic webhook actions with idempotency keys and delivery logs.
- Exit gate: a reviewer can take an extracted obligation from unverified to completed with a reconstructable audit trail.

### Phase 3 — Contract-family effective-term engine

- Connect MSAs, SOWs, order forms, DPAs, and amendments using explicit relationship types and reviewer confirmation.
- Model clause precedence, effective dates, supersession, partial amendment, and termination.
- Produce an effective-term view and conflict warnings with evidence from both parent and modifying documents.
- Exit gate: curated contract-family scenarios resolve to the lawyer-approved effective provision with measured accuracy.

### Phase 4 — Commercial exposure and ROI

- Aggregate auto-renewal value, notice windows, price escalators, SLA credit opportunities, unfulfilled supplier duties, and ownerless obligations.
- Track value at risk, protected, claimed, recovered, and avoided with an auditable calculation explanation.
- Add portfolio filters by owner, counterparty, business unit, contract family, obligation type, date, and confidence.
- Exit gate: pilot customers can validate dashboard totals against a manually reviewed portfolio and report realized savings.

### Phase 5 — Negotiation and vendor-governance expansion

- Build playbook deviation, approval routing, grounded fallback language, concession budgets, and DOCX tracked-change output after post-signature workflows are proven.
- Add a vendor-governance pack for DPA, security, AI-use, subprocessor, audit, breach, residency, and regulatory-flow-down controls.

## Initial domain model

The minimum new aggregates are `Organization`, `ContractFamily`, `EffectiveProvision`, `Obligation`, `ObligationEvidence`, `ObligationEvent`, `ExtractionRun`, `ReviewDecision`, `IntegrationConnection`, and `ActionDelivery`. Every aggregate is organization-scoped. Extracted facts are versioned rather than overwritten, and reviewer decisions reference the exact extraction version they assessed.

## Metrics that determine product-market fit

- Extraction precision and recall by obligation type and monetary-risk tier.
- Citation correctness and page/clause localization accuracy.
- Median time from upload to verified obligation.
- Percentage of obligations with an owner before the due date.
- Renewal exposure acted on before the notice deadline.
- Credits claimed, spend avoided, and value protected.
- Reviewer correction rate and repeated-error rate after organization adaptation.
