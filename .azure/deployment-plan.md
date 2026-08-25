# Deployment Plan - fix-figure-qualification-thresholds (Issue #7)

**Status:** Validated

## Mode

**MODIFY** - publish application code to the existing development Function App.
No Azure infrastructure or application settings change in this deployment.

## Scope

Deploy commit `0246759` from `master` to validate OpenSpec change
`fix-figure-qualification-thresholds` against the 159-page product catalog.

Changed runtime files:

- `src/activities/step4a_figures.py`
- `src/models/types.py`

Tests and OpenSpec artifacts are committed but are not runtime deployment inputs.

## Target Environment

| Item | Value |
|---|---|
| Subscription | `6384661b-af38-401c-8609-337e5042460d` (ME-MngEnvMCAP545510-ivorobeychik-1) |
| Resource Group | `docintv2-dev-rg` |
| Region | East US |
| Function App | `docintv2-dev-func` |

## Deployment Recipe

**Type:** Azure CLI, code-only Azure Functions publish.

1. Confirm Azure CLI and Functions Core Tools authentication and target.
2. Confirm the unit suite passes.
3. Publish with `func azure functionapp publish docintv2-dev-func --python`.
4. Confirm the Function App is running and its root endpoint responds.
5. Reprocess the product catalog and validate qualification artifacts.

## Validation Checks

- [x] Confirm current Azure subscription matches the target subscription.
- [x] Confirm `docintv2-dev-func` exists in `docintv2-dev-rg` and is running.
- [x] Confirm no infrastructure files changed in commit `0246759`.
- [x] Run `.venv/bin/python -m pytest tests/unit/ -q`.
- [x] Confirm Azure Functions Core Tools is installed.

## Post-Deploy Acceptance

- [x] Reprocess the 159-page product catalog.
- [x] Confirm all 59 repeated logo instances are rejected as `repeated_furniture`.
- [x] Confirm the 46 formerly size-rejected product figures qualify.
- [x] Confirm the 16 formerly aspect-rejected product figures qualify.
- [x] Confirm downstream figure descriptions and indexed chunks include recovered figures.

## Risks

- Vision call volume increases because legitimate figures now qualify.
- Existing documents require reprocessing before the recovered figures reach Search.
- This updates the existing development Function App in place.

## Section 7: Validation Proof

**Date:** 2026-08-25

| Check | Command | Result |
|---|---|---|
| Subscription | `az account show` | PASS - target subscription `6384661b-af38-401c-8609-337e5042460d` |
| Function App | `az resource show ... Microsoft.Web/sites` | PASS - `docintv2-dev-func` state is `Running` |
| Functions | `az functionapp function list` | PASS - 15 functions registered, including `step4a_figures` |
| Runtime diff | `git show --name-only 0246759` | PASS - no `infra/` files changed |
| Unit suite | `.venv/bin/python -m pytest tests/unit/ -q` | PASS - 176 tests |
| Python compile | `.venv/bin/python -m compileall -q src` | PASS |
| Core Tools | `func --version` | PASS - 4.10.0 |
| RBAC static review | Search `roleDefinitionId` in `infra/` | PASS - existing resource-scoped managed-identity assignments; unchanged by this commit |

The Function App's bare root URL timed out during the pre-deploy probe, but the
Azure resource reports `Running` and the management API returned all registered
functions. Post-deploy verification will use the management API and pipeline
execution rather than treating the non-function root route as a health endpoint.

## Approval

- [x] User approved commit, deployment, live validation, then archive.

## Deployment Result

**Deployed:** 2026-08-25

- Commit `0246759` published successfully to `docintv2-dev-func`.
- Function host state: `Running`; all 15 functions registered.
- Live RBAC assignments include the required Search, Storage, Key Vault, ADI,
  and Azure OpenAI data-plane roles for the Function App managed identity.
- Validation run: `c5fd986a2f8ddc63/7471a299a490`.
- Step 4A: 330 figures, 257 qualified, 73 rejected.
- Rejections: 59 `repeated_furniture`, 14 `structural_noise`.
- All 46 formerly `low_value_graphic` and all 16 formerly
  `decorative_geometry` product figures qualified and were retained by vision.
- Step 5 produced 253 figure chunks; Step 7 indexed 2,757 total chunks.
- All 62 recovered product-figure chunks were confirmed present in Azure AI
  Search.
- Temporary validation upload and mapping were removed without deleting the
  validated processing run or the original catalog mapping.

**Function App:** https://docintv2-dev-func.azurewebsites.net
