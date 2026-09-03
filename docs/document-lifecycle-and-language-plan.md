# Living-Document and Multilingual Architecture Plan

## Purpose

Enterprise contracts are not static uploads. Files are edited, renamed, moved, countersigned, replaced, restated, and amended in connected repositories. Termnova must preserve that history and keep every derived fact current without confusing a new revision with a new agreement.

This plan also makes multilingual processing a first-class capability. Original-language text remains authoritative; translations are useful, traceable derivatives.

## Current gap

The current general upload path identifies exact file content by hash and creates a standalone document for changed content. It does not have a stable business-document identity, immutable version chain, source revision identity, version diff, or downstream impact model. Negotiation versions are a separate workflow and should not become the persistence model for executed contract changes.

Current PostgreSQL full-text search is configured around English. That is not sufficient for documents or questions in other languages and can silently reduce recall.

## Required user experience

### Document record

The document page should show:

- Current effective version and lifecycle state: draft, executed, future-effective, superseded, terminated, or archived.
- Original source, folder/mail thread, source owner, last synchronized time, and connector health.
- Complete version timeline with author/source actor when available, checksum, source revision ID, and ingestion state.
- Side-by-side and redline comparison for any two versions.
- A material-change summary grouped by commercial, legal, security, privacy, SLA, and operational impact.
- Changed obligations, family terms, deadlines, calculations, and review decisions.
- Original-language text, optional translation, language confidence, and bilingual citations.

### Change review

A reviewer receives one change packet containing:

1. What changed and whether the source regards it as a new revision.
2. Clause-level before/after evidence.
3. Proposed field, obligation, family, and exposure changes.
4. Items that remain valid and require no review.
5. Ambiguities, low-confidence alignment, and whole-document replacement warnings.
6. Approve, correct, reject, split, merge, defer, or mark as non-material actions.

Approval promotes a complete processing snapshot atomically. Until then, the portal continues to show the last approved version and clearly labels a newer version as pending.

## Data model

### Logical document and immutable versions

`LogicalDocument`

- Organization, workspace, title, type, counterparty, and family.
- Canonical source and `current_approved_version_id`.
- Stable business identity independent of filename or storage path.

`DocumentVersion`

- Logical document, monotonically increasing Termnova sequence, parent version, and lifecycle state.
- Source version/revision ID, ETag, source modified time, observed time, content hash, and normalized text hash.
- Detected BCP 47 language tags, processing state, approval state, and effective interval.
- Exact processing snapshot: parser, OCR, chunker, embedding, extractor, schema, prompt, and model versions.

`DocumentArtifact`

- Original bytes, rendered pages, OCR text, normalized text, layout map, and optional translations.
- Object-storage key, hash, MIME type, encryption metadata, retention state, and malware result.

`ClauseIdentity` and `ClauseVersion`

- Stable organization-scoped clause identity across versions.
- Version-specific heading, normalized content, source span, page geometry, fingerprints, and alignment confidence.
- Split/merge ancestry so a clause rewritten into two clauses does not lose lineage.

`DocumentChange`

- From/to versions, deterministic and model-assisted classification, materiality, changed clause identities, reviewer decision, and downstream effects.

`ExternalObjectLink`

- Connection, provider, stable external object ID, drive/mailbox/site, revision identity, URL, permissions snapshot, and last cursor position.
- Uniqueness is organization-scoped; a hash must never deduplicate documents across tenants.

### Translations

`TranslationArtifact` stores language pair, provider/model, terminology-set version, segment alignment, confidence, created time, and source version. It is regenerated when the source or terminology changes and is never treated as a new legal version.

## Change ingestion pipeline

1. **Accept and persist the signal.** Validate webhook signatures where supported, store a minimal immutable event envelope, acknowledge quickly, and enqueue processing.
2. **Normalize and deduplicate.** Convert provider payloads into a common event schema. Use provider event ID plus connection ID for event idempotency.
3. **Resolve the source object.** Fetch current metadata and permissions using the stable external object ID, not its path. A rename or move updates metadata, not legal content.
4. **Decide whether bytes changed.** Compare source revision/ETag, content hash, and normalized text hash. Record metadata-only and formatting-only changes without rerunning extraction.
5. **Create an immutable version.** Store the original before parsing. Never mutate a previously approved artifact.
6. **Quarantine and parse.** Run MIME checks, malware scan, OCR/layout parsing, Unicode NFC normalization, and language detection.
7. **Align and diff.** Match sections and clauses using numbering, headings, structural position, text fingerprints, citations, and semantic similarity. Preserve uncertainty.
8. **Classify materiality.** Apply deterministic rules first for dates, amounts, percentages, negation, parties, defined terms, and obligation verbs. Use a model only for semantic changes and require evidence.
9. **Incrementally recompute.** Re-chunk and re-embed changed regions plus necessary neighbors. Re-extract affected fields and obligations and recompute dependent family terms and exposure.
10. **Create a review packet.** High-impact, low-confidence, whole-replacement, signature-state, and conflict-producing changes require review.
11. **Promote atomically.** Update the approved/current pointer and emit domain events only after all required artifacts and decisions are consistent.
12. **Reconcile.** Periodic provider delta scans and sampled content hashes recover missed notifications and detect drift.

## Handling daily and minute-by-minute edits

- Use a short configurable settle window for autosave storms, while recording every received provider event.
- Coalesce processing for multiple notifications that point to the same provider revision. Do not claim to preserve intermediate edits that the provider itself does not expose.
- Keep source revision IDs when the provider offers revision history; distinguish a provider revision from a Termnova observed version.
- Apply per-connection rate budgets, fair queues, backpressure, and exponential retry. One noisy folder must not starve another organization.
- If a newer version arrives during processing, finish or safely cancel the older job according to its stage; only the newest complete approved snapshot becomes current.
- Use optimistic promotion locks to prevent out-of-order completion.
- For very large replacements, fall back to section-level alignment and explicitly label low-confidence lineage.

## Change classes and downstream policy

| Change class | Examples | Default processing | Human review |
| --- | --- | --- | --- |
| Metadata | rename, move, label | Update source metadata | No |
| No-op formatting | font, pagination, whitespace | Store event; preserve existing facts | Sample only |
| Minor wording | typo, punctuation, non-operative recital | Re-align affected span | If confidence is low |
| Material clause | date, amount, negation, duty, remedy, scope | Re-extract and calculate blast radius | Yes |
| Status/signature | draft executed, countersigned | Update lifecycle/effective logic | Yes |
| Whole replacement | restatement or unrelated bytes under same source ID | Full parse and family analysis | Yes |
| Deletion/revocation | deleted object or lost permission | Tombstone source link; retain per policy | Administrator policy |

Downstream objects carry a freshness state: `current`, `pending_review`, `stale`, `superseded`, or `error`. Completed obligation instances and historical calculations are immutable; future work can be rebased only through an audited decision.

## Multilingual processing design

### Language identity and normalization

- Store language using BCP 47 tags at document, page, clause, query, and translation-segment level.
- Support mixed-language documents rather than forcing a single language on an entire file.
- Normalize searchable Unicode text to NFC while retaining byte-perfect originals and layout coordinates.
- Preserve locale separately from language for dates, decimal separators, currencies, and legal jurisdiction.

### OCR and parsing

- Select OCR language packs from detected script/language and allow reviewer override.
- Measure OCR confidence by page and span. Route low-confidence dates, amounts, signatures, and obligation verbs for verification.
- Preserve tables, footnotes, handwritten annotations, stamps, and page geometry because commercial terms often live outside body paragraphs.
- Evaluate digital PDFs, scans, photos, DOCX, and bilingual side-by-side layouts separately.

### Retrieval and answers

- Replace the hard-coded English full-text assumption with language-aware configurations where PostgreSQL supports the language and a `simple`/ngram fallback where it does not.
- Use a multilingual embedding model only after retrieval benchmarks meet thresholds for every launch language.
- Detect query language, search original and authorized translation indexes, and use reciprocal-rank fusion without mixing evidence across tenants.
- Generate the answer in the user's chosen language, but cite the original clause. Provide aligned translation as a convenience view.
- Show an explicit warning when translation or OCR uncertainty can change legal meaning.

### Extraction and review

- Keep the obligation taxonomy language-neutral; store localized labels separately.
- Use language-specific prompts/examples and terminology sets for legal phrases, defined terms, party names, dates, and currencies.
- Assign review items based on reviewer language capability and support a second approval for translated high-impact fields.
- Capture whether a reviewer corrected extraction, translation, alignment, or source OCR; these are different error classes.
- Do not infer that two language versions are equally authoritative. Extract language-precedence clauses and send ambiguity to the family workbench.

### Launch policy

The first non-English language should be selected from pilot customer demand and available evaluation data, not marketing breadth. Each supported language needs:

- A representative licensed evaluation set across contract types and scan quality.
- Retrieval, extraction, OCR, citation, and translation thresholds.
- A legal terminology glossary and qualified reviewer workflow.
- UI localization where users in that market require it.
- A published limitations statement and monitored error slices.

“Detected” is not the same as “supported.” The portal may ingest an unsupported language but must clearly state which operations have not passed validation.

## APIs and events

Initial endpoints:

- `POST /documents/{id}/versions` for explicit upload or replacement.
- `GET /documents/{id}/versions` and `GET /documents/{id}/versions/{version_id}`.
- `GET /documents/{id}/diff?from=&to=`.
- `GET /documents/{id}/change-impact?version=`.
- `POST /document-changes/{id}/decision`.
- `POST /documents/{id}/translations` and `GET /documents/{id}/translations/{language}`.
- `POST /connectors/events/{provider}` for verified webhooks.

Domain events:

- `document.version_observed`, `document.version_quarantined`, `document.version_processed`.
- `document.change_review_required`, `document.version_promoted`, `document.version_superseded`.
- `obligation.revalidation_required`, `family.recalculation_required`, `exposure.recalculation_required`.
- `translation.created`, `translation.invalidated`, `connector.reconciliation_drift_detected`.

Every command and event carries organization ID, logical document ID, version ID, correlation ID, causation ID, actor, and idempotency key.

## Failure, retention, and legal-hold behavior

- A failed new version never corrupts the last approved version.
- Original artifacts and audit records follow organization retention and legal-hold policy independently from connector deletion.
- Source deletion creates a tombstone and permission change; it does not silently destroy retained evidence.
- Revoked source access removes access to refresh/download according to policy and is visible to administrators.
- A rollback changes the current pointer through a new audited decision; it does not erase history.
- Reprocessing creates a new processing snapshot attached to the same legal version, allowing model upgrades without pretending the contract changed.

## Evaluation and SLOs

- Source notification acknowledged within provider requirements; 99% of durable events enter processing within the internal target.
- Freshness SLO is measured from source modification and separately from event receipt.
- Zero lost approved versions under retry, duplicate, out-of-order, or worker-crash tests.
- Version alignment precision/recall and material-change false-negative rate are release gates.
- Downstream impact tests cover deadline, amount, party, scope, negation, renewal, termination, SLA, and precedence changes.
- Multilingual metrics are reported per language and never hidden inside a global average.

## Rollout

1. Add logical documents and versions behind a feature flag; migrate existing documents as version 1 without changing public behavior.
2. Add manual new-version upload, history, and deterministic diff.
3. Add incremental extraction and review packets.
4. Launch Google Drive synchronization with reconciliation and connector health.
5. Add the first validated non-English language and bilingual evidence UX.
6. Extend to Gmail, Microsoft sources, mixed-language documents, and change-triggered family/workflow/exposure recomputation.

## External design references

- Language tags follow [RFC 5646 / BCP 47](https://www.rfc-editor.org/info/rfc5646/).
- Unicode text normalization follows [Unicode Standard Annex #15](https://www.unicode.org/reports/tr15/); originals remain byte-preserved.
- PostgreSQL documents language-specific parser/dictionary composition in [text search configurations](https://www.postgresql.org/docs/current/textsearch-configuration.html).
- Google Drive exposes both a change log and file revisions; see [changes and revisions overview](https://developers.google.com/workspace/drive/api/guides/change-overview).
- Microsoft Graph recommends stable item IDs and delta links for [Drive item change tracking](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0).
