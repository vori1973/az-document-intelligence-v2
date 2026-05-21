## 1. Understand existing pattern

- [x] 1.1 Read `src/activities/step1_preanalysis.py` to confirm how `step1-result.json` is written (what helper, what fields, where in the function)
- [x] 1.2 Read `src/shared/blob_client.py` to confirm the `upload_json` (or equivalent) helper signature

## 2. Implement result files in each activity

- [x] 2.1 `step2_adi.py` — write `step2-result.json` with: `pages`, `tables`, `figures`, `low_conf_pages`, `duration_ms`
- [x] 2.2 `step3_router.py` — write `step3-result.json` with: `adi_only`, `ocr_pages`, `low_conf_tables`, `ocr_enabled`
- [x] 2.3 `step5_chunks.py` — write `step5-result.json` with: `paragraphs`, `table_rows`, `figures`, `total`
- [x] 2.4 `step6_embed.py` — write `step6-result.json` with: `chunks`, `batches`, `duration_ms`
- [x] 2.5 `step7_search.py` — write `step7-result.json` with: `indexed`, `index_action` (`created`/`updated`), `duration_ms`

## 3. Verify

- [x] 3.1 Upload a test PDF and confirm all 7 `stepN-result.json` files appear in the processing run folder
- [x] 3.2 Confirm existing blobs (`adi-raw.json`, `chunks.json`, etc.) are still present and unmodified
