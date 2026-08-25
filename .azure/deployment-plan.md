# Deployment Plan - add-missed-figure-detection (Issue #6)

**Status:** Validated

## Mode

**MODIFY** - deploy new infra params/app settings via `az deployment group create`,
then publish application code to the existing development Function App.

## Scope

Deploy commit `5b366f9` from `master` to validate OpenSpec change
`add-missed-figure-detection`: recovers figures ADI's reader misses on
image-heavy or scanned pages by cross-checking PDF placement geometry.

Changed runtime files:

- `src/models/types.py`
- `src/activities/step1_preanalysis.py`
- `src/activities/step4a_figures.py`
- `src/activities/step4c_understanding.py`
- `src/activities/step5_chunks.py`

Changed infra files:

- `infra/main.bicep`
- `infra/modules/functions.bicep`

New app settings: `FIGURE_RECOVERY_ENABLED`, `FIGURE_RECOVERY_OVERLAP_THRESHOLD`,
`FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD`.

Tests and OpenSpec artifacts are committed but are not runtime deployment inputs.

## Target Environment

| Item | Value |
|---|---|
| Subscription | `6384661b-af38-401c-8609-337e5042460d` (ME-MngEnvMCAP545510-ivorobeychik-1) |
| Resource Group | `docintv2-dev-rg` |
| Region | East US |
| Function App | `docintv2-dev-func` |

## Deployment Recipe

**Type:** Azure CLI, targeted infra deployment + code publish (not the full
`scripts/deploy.sh` onboarding flow — no new resources or Foundry key needed).

1. Confirm Azure CLI authentication and target subscription.
2. Confirm the unit suite and `az bicep build` pass.
3. `az deployment group create --resource-group docintv2-dev-rg --template-file infra/main.bicep --parameters infra/parameters/dev.bicepparam --parameters deployerPrincipalId=<signed-in-user-oid> figureRecoveryEnabled=true`.
4. Publish code with `func azure functionapp publish docintv2-dev-func --python`.
5. Confirm the Function App is running and new app settings applied.
6. Reprocess the 16-page clinical reference (`162000-159772.pdf`) and confirm
   pages 6 and 8 produce recovered figures; reprocess the remaining corpus.

## Validation Checks

- [x] Confirm current Azure subscription matches the target subscription.
- [x] Confirm `docintv2-dev-func` exists in `docintv2-dev-rg` and is running.
- [x] Run `python3 -m pytest tests/unit -q` (235 passed).
- [x] Run `az bicep build --file infra/main.bicep` (passed).
- [x] Confirm Azure Functions Core Tools is installed (`func --version` → 4.10.0).

## Post-Deploy Acceptance

- [x] `az deployment group create` succeeded (`provisioningState: Succeeded`).
- [x] New app settings (`FIGURE_RECOVERY_ENABLED=true`, `FIGURE_RECOVERY_OVERLAP_THRESHOLD=0.30`, `FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD=0.85`) confirmed present on the Function App.
- [x] `func azure functionapp publish` succeeded; host status `Running`.
- [x] Reprocessed `162000-159772.pdf` — pages 6 and 8 produced recovered figures (`recovered: 2`, `recovered_qualified: 2`), existing 9 ADI figures unchanged (`provenance: "reader"`).
- [x] Visually verified both recovered crops match the source photographs.
- [x] Retrieval query against the live search index surfaced the recovered figure (`source: "pdf-placement-recovery"`) as the top result.
- [x] Reprocessed the remaining 7 demo documents (clearing `_name-index` entries where needed); recorded corpus-wide recovery counts (49 qualified recoveries across 331 pages).
- [x] Full results recorded in `openspec/changes/add-missed-figure-detection/validation-results.md`.

## Risks

- Recovered figures add extra step4a/step4c LLM calls only on pages flagged
  cross-check-eligible (scanned/image-heavy pages), bounded by
  `FIGURE_SCANNED_PAGE_COVERAGE_THRESHOLD`.
- Central risk: false-positive recovery (decorative/logo images promoted to
  figures) — mitigated by the existing qualification filters, which already
  suppressed most raw placement candidates on image-heavy catalog documents
  in this validation round (e.g. 93 raw → 31 qualified on the Surface catalog).
- `FIGURE_RECOVERY_ENABLED=true` is left enabled in dev after this validation;
  no change to the documented default (`false`) for new environments.

## Validation Proof

- `az account show` → subscription `6384661b-af38-401c-8609-337e5042460d` matches target.
- `az functionapp show --name docintv2-dev-func --resource-group docintv2-dev-rg` → `state: "Running"`.
- `python3 -m pytest tests/unit -q` → 235 passed.
- `az bicep build --file infra/main.bicep` → succeeded.
- `az deployment group create` → `provisioningState: "Succeeded"`.
- `az functionapp config appsettings list` → recovery settings present with correct values.
- `func azure functionapp publish docintv2-dev-func --python` → "The deployment was successful!", host status `Running`.
- Blob listing under `processing/4743525acc23b572/414b4f146641/` shows full step1–step7 artifacts including `figures/p6-fig9.png` and `figures/p8-fig10.png`.
- `step4a-result.json` for the primary case: `{"recovered": 2, "recovered_qualified": 2}`.
- `chunks.json` entries for both recovered figures show `source: "pdf-placement-recovery"` with real captions and bounding polygons.
- REST search query (AAD-authenticated) for "golf bag person carrying" against `document-chunks` index returned the recovered figure as top hit.
- Corpus-wide reprocessing of 7 additional documents completed with recovery
  stats recorded in `validation-results.md`.
