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
- Recurring obligations materialize into independently owned and completed instances. Each instance
  freezes the source obligation revision, document version, recurrence policy, evidence policy, and
  owner and monetary exposure that applied when it was generated, so later contract or workflow
  edits do not rewrite historical work.
- Recurrence expansion requires an explicit IANA timezone, accepts bounded RFC 5545 rules with
  daily, weekly, monthly, or yearly frequency, and limits each request to a 366-day window and 500
  occurrences. Materialization is idempotent for an obligation and scheduled timestamp.
- A globally locked automation pass maintains a 90-day rolling occurrence window every 15 minutes.
  It creates idempotent reminder, due, and configured escalation alerts, cancels alerts when their
  work becomes terminal, and writes alert delivery to the transactional outbox in the same commit.
- Recurring instances freeze lead time and escalation policy along with their other source
  snapshots. Later edits therefore affect future materialization without silently changing alerts
  or attestations for an already-generated occurrence.
- This increment deliberately accepts only the `in_app` channel. Email, calendar, Slack/Teams,
  Jira, and webhook adapters must consume the durable `obligation.alert.ready` outbox contract in
  later integration PRs rather than pretending an external delivery happened.

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
9. For recurring work, a manager calls
   `POST /api/v1/obligations/{id}/instances/materialize` with timezone-aware window boundaries.
   Owners operate each occurrence through `POST /api/v1/obligations/{id}/instances/{instance_id}/transitions`.
   Evidence can be scoped to an occurrence by including `obligation_instance_id` in the evidence
   upload; proof from one occurrence never completes another.
10. Consumers list occurrences at `GET /api/v1/obligations/{id}/instances` and reconstruct an
   occurrence history at `GET /api/v1/obligations/{id}/instances/{instance_id}/events`.
11. Reviewers and auditors can reconstruct the parent history at
   `GET /api/v1/obligations/{id}/events`.
12. Owners list their alert feed at `GET /api/v1/obligations/alerts`. Workflow managers and auditors
    can request the organization view with `mine=false`; other roles remain recipient-scoped.
13. A recipient or workflow manager acknowledges a ready alert at
    `POST /api/v1/obligations/alerts/{alert_id}/acknowledgements` using its expected revision.

## Escalation policy contract

`escalation_policy.steps` accepts at most ten distinct, ordered `after_days` values between 0 and
3650. Each step targets `owner`, `legal-reviewer`, `procurement-reviewer`, or `administrator` and
currently uses `channel: in_app`. Unsupported fields, recipients, channels, duplicate delays, and
unbounded delays are rejected before the obligation is created. An owner-targeted alert for
unassigned work falls back to the procurement-reviewer role instead of disappearing.

The scheduled command is safe to replay:

```bash
python -m termnova.obligations.automation --horizon-days 90 --lookback-days 30
```

One PostgreSQL advisory lock prevents overlapping global runs. Tenant failures are isolated and
reported with a non-zero exit code after the remaining organizations have been processed.

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

Bulk assignment rules, evidence-package export, digests/calendar views, and external action
delivery belong in separate reviewable PRs built on this foundation. The in-app alert feed and
transactional outbox are now present; no external channel should be advertised until its adapter
records an actual delivery receipt.
