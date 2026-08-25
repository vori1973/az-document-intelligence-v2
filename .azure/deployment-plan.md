# Deployment Plan - add-document-derived-prompt (Issue #9)

**Status:** Validated

## Mode

**MODIFY** - publish application code to the existing development Function App.
No Azure infrastructure or application settings change in this deployment.

## Scope

Deploy commit `b80d608` from `master` to validate OpenSpec change
`add-document-derived-prompt` against the technique guide and product
catalog documents already ingested in the dev environment.

Changed runtime files:

- `src/models/types.py`
- `src/activities/step4a_figures.py`
- `src/activities/step4c_understanding.py`

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
5. Reprocess the technique guide and product catalog and compare
   description-quality signals against baseline.

## Validation Checks

- [x] Confirm current Azure subscription matches the target subscription.
- [x] Confirm `docintv2-dev-func` exists in `docintv2-dev-rg` and is running.
- [x] Confirm no infrastructure files changed in commit `b80d608`.
- [x] Run `.venv/bin/python -m pytest tests/ -q`.
- [x] Confirm Azure Functions Core Tools is installed.

## Post-Deploy Acceptance

- [x] Reprocess the technique guide; compare generic-opener rate (baseline 59%) and unlabelled rate (baseline 20%).
- [x] Reprocess the product catalog; compare generic-opener rate (baseline 26%) and unlabelled rate (baseline 46%).
- [x] Manually review at least 20 changed descriptions per document for unsupported identity, measurement, or procedure claims.
- [x] Confirm figures with genuinely unreadable artwork still populate `uncertainty` rather than asserting a context-derived term.
- [x] Verify a document containing instruction-like text does not alter model behavior.
- [x] Record before/after rates and manual review outcome in the change folder.

## Risks

- Description text changes for already-ingested documents only on reprocessing.
- Prompt token cost rises modestly (context is text-only, bounded to 600 chars).
- Central risk: document vocabulary could be misapplied to artwork that doesn't show it — mitigated by the recognition/assertion rule, unchanged grounding rules, and the mandatory manual review gate before archiving.

## Validation Proof

- `az account show` → subscription `6384661b-af38-401c-8609-337e5042460d` matches target.
- `az functionapp show --name docintv2-dev-func --resource-group docintv2-dev-rg` → `availabilityState: "Normal"`.
- `git show --stat b80d608` → no files under `infra/` changed.
- `.venv/bin/python -m pytest tests/ -q` → 207 passed.
- `func --version` → 4.10.0.
- `.venv/bin/python -m py_compile` on all three changed runtime files → succeeded.
- Diff of changed files vs. prior archived commit shows no new Azure SDK client
  imports or `.create_client`-style calls — no new RBAC role assignments required.
