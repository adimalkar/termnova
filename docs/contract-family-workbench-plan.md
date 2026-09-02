# Contract-Family Effective-Term Workbench Plan

## Product decision

The existing family/graph experience should be reworked from a relationship visualization into a decision workspace that answers:

> Which term governs this issue for this scope and date, what changed it, what remains unresolved, and what action follows?

A node-link graph can remain as a secondary exploration tool. It is not the primary value because users still have to interpret precedence, amendments, overlapping SOWs, and operational impact themselves.

## Problems to solve

- An MSA, DPA, SOW, order form, renewal, and several amendments are uploaded as unrelated documents.
- A later agreement changes only one subsection, while the rest of the parent remains effective.
- Two SOWs have different pricing, SLA, region, product, or term scopes under the same MSA.
- A restatement replaces an agreement, but historic obligations must still resolve correctly for past dates.
- An amendment contains vague precedence language and Termnova cannot safely decide which text controls.
- A document version changes and users cannot tell which obligations or commercial totals are now stale.
- Users see graph edges but cannot act on them.

## Primary user journeys

### Assemble a family

1. Termnova suggests family membership and relationship type.
2. The reviewer sees the exact reference, parties, dates, source folder/thread, and confidence supporting the suggestion.
3. The reviewer confirms, corrects, rejects, merges, or splits the family.
4. Termnova recomputes effective terms and shows unresolved scope/precedence questions.

### Determine the current term

1. The user selects a topic such as renewal, liability cap, price escalation, DPA breach notice, or SLA credit.
2. The workbench shows the current value, governing document and clause, modification chain, applicable scope, and effective interval.
3. The user changes “as of” date, SOW, product, region, entity, or customer/supplier role.
4. The result updates with original evidence and competing text when ambiguous.

### Process an amendment

1. A connector or upload creates a new immutable amendment version.
2. Termnova proposes family placement and clause effects.
3. A blast-radius view shows displaced provisions, changed fields, obligations, deadlines, and exposure.
4. The reviewer approves effects and separately approves downstream workflow changes.

## Information model

`ContractFamily`

- Organization, name, counterparties, family status, primary agreement, owner, review health, and external business identifiers.

`FamilyMembership`

- Family, logical document, role (master, SOW, amendment, DPA, order, renewal, termination, assignment, exhibit), scope, effective interval, and reviewer state.

`DocumentRelationship`

- Source and target logical documents, typed relationship, supporting source span, confidence, extractor snapshot, and reviewer decision.
- Types include `AMENDS`, `RESTATES`, `SUPERSEDES`, `INCORPORATES`, `GOVERNS`, `EXTENDS`, `TERMINATES`, `ASSIGNS`, and `RELATED_ORDER`.

`Provision`

- Stable semantic provision identity within a family and category such as renewal, payment, liability, SLA, privacy, security, or termination.

`ProvisionVersion`

- Exact document version and clause span, normalized typed value, language, effective interval, scope predicates, and verification state.

`ProvisionEffect`

- Actor provision, target provision or category, effect type, whole/partial scope, effective date, evidence, confidence, and decision.
- Effects include replace, modify, delete, add, narrow, expand, suspend, revive, and terminate.

`EffectiveTerm`

- Materialized, versioned decision for a family/topic/scope/as-of interval.
- Governing provision, modification chain, resolution rule, confidence, state, and reviewer.

`FamilyDecision`

- Append-only approval, correction, ambiguity, manual override, waiver, merge/split, or rollback event with reason and evidence.

No family object or effect may cross organization boundaries. Manual decisions are not overwritten by later extraction runs; new evidence creates a review proposal.

## Family suggestion engine

Signals should be scored and explained rather than collapsed into one opaque embedding score:

- Explicit references: agreement title, date, ID, “pursuant to,” “amends,” “under,” or “incorporated by reference.”
- Party/entity overlap and roles, accounting for assignments, parent/subsidiary names, and normalized aliases.
- Contract numbers, purchase/order numbers, project names, products, regions, and effective-date ranges.
- Source context such as a dedicated Drive folder, SharePoint library, Gmail/Outlook thread, or e-signature envelope.
- Document type and signature metadata.
- Repeated defined terms and cross-document citations.

High confidence still produces a suggestion unless an organization explicitly enables a safe auto-link rule. Ambiguous candidates must show why they match and what evidence is missing.

## Effective-term resolution

### Rule order

1. Apply only reviewer-confirmed family membership and document versions valid for the requested as-of date.
2. Filter by explicit scope: legal entity, SOW/order, service/product, region, data set, customer group, or other defined dimension.
3. Apply explicit termination, restatement, supersession, amendment, and precedence language with its evidenced scope.
4. Apply provision effects in effective-date order while retaining every intermediate state.
5. If two surviving provisions conflict and no approved rule resolves them, return `unresolved` with both sources.

Document type or recency alone is not legal proof of precedence. Organization-configured rules may suggest a result but cannot conceal contradicting source text.

### Special cases

- **Partial amendment:** replace only the targeted span; inherit unaffected parent text.
- **Restatement:** create a new governing branch from its effective date while preserving historic answers.
- **Future-effective change:** show current and scheduled terms separately.
- **Multiple SOWs:** maintain parallel scoped effective terms rather than merging their commercial values.
- **Incorporated URL/policy:** snapshot the referenced artifact when authorized and preserve the incorporation evidence.
- **Bilingual agreement:** extract any language-precedence clause; if none exists, show language variants without assuming equivalence.
- **Termination:** distinguish document termination, service/SOW termination, and obligations that survive termination.

## Workbench information architecture

### Family header

- Counterparty, internal entities, primary agreement, active term, total value, owner, source freshness, and last approved change.
- Health indicators: unlinked documents, unresolved conflicts, stale facts, unreviewed amendment impacts, ownerless obligations, and expiring terms.

### Tabs

1. **Effective terms:** category table with current value, scope, governing source, last change, confidence, and review state.
2. **Timeline:** chronological agreements, versions, effects, signatures, renewals, terminations, and decisions.
3. **Changes:** amendment/revision blast radius and pending decisions.
4. **Obligations:** current and historical duties/entitlements grouped by governing provision.
5. **Exposure:** family-specific value, renewal, escalation, SLA credits, and calculation lineage.
6. **Documents:** family members, suggested additions, duplicates, and source synchronization.
7. **Graph:** optional relationship exploration with filters and evidence drawer.

Every table row opens an evidence drawer showing original document, exact clause, aligned translation when requested, and the complete modification chain.

### Actions

- Confirm or change relationship and scope.
- Resolve or explicitly leave a conflict unresolved.
- Assign review or an obligation owner.
- Accept/reject amendment effects.
- Create a renewal, termination, credit, or remediation workflow.
- Export an as-of family summary and evidence package.
- Compare two dates or scopes.

## APIs

- `GET /families` with health, owner, counterparty, date, source, and conflict filters.
- `POST /families/suggestions/{id}/decision`.
- `POST /families/{id}/members` and audited merge/split endpoints.
- `GET /families/{id}/effective-terms?as_of=&scope=`.
- `GET /families/{id}/effective-terms/{category}/lineage`.
- `GET /families/{id}/changes/{version_id}/impact`.
- `POST /families/{id}/effects/{id}/decision`.
- `POST /families/{id}/conflicts/{id}/decision`.
- `GET /families/{id}/summary?as_of=&scope=&language=`.

Writes use optimistic concurrency and idempotency keys. Responses include the family calculation version so clients cannot approve a stale proposal.

## Migration from the current graph

1. Retain existing entities and relationships as unverified candidate evidence; do not treat current edges as effective-term decisions.
2. Add organization scope and source-version references to graph-derived records.
3. Backfill logical documents and family candidates from explicit relationship records, party/date signals, and existing document metadata.
4. Require review before candidates influence effective terms.
5. Replace the graph-first page with the workbench shell; keep the D3 view under the Graph tab.
6. Remove the current shortcut that builds intelligence from only the first few chunks. Family extraction must use relevant indexed clauses across the complete document.
7. Introduce effective-term calculations category by category: renewal/term, pricing, SLA/credits, termination, liability, privacy/security, then long-tail clauses.

## Evaluation scenarios

The gold set must contain complete, lawfully usable families rather than isolated clauses:

- MSA plus two SOWs with different prices and terms.
- MSA plus amendment changing one liability subsection.
- DPA that overrides security/breach terms only.
- Restated agreement with historic and future as-of questions.
- Conflicting precedence clauses that must remain unresolved.
- Termination with surviving confidentiality, payment, audit, and data-deletion duties.
- Assignment to a new entity.
- Multilingual family with and without a language-precedence clause.
- Source revision that changes an amendment before and after signature.

Measure relationship suggestion precision/recall, provision alignment, effect classification, effective-term accuracy, appropriate unresolved rate, evidence correctness, reviewer correction rate, and blast-radius false negatives.

## Rollout and success metrics

### Release 1: family inbox

- Suggestions, evidence, confirm/reject, merge/split, chronology, and graph demotion.
- Success: suggestion acceptance and time to assemble a family.

### Release 2: effective term ledger

- Renewal, term, pricing, SLA/credits, and termination categories with as-of filtering.
- Success: lawyer-approved effective-term accuracy and time to answer a family question.

### Release 3: amendment blast radius

- Provision effects, change review, obligation/exposure proposals, and audit trail.
- Success: time from amendment arrival to approved impact and material-impact false-negative rate.

### Release 4: portfolio controls

- Family health queues, unresolved conflict aging, scheduled changes, cross-family filters, and reporting.
- Success: conflicts resolved, renewal actions completed, stale terms reduced, and protected/recovered value.

## Non-goals

- Automatically declaring a legally controlling term when evidence is ambiguous.
- Treating every document mentioning the same vendor as one family.
- Replacing lawyer review for complex precedence or scope interpretation.
- Making the force graph the primary workflow.
- Recomputing history by overwriting prior effective-term decisions.
