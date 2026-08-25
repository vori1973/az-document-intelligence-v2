# Deployment Plan — add-vision-budget (Issue #8)

**Status:** Validated

## Mode

**MODIFY** — updating an existing, already-deployed environment. No new resources of note; this is a code + minor config update to a live Function App.

## Scope

Deploy the `issue-8-vision-budget` branch (OpenSpec change `add-vision-budget`) to the existing East US development environment so the four remaining acceptance tasks (technique guide re-run, product catalog re-run, placeholder-chunk verification, cost/wall-clock recording) can be completed against real documents.

This branch contains **no** Durable Task Scheduler changes — the paused `migrate-durable-task-scheduler` work (issue #10) lives only on the separate `issue-10-dts-migration` branch and is explicitly out of scope here. Storage-backed Durable Functions is unchanged.

## Target Environment

| Item | Value |
|---|---|
| Subscription | `6384661b-af38-401c-8609-337e5042460d` (ME-MngEnvMCAP545510-ivorobeychik-1) |
| Resource Group | `docintv2-dev-rg` (existing) |
| Region | East US |
| Function App | `docintv2-dev-func` (existing) |
| Search | `docintv2-dev-search` (existing, Standard SKU, 1 replica/partition) |
| Key Vault | `docintv2-dev-kv` (existing) |

## What Changes vs. Currently Deployed

- **Application code** (`src/activities/step4c_understanding.py`, `step4a_figures.py`, `step5_chunks.py`, `src/models/types.py`): document-derived vision budget (`min(pages*4, 500)`), round-robin page-balanced figure selection, per-document model tiering, placeholder-chunk suppression, `budget_bound` telemetry in `step4c-result.json`.
- **Infrastructure (`infra/`)**: security-hardening only —
  - `search.bicep`: remove invalid `authOptions` block now that `disableLocalAuth: true` is set (SKU stays `standard`, matching the live resource — no SKU change).
  - `openai.bicep`: figure-model deployment parameters (model tier selection support), serialized deployment ordering (`dependsOn`) to avoid `RequestConflict` on concurrent child deployments.
  - `functions.bicep` / `main.bicep`: new app settings for figure budget/model-tier configuration (e.g. figure count thresholds, model names per tier). No new resources, no breaking changes to existing settings.
  - `adi.bicep`, `keyvault.bicep`, `storage.bicep`: minor security-hardening carried over from the shared branch history (no functional change to this deployment).
- **`scripts/deploy.sh`**: one bug fix — corrected ordering so `STORAGE_ACCOUNT_NAME` is resolved before the Event Grid subscription step. No new deployment steps, no DTS gating logic (that only exists on the DTS branch).

## Out of Scope (explicitly excluded)

- Durable Task Scheduler migration (issue #10) — remains paused on `issue-10-dts-migration`.
- Any change to Search SKU/replica/partition (stays Standard, as currently live).
- Any new resource group or region (this is *not* a blue-green deploy — it updates the existing dev environment in place).

## Deployment Steps

1. `az bicep lint` + `az bicep build` on `infra/main.bicep` (static validation).
2. `azure-validate`: `az deployment group what-if` against `docintv2-dev-rg`, confirm 0 deletions, review Azure Policy compliance, static RBAC review.
3. `azure-deploy`: run `./scripts/deploy.sh dev` (or equivalent existing invocation for `docintv2-dev-rg`) — Bicep deploy, then `func azure functionapp publish docintv2-dev-func --python`, then Event Grid subscription wiring.
4. Post-deploy smoke check: confirm Function App is healthy and orchestrator responds.

## Validation Checks (All validation checks pass)

- [x] 1. Core Validation (CLI, auth, build, validate, what-if) — PASS. `validate-deployment.sh` summary: Create 7 / Modify 14 / Delete 16 (script's heuristic line-count, includes property-level removals). Cross-checked with structured `what-if` JSON (`changeType` field): **0 Create, 11 Modify, 0 Delete, 9 Unsupported (pre-existing role-assignment GUIDs, unrelated to this change), 6 NoChange, 1 Ignore**. No resource is created or deleted; every reported "Delete" line is a property removal (`authOptions` cleanup on Search, RAI policy/version-upgrade cleanup on OpenAI deployments, storage encryption-scope property removal, etc.), consistent with the security-hardening carried over from the shared branch history.
- [x] 2. Linting — `az bicep lint --file infra/main.bicep` — clean, no warnings/errors.
- [x] 3. Azure Policy Validation — `az policy state list --resource-group docintv2-dev-rg --filter "complianceState eq 'NonCompliant'"` returned pre-existing findings (diagnostic settings not enabled, TLS/network baseline checks) on resources this change does not touch functionally (adi, oai, storage, search, keyvault, function app). None of these are newly introduced by the #8 diff — same baseline as prior validations.
- [x] 4. RBAC / role verification review — grepped all `Microsoft.Authorization/roleAssignments` in `infra/`: identical set of least-privilege, resource-scoped roles (Cognitive Services User, OpenAI User, Storage Blob/Table/Queue Data Contributor, Search Index/Service Contributor, Key Vault Secrets User/Officer) as before. No new or elevated role assignments introduced by this branch.

**Validation Proof recorded:** 2026-08-24. Subscription `6384661b-af38-401c-8609-337e5042460d`, RG `docintv2-dev-rg`, template `infra/main.bicep` + `infra/parameters/dev.bicepparam`. OVERALL: PASS.

## Post-Deploy Verification (OpenSpec tasks 15, 20, 21, 23)

1. Submit the **technique guide** (72 pages) through ingestion; inspect `step4c-result.json` — confirm figures described past page 22, `budget_bound` reported correctly, and placeholder (`"[Figure] (Page N)"`) chunks are gone from the index (tasks 15/4.4, 20/6.2).
2. Submit the **product catalog** (159 pages, 195 qualified figures); confirm all 195 figures analyzed and `budget_bound: false` (task 21/6.3).
3. Record measured cost and wall-clock time for both runs in the change's documentation before archiving (task 23/6.5).

## Risks

- Existing production-ish Search resource is Standard SKU already deployed — Bicep must not attempt any drift-inducing SKU/capacity change. Confirmed in code review: this branch's `search.bicep` default SKU is `standard`, matching live state.
- Cost increase is expected and intentional (~2.2x per the OpenSpec design doc) — this is the accepted trade-off of the change, not a deployment risk.
- Orchestrator activity timeout should be checked against the higher figure-count ceiling (up to 500) per the design doc's noted risk; will monitor during the product catalog run.

## Section 7: Validation Proof

**Date:** 2026-08-24
**Subscription:** `6384661b-af38-401c-8609-337e5042460d` (ME-MngEnvMCAP545510-ivorobeychik-1)
**Resource Group:** `docintv2-dev-rg` (East US)
**Template:** `infra/main.bicep` + `infra/parameters/dev.bicepparam`

| Check | Command | Result |
|---|---|---|
| CLI installed | `az version` | PASS |
| Authenticated | `az account show` | PASS |
| Bicep build | `az bicep build --file infra/main.bicep` | PASS — compiles cleanly |
| Template validate | `az deployment group validate ...` | PASS |
| What-if | `az deployment group what-if --resource-group docintv2-dev-rg ...` | PASS — structured JSON: 0 Create, 11 Modify, 0 Delete, 9 Unsupported (pre-existing role-assignment GUIDs), 6 NoChange, 1 Ignore |
| Lint | `az bicep lint --file infra/main.bicep` | PASS — no warnings |
| Policy compliance | `az policy state list --resource-group docintv2-dev-rg --filter "complianceState eq 'NonCompliant'"` | Pre-existing findings only (diagnostics/TLS baseline); none newly introduced by this change |
| RBAC static review | `grep -rn roleDefinitionId infra/` | PASS — same least-privilege role set as before, no new/elevated assignments |
| Test suite | `.venv/bin/python -m pytest tests/ -q` | PASS — 169 passed |

**Overall: PASS.** No resource deletions. Safe to proceed to deployment.

## Approval

- [x] User has approved this plan (subscription + region confirmed, MODIFY scope, no DTS involvement).
