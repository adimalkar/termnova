# Real-Contract Corpus and Customer Onboarding Plan

## Goal

Termnova needs real contracts for three different purposes that must not be conflated:

1. **Public product demo:** a read-only portfolio that lets prospects experience the product without uploading confidential data.
2. **Evaluation:** licensed documents with reviewed labels and scenarios that gate retrieval, extraction, family, language, and change releases.
3. **Customer onboarding:** the customer's authorized documents, isolated in that organization and governed by its permissions, retention, and model-routing choices.

Synthetic documents remain useful for edge cases, destructive tests, and deliberately complex families, but must always be labeled synthetic. They cannot be presented as customer evidence or real-world validation.

## Data governance first

Public accessibility is not the same as permission to redistribute, modify, translate, or use a document in a commercial demo. Every corpus item requires a reviewed manifest entry before ingestion.

`CorpusManifestEntry` includes:

- Stable corpus ID and purpose: demo, evaluation, or test.
- Original title, contract type, parties, filing/publisher identifier, source URL, and retrieval date.
- Publisher/rightsholder, license or other use basis, attribution text, redistribution flag, derivative/translation flag, and review owner/date.
- Original content hash, local object key, MIME type, language, page count, and scan quality.
- Redaction/anonymization state and prohibited-use notes.
- Family ID only when a relationship is evidenced; no guessed families for a polished demo.
- Gold-label version, reviewer qualifications, disagreements, and adjudication state where used for evaluation.

The manifest is version controlled; large source documents should live in controlled object storage or be fetched by a reproducible importer when the license permits it. Never commit private customer contracts to the repository.

## Public demo organization

Create a seeded, read-only organization that is operationally separate from customer tenants.

### Initial portfolio

- 25–50 attributable real commercial agreements covering MSA/service, SaaS, license, supply, outsourcing, SLA, DPA/privacy, order/SOW, and amendment patterns.
- A balanced range of page lengths, layouts, scan quality, dates, monetary terms, and party roles.
- 5–10 genuine contract families only if the complete related document sets can be lawfully used. Otherwise show isolated real contracts and clearly labeled synthetic family scenarios.
- Non-English or bilingual real contracts only after use/translation rights and evaluation coverage are confirmed.
- A small number of intentionally difficult documents with visible limitations; the demo should not hide OCR or ambiguity.

### Demo stories

The seed data should support specific repeatable workflows:

- Find an upcoming auto-renewal and its notice deadline.
- Recover an SLA credit with a clause-backed claim pack.
- Detect an out-of-contract price escalation.
- Review a changed document version and approve obligation impact.
- Resolve an amendment in a family and compare effective terms by date.
- Search in one language and inspect evidence in another.
- Assign, fulfill, and export an obligation with evidence.

Demo results are precomputed through the same production pipeline and retain their processing snapshots. Any manually curated result is labeled and auditable rather than hard-coded into the UI.

## Candidate public sources

### CUAD

The Contract Understanding Atticus Dataset contains 510 real commercial contracts, more than 13,000 expert labels, and 41 clause categories. Its publisher describes it as CC BY 4.0. It is useful for clause/evidence evaluation and for selecting attributable demo documents after a manifest review.

CUAD does not by itself prove that Termnova can assemble complete MSA/SOW/amendment families, track daily revisions, or extract the full obligation schema. Add separate family and version-change evaluation sets.

### SEC EDGAR

SEC filing exhibits can provide public agreements and filing metadata. Use SEC APIs and fair-access guidance, preserve accession/source links, and review the rights/status of each underlying exhibit before redistribution or derivative use.

Do not build the product demo by scraping arbitrary “public” contract sites without provenance and a documented use basis.

### Permissioned pilot contributions

Invite design partners to contribute de-identified or permissioned evaluation examples under a written agreement that specifies purpose, access, retention, derivative labels, model-training exclusion, and deletion. Keep this corpus separate from their production organization.

## Evaluation corpus design

### Required slices

- Contract type and clause/obligation category.
- Digital PDF, scanned PDF, image, DOCX, table-heavy, and poor-layout documents.
- Short and long contracts.
- Language, locale, bilingual layout, and OCR/script.
- Monetary-risk tier and date/notice arithmetic complexity.
- Original, minor revision, material revision, restatement, and unrelated replacement.
- Isolated document and complete family scenarios.
- Explicit, implicit, conflicting, and unresolved precedence.
- Positive and negative examples, especially absent clauses and no-obligation text.

### Labels

- Exact page, clause, and character span.
- Typed value with normalized date/currency/percentage and party role.
- Obligation actor, beneficiary, action, object, trigger, due rule, recurrence, remedy, and conditions.
- Version alignment and materiality.
- Family membership, relationship, provision effect, scope, as-of effective term, and correct unresolved state.
- Translation/OCR/alignment corrections where applicable.

At least two qualified reviewers should adjudicate the high-risk test subset. Split by contract family and source, not random clauses, to prevent near-duplicate leakage between train/examples and test.

### Release gates

- No evaluation document appears in prompts/examples used for the same held-out test.
- Report precision, recall, false-negative rate, evidence accuracy, and calibration by slice rather than only one aggregate score.
- Compare every model/parser/prompt/schema change against the pinned corpus and retain regression artifacts.
- Product documentation states which contract types and languages meet thresholds and which remain experimental.

## Customer onboarding flow

### Step 1: define authorization and scope

- Choose organization/workspace, data region, retention, model providers, administrators, reviewers, and legal hold behavior.
- Select upload, ZIP, Drive/Shared Drive, Gmail label/shared mailbox, OneDrive/SharePoint, Outlook, or later repository connector.
- Preview requested scopes and estimated document count/size before content transfer.

### Step 2: inventory before ingestion

- Fetch metadata first where the provider permits it: name, type, size, modified time, source owner, path/container, permissions, and stable object ID.
- Estimate supported, unsupported, duplicate, encrypted, too-large, and likely non-contract files.
- Let administrators refine include/exclude rules and sample the proposed scope.

### Step 3: secure ingestion

- Quarantine originals, validate MIME, scan malware, hash within the tenant, and identify encrypted/password-protected files.
- Create logical documents and immutable first versions; preserve external object identity for future changes.
- Separate exact duplicates from legitimate copies and distinguish amendments/versions from duplicate files.
- Show progress and actionable errors at source, object, and processing-stage level.

### Step 4: metadata and family review

- Propose contract type, parties, owner, business unit, dates, value, language, family, and lifecycle state.
- Bulk approve deterministic metadata while routing ambiguity, possible duplicates, and family conflicts to reviewers.
- Support CSV mapping for internal vendor IDs, contract IDs, cost centers, and owners.

### Step 5: quality acceptance

- Randomly sample by contract type, language, scan quality, and risk tier.
- Compare extraction/citation results with customer reviewers and record corrections as organization evaluation data.
- Publish onboarding completeness: files discovered, authorized, fetched, quarantined, parsed, reviewed, failed, excluded, and stale.
- Enable workflows only after agreed quality and owner-mapping gates; avoid flooding users with unverified tasks.

## Privacy and tenant separation

- Demo and evaluation organizations have different credentials, object-storage prefixes/buckets, encryption context, database tenant IDs, indexes, and audit exports from customer organizations.
- Customer originals are excluded from shared training by default.
- Logs contain identifiers and redacted diagnostics, not document bodies or secrets.
- Support customer deletion, legal hold, export, connector revocation, and model-provider restrictions.
- Reviewers and support staff use time-bound, approved access with complete audit events.

## Implementation sequence

1. Define the corpus manifest schema, license-review checklist, and storage separation.
2. Build a deterministic seed/import command using the normal ingestion API and processing pipeline.
3. Curate the first CUAD/approved public subset and pin hashes/source links.
4. Add demo organization reset, read-only role, guided stories, and visible provenance.
5. Build held-out extraction/citation evaluations and then version/family scenarios.
6. Add customer inventory, scope preview, quarantine dashboard, metadata mapping, and sampled acceptance.
7. Add the first permissioned multilingual slice and publish language-specific metrics.

## Success criteria

- A fresh environment can recreate the same demo corpus and processing versions without manual database edits.
- Every demo source has visible provenance and a reviewed right-to-use entry.
- The demo exercises real workflows rather than static screenshots or hard-coded values.
- Evaluation failures block release according to risk-tier thresholds.
- A pilot administrator can reconcile every scoped source file to ingested, excluded, quarantined, failed, or deleted state.
- Customer onboarding does not create live obligations until source quality and reviewer acceptance gates pass.

## External references

- The Atticus Project describes [CUAD](https://www.atticusprojectai.org/cuad/) as 510 real commercial contracts with over 13,000 labels across 41 clause categories and publishes it under CC BY 4.0.
- The CUAD source and dataset documentation are available from the [Atticus Project GitHub repository](https://github.com/TheAtticusProject/cuad/).
- The SEC documents its no-auth, real-time filing data in the [EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and publishes additional [developer resources](https://www.sec.gov/about/developer-resources).

## Non-goals

- Treating public availability as a blanket commercial license.
- Mixing confidential customer contracts into a public demo or shared evaluation corpus.
- Presenting synthetic families as real agreements.
- Optimizing benchmark scores on one dataset and claiming general enterprise accuracy.
- Enabling autonomous workflows before an onboarding quality gate.
