## Context

Each pipeline activity currently logs key metrics to App Insights (page count, table count, chunk count, duration) and writes domain-specific blobs (`adi-raw.json`, `chunks.json`, etc.). However, there is no consistent, glanceable status file per step. To diagnose a failure today you must correlate the Durable Functions instance state in the Azure portal with App Insights log queries.

`step1_preanalysis` already writes a `step1-result.json` summary. Steps 2–7 do not. This design extends that pattern consistently across the pipeline.

## Goals / Non-Goals

**Goals:**
- Each activity writes a `stepN-result.json` to `processing/{doc_id}/{run_id}/` on success
- The file contains the same metrics already logged (no new computation)
- The pattern matches `step1-result.json` exactly (same helper, same location)

**Non-Goals:**
- Changing what data is computed or how it flows between steps
- Adding failure/error artifacts (Durable Functions already surfaces retry state; App Insights captures exceptions)
- Modifying the orchestrator, trigger, or pipeline context model
- Modifying existing blobs (`adi-raw.json`, `adi-content.md`, `chunks.json`, etc.)

## Decisions

### D1: Use the existing `upload_json` blob helper, same pattern as step1

`step1_preanalysis` calls `upload_json(ctx, "step1-result.json", {...})`. Each activity will call the same function with `"stepN-result.json"` and a dict of its key metrics.

**Alternative considered:** Append to a shared `pipeline-status.json` on each step completion. Rejected — concurrent writes from fan-out activities (extract_page, ocr_page) would require optimistic locking or a separate aggregation step. The per-step file is simpler and atomic.

### D2: Write only on success, not on failure

The file's presence is the success signal. Its absence means the step either hasn't run or failed — both states are actionable. Writing a failure file would duplicate what App Insights already captures and add branching to every activity's error path.

### D3: Content matches what is already logged to App Insights

No new data is computed. The dict written to the result file mirrors the keyword arguments passed to `log_step_end` (duration_ms, counts, flags). This keeps the implementation to a one-liner addition per activity.

### D4: step4 (extract_page / ocr_page fan-out) is excluded

`extract_page` and `ocr_page` are fan-out leaf activities that execute per page. Writing one file per page would produce N blobs with overlapping names unless the filename encodes page number, which adds complexity. The routing step (step3) and chunk step (step5) already summarize the overall fan-out outcome. A per-fan-out result file is out of scope.

## Risks / Trade-offs

- **Extra blob writes per run**: 5 additional PUT requests (< 1 KB each). Negligible cost and latency impact.
- **Result file not written if activity throws before reaching the write call**: This is intentional (D2) — absence = failure signal. The write is the last line of the happy path.

## Migration Plan

- Change is purely additive. No existing blobs are renamed.
- No redeployment of infrastructure required — code-only change.
- Rollback: revert the 5 activity files and redeploy. Old runs in the processing container are unaffected.
