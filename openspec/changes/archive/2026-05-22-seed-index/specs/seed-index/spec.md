## ADDED Requirements

### Requirement: Synthetic chunk seeding with configurable count
`seed_index.py` SHALL generate and upload N synthetic chunks directly to the
Azure AI Search `document-chunks` index. Each chunk SHALL conform to the existing
index schema with a random unit vector in the `embedding` field and a `synthetic-`
prefixed ID.

#### Scenario: Seed completes successfully
- **WHEN** `seed_index.py --chunks 50000` is run with valid credentials
- **THEN** 50,000 documents are uploaded to the index, progress is printed per
  batch, and a final summary shows total chunks uploaded and elapsed time

#### Scenario: Partial batch on last iteration
- **WHEN** `--chunks` is not a multiple of the batch size
- **THEN** the final batch contains the remainder and all chunks are uploaded

#### Scenario: Missing environment variable exits cleanly
- **WHEN** `AZURE_SEARCH_ENDPOINT` or `AZURE_SEARCH_INDEX` is not set
- **THEN** the script exits with a clear error message naming the missing variable

---

### Requirement: Synthetic chunks are identifiable and deletable
All synthetic chunks SHALL use IDs prefixed with `synthetic-` so they can be
filtered and removed without affecting real indexed documents.

#### Scenario: Delete mode removes only synthetic chunks
- **WHEN** `seed_index.py --delete` is run
- **THEN** all documents whose `id` starts with `synthetic-` are removed from
  the index, real documents are untouched, and a count of deleted chunks is printed

#### Scenario: Delete with no synthetic chunks is a no-op
- **WHEN** `seed_index.py --delete` is run against an index with no synthetic chunks
- **THEN** the script exits cleanly reporting 0 documents deleted

---

### Requirement: Random unit vectors match embedding field dimensions
Each synthetic chunk's `embedding` field SHALL contain a 1536-dimensional unit
vector generated from a random normal distribution and L2-normalised, matching
the dimension configured in the index schema.

#### Scenario: Vector dimension matches index schema
- **WHEN** a synthetic chunk is uploaded and then retrieved
- **THEN** its `embedding` field (if retrieved) has exactly 1536 floats

#### Scenario: Vectors are approximately unit length
- **WHEN** a random vector is generated
- **THEN** its L2 norm is within 0.001 of 1.0 after normalisation

---

### Requirement: Progress reporting during seeding
`seed_index.py` SHALL print batch-level progress so the operator can monitor
long-running seeding operations.

#### Scenario: Progress printed per batch
- **WHEN** seeding is in progress
- **THEN** each uploaded batch prints: batch number, chunks in batch,
  cumulative total, elapsed time, and upload rate (chunks/sec)

#### Scenario: Final summary on completion
- **WHEN** seeding completes
- **THEN** a summary line prints total chunks uploaded, total elapsed time,
  and a reminder to wait 2–5 minutes before running the load test
