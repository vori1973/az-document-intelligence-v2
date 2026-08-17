# AGENTS.md

Guidance for AI coding agents working in this repository.

## Spec-driven workflow (OpenSpec)

This project uses [OpenSpec](https://github.com/Fission-AI/OpenSpec). Specs are the source of truth for behavior; code follows them.

**Before writing code for any non-trivial change, create an OpenSpec change.** Non-trivial means: a new capability, a change to observable behavior, a new external dependency, or anything touching the pipeline's contract with the search index.

| Intent | Do this |
|---|---|
| New feature or behavior change | `/opsx-propose` — creates `proposal.md`, `specs/`, `design.md`, `tasks.md` |
| Implement an approved change | `/opsx-apply` — work `tasks.md` top to bottom, checking off as you go |
| Finish and fold specs into the baseline | `/opsx-archive` |
| Think through an idea first | `/opsx-explore` |

The equivalent skills in `.github/skills/` carry the full instructions — read the relevant one before acting.

Useful commands:

```bash
openspec list                         # active changes
openspec list --specs                 # baseline capabilities
openspec status --change "<name>"     # artifact progress
openspec validate "<name>" --strict   # validate before implementing
openspec show "<name>"
```

**Rules**
- Do not start implementing until `openspec validate <name> --strict` passes.
- Specs describe *observable behavior*, not implementation. No class names, no library choices, no step-by-step plans — those belong in `design.md`.
- Scenarios need exactly four hashes (`#### Scenario:`). Three fails silently.
- Keep `tasks.md` checkboxes current as you implement; that file is the progress record.
- Bug fixes, typos, and pure refactors do not need a change proposal.

Established baseline specs live in `openspec/specs/`. Read the relevant one before modifying behavior it covers.

## Project shape

Python Azure **Durable Functions** pipeline (v2 programming model) that ingests PDFs and indexes them into Azure AI Search for RAG.

```
src/
  function_app.py              # every activity must be registered here
  orchestrators/               # durable orchestration
  activities/                  # step1..step7 pipeline stages
  triggers/                    # Event Grid ingest + delete
  shared/                      # auth, blob, telemetry helpers
  models/types.py              # pydantic contracts between steps
infra/                         # Bicep modules (hand-written, not azd)
scripts/deploy.sh              # infra deployment
tests/{unit,integration}/
openspec/                      # specs and change proposals
docs/                          # design documents
```

Pipeline: `step1_preanalysis → step2_adi → step3_router → [extract_page ×N] → [ocr_page ×N] → step4a_figures → step4c_understanding → step5_chunks → step6_embed → step7_search`

## Conventions

- **Adding an activity** requires three edits: the module in `activities/`, an import plus `@app.activity_trigger` in `function_app.py`, and a `call_activity_with_retry` in the orchestrator. Missing any one fails silently at runtime.
- **Every step writes `stepN-result.json`** to `processing/{doc_id}/{run_id}/`. This is a specified requirement (`openspec/specs/step-result-files/`), not a convention — the absence of the file means the step did not succeed.
- **Managed identity only.** No keys, no connection strings in app settings. Use the helpers in `shared/auth.py`.
- **Never hand-edit Azure resources.** Change the Bicep and redeploy. Out-of-band portal changes have silently broken deployments here before.
- Inter-step data passes as blob artifacts, not orchestrator payloads. Activity inputs are small JSON contexts (`doc_id`, `run_id`, `blob_name`).

## Commands

```bash
.venv/bin/python -m pytest tests/ -q        # unit tests
az bicep build --file infra/main.bicep      # validate IaC
./scripts/deploy.sh                          # deploy infra
func azure functionapp publish docintv2-dev-func --python   # deploy code
```

Run the unit suite before considering a change done.

## Gotchas

- **Document identity is content-derived.** Re-uploading a PDF whose bytes are unchanged is silently skipped. To force reprocessing, clear that document's `processing/_name-index/` entry first.
- **App Insights telemetry is currently not flowing.** Diagnose runs via the Durable Functions storage tables instead (`az storage entity query -t docpipelineInstances --auth-mode login ...`).
- Storage key auth is disabled; storage CLI calls need `--auth-mode login` plus a data-plane RBAC role.
- ADI reports geometry in **inches**; PyMuPDF works in **points** (×72).
