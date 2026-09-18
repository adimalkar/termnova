# Contract Family Intelligence

Termnova contract families group stable logical documents rather than uploaded files. This means an MSA, SOW, DPA, order form, amendment, or addendum remains in the same family when a connector or user uploads a new revision.

## Governing model

- Each active logical document belongs to at most one active family.
- The root agreement is created with the family; related agreements declare their role, relationship, parent, effective period, precedence, and optional fact-type scope.
- Default precedence is MSA 100, other 150, DPA 200, SOW/order form 300, and amendment/addendum 400. API clients can set an explicit value when contract language requires a different order.
- An empty `applies_to` scope means the agreement can govern every extracted fact type. A non-empty scope limits its effect to those fact types.
- Only facts from each member's active immutable version are considered. By default, only reviewer-approved or corrected facts can become effective.

For each term key, the highest-precedence verified value is effective. Different lower-precedence values are retained as overridden alternatives with exact document, version, page, clause text, language, confidence, and review status. Different values at the same highest precedence create an unresolved conflict; Termnova does not guess. A reviewer can select the controlling source, which updates membership precedence and records an immutable audit event.

## API

- `POST /api/v1/graph/families` creates a family from a document.
- `POST /api/v1/graph/families/{family_id}/members` adds a related logical document.
- `PATCH /api/v1/graph/families/{family_id}/members/{membership_id}` changes precedence, scope, dates, or status.
- `GET /api/v1/graph/families/{family_id}/intelligence` returns members, effective terms, alternatives, and conflicts as of a date.
- `GET /api/v1/graph/families/by-document/{document_id}` resolves the family from any current or historical upload.

The Family screen uses these endpoints to create governed families, add related agreements, inspect controlling provisions with source evidence, and resolve equal-precedence conflicts.

## Deployment

Run `alembic upgrade head` before serving this release. The migration creates tenant-protected `contract_families` and `contract_family_memberships` tables with PostgreSQL row-level security and an active-membership uniqueness constraint. Existing graph links remain available; they are not silently promoted into governed families because relationship direction, precedence, and scope require review.
