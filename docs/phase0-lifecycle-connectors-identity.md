# Phase 0 Lifecycle, Language, Connector, and Identity Foundations

Every new upload now creates a stable `LogicalDocument` and an immutable `DocumentVersion`. A later upload can name the same logical document to create the next version while retaining the original source object, content hash, source-system revision, detected BCP-47 language tag, and processing snapshot. API deletion soft-deletes the searchable document while preserving version lineage and governed evidence.

The language boundary performs Unicode NFC normalization and conservative script-based detection without pretending to translate legal text. Translation providers must preserve the original text, source offsets, target language, provider, and processing provenance when added. Human review remains required for multilingual legal extraction.

The connector control plane stores provider, scopes, external tenant, secret-manager credential reference, cursor, webhook subscription, health, and an idempotent inbound event ledger. It deliberately stores no OAuth refresh token in PostgreSQL. Google Drive, Gmail, SharePoint, OneDrive, Dropbox, and Box adapters can build on these provider-neutral records without weakening tenant isolation.

Enterprise identity foundations include individually revocable service accounts whose high-entropy secret is shown once and only hashed at rest, plus SAML/SCIM directory configuration and group-to-role mappings. SAML assertion processing should be delegated to the configured enterprise identity provider and consumed through Termnova's verified OIDC boundary. A standards-complete SCIM endpoint remains integration work and must pass provider conformance testing before being advertised as supported.
