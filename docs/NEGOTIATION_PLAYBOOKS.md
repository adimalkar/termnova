# Negotiation Playbook Copilot

Termnova playbooks turn approved legal positions into a governed, repeatable redline review process. They are intentionally deterministic: assessment results do not depend on an LLM call and can be reproduced from the playbook revision and negotiation change evidence.

## Lifecycle

1. Create a draft with one position per clause category.
2. Revise the draft until legal and business owners approve it.
3. Activate it. Termnova automatically archives the prior active playbook for the same organization and contract type.
4. Assess a tracked negotiation version. The version must belong to a negotiation track with the same contract type.
5. Use the immutable assessment snapshot for approval routing and audit evidence.

Active and archived playbooks cannot be edited. Create a new draft when policy language changes. Assessments bind the playbook revision, negotiation version, observed change, contract document, approved position, reviewer identity, and timestamp.

## Position semantics

Each clause position supports:

- preferred language;
- multiple acceptable variants;
- fallback language;
- required and prohibited terms;
- a configurable similarity threshold;
- risk and approval levels; and
- optional provenance pointing to an approved source document, page, and clause.

Evaluation precedence is prohibited term, missing required term, preferred language, acceptable language, fallback language, then outside playbook. Preferred and acceptable results do not require approval. Fallback results use the configured approval level. Prohibited, uncovered, and outside-playbook language always requires approval.

## API

- `POST /api/v1/playbooks` creates a draft.
- `GET /api/v1/playbooks` lists playbooks and supports `contract_type` and `status` filters.
- `GET /api/v1/playbooks/{id}` returns positions and provenance.
- `PATCH /api/v1/playbooks/{id}` revises a draft and increments its revision.
- `POST /api/v1/playbooks/{id}/activate` approves a revision.
- `POST /api/v1/playbooks/{id}/archive` retires it.
- `POST /api/v1/playbooks/{id}/assessments` assesses a negotiation version.
- `GET /api/v1/playbooks/assessments/{id}` retrieves the immutable result.

All routes are authenticated and tenant-scoped. Writes require the existing `document:write` permission. Every lifecycle mutation and assessment appends an audit event. PostgreSQL row-level security protects all four playbook tables.

## Assessment evidence

Every finding includes the negotiation change ID and document ID for the observed redline. When the approved position cites a source, the finding also snapshots its document, page, and clause references. Suggested language is always taken from the approved playbook; it is never generated ad hoc.

The current increment operates on clause changes already produced by the negotiation version processor. A later UI increment can present findings inline in the Redline screen and connect approval-required findings to workflow tasks without changing the assessment contract.
