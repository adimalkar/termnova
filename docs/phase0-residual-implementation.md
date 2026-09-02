# Phase 0 Residual Implementation Register

## Purpose

This register is the explicit handoff for Phase 0 work that cannot honestly be called production-complete yet. It separates code already delivered from infrastructure, provider integration, data, and operational proof that still require deployment credentials, licensed inputs, or production-like environments.

An item leaves this register only when its acceptance evidence is attached to a release record. A schema, interface, configuration field, or mocked test is a foundation—not proof that the corresponding enterprise control operates in production.

## Status vocabulary

- **Code gap:** more repository implementation is required.
- **External dependency:** credentials, vendor configuration, licensed data, or provisioned infrastructure is required.
- **Operational proof:** code exists, but a production-like drill or conformance test has not passed.
- **Policy decision:** the customer or operator must choose a supported policy before enforcement can be enabled.

## Residual work

| Area | Current foundation | Remaining implementation or proof | Reason still open | Acceptance evidence |
| --- | --- | --- | --- | --- |
| OIDC login lifecycle | JWT issuer, audience, key rotation, and verified actor boundary | Configure a real IdP, browser login/session lifecycle, logout, refresh/revocation behavior, and break-glass recovery | External dependency and operational proof | IdP conformance test; revoked and expired tokens fail; login/logout audit trail; recovery drill |
| SAML SSO | Directory connection metadata and group mapping records | Certified assertion validation through an IdP/broker, metadata rotation, replay protection, encrypted assertions where required, and IdP-initiated policy | External dependency and code gap | Interoperability tests against each supported IdP; replay/clock-skew/rotation security tests |
| SCIM | Directory connection and mapping substrate | Standards-complete Users/Groups endpoints, pagination, filtering, patch semantics, bearer-token rotation, deprovisioning, and provider conformance suites | Code gap | Okta/Entra conformance runs; deprovisioning removes access within the promised SLO |
| Service accounts | Create/revoke records with one-time secret display and hashed storage | Authenticate DB-backed service credentials, scoped rotation, last-used metadata, IP/network policy, and emergency revocation | Code gap | Create/use/rotate/revoke tests; revoked credentials fail immediately; every use is attributable |
| Resource-level authorization | Organization RBAC and tenant-scoped data access | Bind workspace membership to verified organization subjects and enforce document/folder/source ACL intersections where required | Code gap and policy decision | Cross-role and cross-workspace authorization matrix; source-permission revocation test |
| PostgreSQL RLS | Forced RLS policies and tenant transaction context | Run all production services under a non-owner, non-superuser application role and make the cross-tenant role probe a required CI/infrastructure test | External dependency and operational proof | Automated two-tenant test under the deployed application role; owner/superuser bypass alert |
| Durable object storage | Tenant-prefixed S3-compatible storage, quarantine, promotion, signed reads, encryption settings | Provision versioned buckets, KMS/customer keys, object lock where promised, regional placement, lifecycle rules, backup, and restore | External dependency and policy decision | Bucket-policy review; cross-tenant denial; key rotation; version restore; regional placement evidence |
| Secure intake | Structural MIME validation and ClamAV INSTREAM client | Run redundant ClamAV or an approved scanning service, maintain signatures, enforce `SECURE_UPLOADS_REQUIRED=true`, and define encrypted-file handling | External dependency and operational proof | Live clean/EICAR/encrypted/corrupt-file tests; fail-closed test; signature-age alert |
| Retention, deletion, and holds | Retention policy, deletion request, legal-hold-aware deletion controls | Scheduled retention executor, complete derived-artifact inventory, export/restore flow, approval policy, and object-lock verification | Code gap, external dependency, and policy decision | Timed deletion drill; legal hold blocks every copy; export and restore reconciliation |
| Jobs and dead letters | Durable job, snapshot, dead-letter, outbox, idempotent ingestion, and replay API | Add leased outbox dispatchers, heartbeat/stale-lease recovery, recurring reconciliation, poison-event policy, and dependency-aware replay | Code gap | Worker-kill recovery; duplicate delivery; out-of-order event; poison event; replay audit tests |
| Processing provenance | Processing snapshots on ingestion jobs and versions | Require snapshot/source-version references on every new extraction, translation, family decision, workflow, and calculation; backfill or mark legacy artifacts | Code gap | Database constraints and provenance completeness query return zero unexplained records |
| Evaluation corpus | Dataset loader, metrics, release thresholds, and CLI gate | Curate authorized contract-family and multilingual sets with obligation, evidence, negative, OCR, and high-risk labels | External dependency and data work | Versioned manifest; adjudicated holdout; slice metrics; release gate artifact |
| AI quality gates | Threshold configuration and regression runner | Add false-negative and calibration gates per obligation/risk/language slice, citation-span validation, prompt leakage checks, and rollback policy | Code gap and data work | A deliberately regressed build fails; approved build publishes reproducible metrics |
| Tenant operational controls | Organization usage-policy model and hard request ceiling | Load per-org policy, meter model tokens/cost, bound concurrent expensive jobs, expose budgets, and alert on SLO/cost exhaustion | Code gap | Concurrency and quota tests; budget cutoff; tenant dashboard; alert delivery test |
| Observability | Tracing and metrics foundations with redaction intent | Production collector/exporter, tenant-safe cardinality policy, redaction verification, SLO dashboards, alerts, and incident links | External dependency and operational proof | Synthetic incident reaches on-call; sampled traces contain no body text or secrets |
| Data/model routing | Provider-aware clients and organization foundation | Enforce per-tenant allowed model providers, zero-retention options, regions, fallback policy, and customer-managed routing restrictions | Code gap, external dependency, and policy decision | Denied-provider tests; route/fallback audit record; regional and retention attestations |
| Connector control plane | Connections, encrypted-secret field, scopes, cursors, webhook metadata, event ledger, and health | Provider OAuth flows, envelope encryption/key rotation, Drive/Gmail sync, webhook verification, permission mirroring, and periodic reconciliation | Phase 1 code gap and external dependency | Provider sandbox end-to-end tests including revoke, missed event, duplicate event, and ACL loss |
| Clause continuity | Stable clause identity table | Populate version-specific clause occurrences, align unchanged/modified clauses, preserve source spans, and measure alignment accuracy | Phase 1 code gap | Version fixture shows stable identities and correct add/modify/delete classification |
| Language services | Unicode normalization, conservative detection, and provider boundary | Page/clause BCP 47 detection, OCR routing, versioned translations, multilingual retrieval, glossary, locale parsing, and reviewer routing | Phase 1 code gap and external dependency | Published per-language/OCR slice metrics and bilingual evidence review tests |
| Recovery and release drills | Health checks and migration/release CI | Exercise database/object restore, credential revocation, queue replay, rollback, deletion, hold, and source permission loss on a schedule | Operational proof | Dated drill artifacts with RTO/RPO results, deviations, owner, and remediation date |

## Required ownership before production pilots

Each deployment must name accountable owners for identity, database/RLS, storage/KMS, malware scanning, connector credentials, privacy/retention, evaluation quality, and incident response. A single person may hold several roles in an early-stage company, but the responsibilities and evidence must remain separate.

## Phase 1 boundary

Phase 1 may build on the existing logical-document, version, connector, language, job, audit, and tenant-control foundations. It must not claim the residual provider or operational items above are complete merely because Phase 1 can exercise a local or mocked implementation.

The first Phase 1 increments should close the code gaps for clause continuity, source-version change classification, structured source-backed facts, verification decisions, and connector event reconciliation. Provider launches and quality claims remain gated by sandbox credentials and the authorized evaluation corpus.

## Exit procedure

For every release candidate:

1. Link each applicable row to a test, drill, dashboard, vendor configuration, or approved policy artifact.
2. Record environment, application revision, migration revision, actor, timestamp, and result.
3. Keep failures and waivers visible with an owner and expiry date.
4. Block production claims for any row whose promised behavior lacks evidence.
5. Preserve the evidence with the immutable release audit record.
