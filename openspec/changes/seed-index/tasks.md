## 1. Script scaffold

- [ ] 1.1 Create `scripts/load-test/seed_index.py` with shebang, docstring, and CLI argument parsing: `--chunks`, `--batch-size`, `--delete`
- [ ] 1.2 Add env var validation for `AZURE_SEARCH_ENDPOINT` and `AZURE_SEARCH_INDEX` with clear exit messages

## 2. Vector generation

- [ ] 2.1 Implement `random_unit_vector(dims=1536)` — draw from standard normal, L2-normalise to unit length
- [ ] 2.2 Implement `make_synthetic_chunk(seq: int) -> dict` — build a full schema-conformant document with `synthetic-` prefix IDs, placeholder text fields, and a random unit vector

## 3. Seeding

- [ ] 3.1 Implement `seed(client, chunks, batch_size)` — loop, generate batches, upload via `SearchClient.upload_documents`, print per-batch progress (batch N, cumulative, elapsed, chunks/sec)
- [ ] 3.2 Print final summary: total chunks uploaded, elapsed time, reminder to wait 2–5 minutes before load testing

## 4. Delete mode

- [ ] 4.1 Implement `delete_synthetic(client)` — search for all `id` starting with `synthetic-` (paged), collect IDs, delete in batches, print count deleted
- [ ] 4.2 Handle the no-op case: if 0 synthetic chunks found, exit cleanly with a message

## 5. README update

- [ ] 5.1 Add a "Step 0 — Seed the Index (optional)" section to `scripts/load-test/README.md` explaining when and why to seed, the `--chunks` guidance table, and the `--delete` cleanup step
- [ ] 5.2 Add `Search Index Data Contributor` to the RBAC table in the README (seeding requires write access, not just read)

## 6. Verify

- [ ] 6.1 Run `seed_index.py --chunks 1000` — confirm 1,000 documents appear in the index and progress output is correct
- [ ] 6.2 Run `seed_index.py --delete` — confirm synthetic chunks are removed and real documents are untouched
- [ ] 6.3 Run `load_test.py --concurrency 60 --profile hybrid` after seeding 50,000 chunks — confirm p95 latency increases and 429s appear
