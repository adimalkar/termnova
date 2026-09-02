# Operational Control Plane

Every ingestion submission now creates durable database state before broker publication:

- `processing_snapshots` fingerprints the application, parser, chunking, embedding, model, prompt, and schema versions used for the run.
- `background_jobs` holds the idempotency key, broker task ID, attempt count, status, payload, timestamps, and last bounded error.
- `outbox_events` records the publication intent in the same transaction as the document and job. Published state is recorded after broker acceptance; unpublished entries remain discoverable for a dispatcher or operator.
- `dead_letters` retain terminal failures and replay history. Administrators can inspect jobs and snapshots and explicitly replay supported dead letters through `/api/v1/operations`.

Workers restore the organization RLS context before reading either the job or document. Broker task-result expiry therefore does not erase operational history, and a task cannot silently process another tenant's document.

Organization request budgets are keyed by internal organization ID in Redis. Per-IP SlowAPI protection remains an outer abuse-control layer. Database-backed `organization_usage_policies` provide the durable configuration boundary for concurrency, request, token, and cost limits; request enforcement currently uses the configured hard organization ceiling.

The evaluation runner accepts `--thresholds data/eval/release_thresholds.json` and exits non-zero when a release falls below a required metric or sample count. The threshold manifest also declares required future slices for contract type, obligation type, language, scan quality, and risk tier. Those slices require licensed or customer-authorized labeled examples before they can honestly become release gates.
