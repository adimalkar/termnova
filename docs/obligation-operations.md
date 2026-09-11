# Obligation Operations

This is the first Phase 2 control-tower slice. It turns a human-approved or corrected contract fact
into accountable work without severing the chain back to the executed source.

## Guarantees

- One obligation is materialized per verified source fact. Repeating the request returns the same
  obligation instead of creating duplicate work.
- The obligation permanently records the source fact, logical document, immutable document version,
  clause occurrence, and processing snapshot that created it.
- Owner assignment accepts only an active membership in the same organization.
- Every mutation uses an expected revision, so two reviewers cannot silently overwrite each other.
- Obligation events and organization audit events record creation, assignment, acknowledgement,
  evidence decisions, transitions, and reopening. Database triggers make obligation history
  append-only and prevent submitted evidence from being deleted or silently replaced.
- PostgreSQL row-level security isolates both obligations and their event history by organization.
- API responses include the original clause text, page, and character span.
- Fulfillment files use the governed object-storage path: server-side size and content validation,
  quarantine, malware scanning, encryption inventory, retention policy, and tenant-scoped download.
- Completion is blocked until every configured evidence type and minimum accepted count is met.
  Regulated, explicitly controlled, or configured high-value obligations require a reviewer other
  than the submitter to accept the evidence.

## API workflow

1. A reviewer approves or corrects a fact in `POST /api/v1/verification/facts/{id}/decisions`.
2. A workflow manager calls `POST /api/v1/obligations/from-facts/{fact_id}` with an optional owner,
   due date, recurrence rule, escalation policy, business unit, and evidence requirements.
3. Managers can assign or reassign work with `PATCH /api/v1/obligations/{id}/assignment`.
4. The assigned owner acknowledges it with `POST /api/v1/obligations/{id}/acknowledgements`.
5. The owner or manager uploads proof with `POST /api/v1/obligations/{id}/evidence`; identical
   content is idempotent and returns the existing evidence record.
6. Legal or procurement reviewers decide pending evidence at
   `POST /api/v1/obligations/{id}/evidence/{evidence_id}/decisions`.
7. Authorized users list and download evidence through tenant-scoped API endpoints; raw storage
   keys are never exposed.
8. The owner or a workflow manager uses `POST /api/v1/obligations/{id}/transitions` to block,
   complete, waive, supersede, or reopen it. Completion enforces the configured evidence policy.
9. Reviewers and auditors can reconstruct the history at
   `GET /api/v1/obligations/{id}/events`.

All mutation requests after creation require `expected_revision`. A stale request returns HTTP 409.
Invalid transitions return HTTP 422, and owner-only actions return HTTP 403.

## Role boundaries

- Legal and procurement reviewers can read, create, assign, act, submit evidence, and independently
  accept or reject evidence.
- Obligation owners can read, act on assigned work, and submit evidence, but cannot reassign work or
  accept evidence.
- Auditors and read-only users can inspect obligations and evidence without mutating them.
- Administrators retain all permissions.

## Deliberately deferred Phase 2 increments

This slice stores recurrence policy without generating independently tracked occurrences. Recurring
instances, reminders/escalations, bulk assignment rules, evidence-package export, and external
action delivery belong in separate reviewable PRs built on this foundation.
