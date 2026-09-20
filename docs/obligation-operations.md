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
  transitions, and reopening. Database triggers make obligation history append-only.
- PostgreSQL row-level security isolates both obligations and their event history by organization.
- API responses include the original clause text, page, and character span.

## API workflow

1. A reviewer approves or corrects a fact in `POST /api/v1/verification/facts/{id}/decisions`.
2. A workflow manager calls `POST /api/v1/obligations/from-facts/{fact_id}` with an optional owner,
   due date, recurrence rule, escalation policy, business unit, and evidence requirements.
3. Managers can assign or reassign work with `PATCH /api/v1/obligations/{id}/assignment`.
4. The assigned owner acknowledges it with `POST /api/v1/obligations/{id}/acknowledgements`.
5. The owner or a workflow manager uses `POST /api/v1/obligations/{id}/transitions` to block,
   complete, waive, supersede, or reopen it.
6. Reviewers and auditors can reconstruct the history at
   `GET /api/v1/obligations/{id}/events`.

All mutation requests after creation require `expected_revision`. A stale request returns HTTP 409.
Invalid transitions return HTTP 422, and owner-only actions return HTTP 403.

## Role boundaries

- Legal and procurement reviewers can read, create, assign, and act on obligations.
- Obligation owners can read and act on assigned work but cannot reassign it.
- Auditors and read-only users can inspect obligations and evidence without mutating them.
- Administrators retain all permissions.

## Deliberately deferred Phase 2 increments

This slice records evidence requirements but does not yet upload or accept fulfillment evidence. It
also stores recurrence policy without generating independently tracked occurrences. Evidence
artifacts and acceptance, recurring instances, reminders/escalations, bulk assignment rules, and
external action delivery belong in separate reviewable PRs built on this foundation.
