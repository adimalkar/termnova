# Nemotron 2048-Dimension Embedding Migration

This release changes the semantic embedding space from 1536 dimensions to the
native 2048 dimensions emitted by `nvidia/nemotron-3-embed-1b:free`.
The database stores these vectors as `halfvec(2048)` because pgvector HNSW
indexes support at most 2,000 dimensions for the full-precision `vector` type.
The migration updates the installed pgvector extension before introducing the
`halfvec` column.

## Deployment order

1. Save the new Render variables without deploying them.
2. Deploy this release. Render runs `alembic upgrade head` before starting the
   new application revision.
3. Confirm the API health check succeeds.
4. Open a Render shell and count chunks requiring regeneration:

   ```bash
   python -m termnova.pipeline.reembed --dry-run
   ```

5. Regenerate vectors in resumable batches:

   ```bash
   python -m termnova.pipeline.reembed --batch-size 32
   ```

The migration preserves document and chunk text but deliberately sets existing
embeddings to `NULL`; vectors from different models cannot be converted or
meaningfully compared. Lexical full-text retrieval remains available while the
regeneration command is running.

The command commits after every batch and only selects chunks with a missing
embedding. It can be stopped and run again safely. Use `--max-chunks` to cap a
single run when operating under a provider request quota:

```bash
python -m termnova.pipeline.reembed --batch-size 32 --max-chunks 1600
```

## Rollback

Downgrading the Alembic revision returns the column to 1536 dimensions, but it
also invalidates 2048-dimensional vectors. A rollback therefore requires
regenerating embeddings with the former 1536-dimensional model.

## Render schema troubleshooting

For a service that was created manually rather than from the repository
Blueprint, also set **Settings -> Build & Deploy -> Pre-Deploy Command** to:

```bash
alembic upgrade head
```

If a deployed database reports that `chunks.content_tsv` is missing, deploy the
schema-reconciliation revision and confirm the migration from a Render shell:

```bash
alembic current
alembic upgrade head
alembic current
```

The reconciliation is idempotent: it restores the generated full-text column,
its GIN index, and the 2048-dimensional embedding column/index only when they
are missing or incompatible.
