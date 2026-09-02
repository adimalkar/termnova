# Governed Document Storage

Uploads pass through a quarantine boundary before ingestion:

1. The filename is normalized and its allowed extension is checked.
2. The bytes are structurally validated as PDF, DOCX, or UTF-8 text. The HTTP content type is not trusted.
3. The original is written beneath the organization's quarantine prefix.
4. ClamAV scans the byte stream when enabled. Infected or indeterminate files never reach the parser.
5. A clean object is promoted to the immutable-version location and inventoried in `stored_objects` with its hash, detected MIME type, scan result, encryption mode, retention date, and legal-hold state.
6. Only then is the tenant-bound ingestion job submitted.

Production deployments should use an S3-compatible versioned bucket, block public access, and set `SECURE_UPLOADS_REQUIRED=true`. This startup gate requires both object storage and ClamAV. S3 writes request server-side encryption; `aws:kms` additionally requires `STORAGE_KMS_KEY_ID`.

Downloads first resolve the document and stored-object record under PostgreSQL RLS. S3 backends return a short-lived presigned URL. Local development streams the object through the authenticated API.

Deletion is denied while an object has a legal hold or unexpired retention timestamp. The denied request and reason are persisted and audited. Organization administrators manage retention policies and object holds through `/api/v1/governance`.
