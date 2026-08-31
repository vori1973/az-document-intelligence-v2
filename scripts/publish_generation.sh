#!/usr/bin/env bash
# =============================================================================
# publish_generation.sh — guarded knowledge-generation publication
#                          (openspec: add-apim-exact-cache-demo, task 6.2)
#
# Publishing a new `knowledgeGeneration` is the correctness boundary for the
# exact-response cache (design.md, "Publish generation through trusted APIM
# configuration"): every cache key includes it, so bumping the value makes
# every prior cache entry unreachable without a bulk purge. Bumping it BEFORE
# the corpus is actually queryable would let the new generation serve (and
# cache) answers against an incomplete or inconsistent index — worse than not
# publishing at all.
#
# This script therefore does exactly one thing, and only after two independent
# checks both pass:
#
#   1. Ingestion completion  — the pipeline's own artifact contract
#      (processing/{docId}/{runId}/step7-result.json existing IS the
#      completion signal per AGENTS.md/openspec/specs/step-result-files) and,
#      when an orchestration instance ID is supplied, the Durable Functions
#      Instances table reports RuntimeStatus=Completed for it.
#   2. Successful queryability — a live probe question sent through
#      POST /rag/baseline (the uncached control arm — never the cached
#      operation) must return 200 and an answer/citation containing the
#      caller-supplied expected substring.
#
# Only then does it update the `rag-knowledge-generation` APIM named value.
# Any missing input or failed check exits non-zero and changes nothing
# (fail closed) — there is no "publish anyway" flag.
#
# Auth: entirely through the caller's own `az login` session (a real user or a
# pipeline's managed identity — this script never asks which). No credential
# is stored, defaulted, or accepted as an argument:
#   - Storage/table reads use `--auth-mode login` (Entra), matching
#     AGENTS.md's guidance that storage key auth is disabled repo-wide.
#   - The APIM named-value update uses ARM (`az apim nv`), authorized by the
#     caller's own Azure RBAC role on the APIM resource.
#   - The one non-ARM credential this script touches is the APIM subscription
#     key used to prove queryability through the gateway itself. It is read
#     into a shell variable via the APIM listSecrets ARM action, used once, and
#     never echoed, logged, or written to a file — pass --no-subscription-key
#     only for a deployment with apimSubscriptionRequired=false.
#
# Usage:
#   scripts/publish_generation.sh \
#     --resource-group      docintv2-dev-rg \
#     --apim-name            docintv2-dev-apim \
#     --storage-account      docintv2devst \
#     --doc-id                <content-derived doc id from the run> \
#     --run-id                <run id from the run> \
#     --probe-question       "What does the warranty cover?" \
#     --probe-expect          "warranty" \
#     --gateway-url           https://docintv2-dev-apim.azure-api.net \
#     --new-generation        2
#
# Optional:
#   --instance-id <id>          Also require this Durable orchestration instance
#                                to be RuntimeStatus=Completed in the Instances table.
#   --task-hub <name>            Durable Functions task hub (default: docpipeline,
#                                matching infra/modules/functions.bicep TASK_HUB_NAME).
#   --subscription-name <name>   APIM subscription used for the probe (default: rag-demo,
#                                matching infra/modules/apim.bicep).
#   --no-subscription-key         Skip subscription-key retrieval (apimSubscriptionRequired=false).
#   --timeout-seconds <n>         Probe HTTP timeout (default: 30).
#   --dry-run                     Run every check, print what would change, update nothing.
# =============================================================================

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: publish_generation.sh --resource-group RG --apim-name NAME \
         --storage-account ACCOUNT --doc-id ID --run-id ID \
         --probe-question TEXT --probe-expect TEXT \
         --gateway-url URL --new-generation VALUE \
         [--instance-id ID] [--task-hub NAME] [--subscription-name NAME] \
         [--no-subscription-key] [--timeout-seconds N] [--dry-run]

All of --resource-group, --apim-name, --storage-account, --doc-id, --run-id,
--probe-question, --probe-expect, --gateway-url, and --new-generation are
required. There is no default corpus, question, or generation value: an
incomplete command fails closed instead of guessing.
EOF
}

# ── Explicit inputs only — nothing here has a production-meaningful default ─
RESOURCE_GROUP=""
APIM_NAME=""
STORAGE_ACCOUNT=""
DOC_ID=""
RUN_ID=""
PROBE_QUESTION=""
PROBE_EXPECT=""
GATEWAY_URL=""
NEW_GENERATION=""
INSTANCE_ID=""
TASK_HUB="docpipeline"
SUBSCRIPTION_NAME="rag-demo"
USE_SUBSCRIPTION_KEY=1
TIMEOUT_SECONDS=30
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    --apim-name) APIM_NAME="$2"; shift 2 ;;
    --storage-account) STORAGE_ACCOUNT="$2"; shift 2 ;;
    --doc-id) DOC_ID="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --probe-question) PROBE_QUESTION="$2"; shift 2 ;;
    --probe-expect) PROBE_EXPECT="$2"; shift 2 ;;
    --gateway-url) GATEWAY_URL="$2"; shift 2 ;;
    --new-generation) NEW_GENERATION="$2"; shift 2 ;;
    --instance-id) INSTANCE_ID="$2"; shift 2 ;;
    --task-hub) TASK_HUB="$2"; shift 2 ;;
    --subscription-name) SUBSCRIPTION_NAME="$2"; shift 2 ;;
    --no-subscription-key) USE_SUBSCRIPTION_KEY=0; shift ;;
    --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unrecognized argument: $1" >&2; usage; exit 1 ;;
  esac
done

# ── Fail closed on missing required inputs ─────────────────────────────────
MISSING=()
[[ -z "${RESOURCE_GROUP}" ]] && MISSING+=("--resource-group")
[[ -z "${APIM_NAME}" ]] && MISSING+=("--apim-name")
[[ -z "${STORAGE_ACCOUNT}" ]] && MISSING+=("--storage-account")
[[ -z "${DOC_ID}" ]] && MISSING+=("--doc-id")
[[ -z "${RUN_ID}" ]] && MISSING+=("--run-id")
[[ -z "${PROBE_QUESTION}" ]] && MISSING+=("--probe-question")
[[ -z "${PROBE_EXPECT}" ]] && MISSING+=("--probe-expect")
[[ -z "${GATEWAY_URL}" ]] && MISSING+=("--gateway-url")
[[ -z "${NEW_GENERATION}" ]] && MISSING+=("--new-generation")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "ERROR: missing required argument(s): ${MISSING[*]}" >&2
  echo "" >&2
  usage >&2
  exit 1
fi

for tool in az curl jq; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "ERROR: required tool '${tool}' is not installed" >&2
    exit 1
  fi
done

# ── Fail closed unless the caller already has an authenticated az session ──
if ! az account show >/dev/null 2>&1; then
  echo "ERROR: not authenticated. Run 'az login' (or rely on the ambient" >&2
  echo "       managed identity in a pipeline agent) before publishing." >&2
  exit 1
fi

echo "=============================================="
echo "  Knowledge-generation publication"
echo "  Resource group : ${RESOURCE_GROUP}"
echo "  APIM           : ${APIM_NAME}"
echo "  Doc / run      : ${DOC_ID} / ${RUN_ID}"
echo "  New generation : ${NEW_GENERATION}"
[[ "${DRY_RUN}" -eq 1 ]] && echo "  Mode           : DRY RUN (no update will be made)"
echo "=============================================="

# ── Check 1: ingestion completion ──────────────────────────────────────────
echo ""
echo "[1/3] Verifying ingestion completion..."

RESULT_BLOB="${DOC_ID}/${RUN_ID}/step7-result.json"
BLOB_EXISTS=$(az storage blob exists \
  --auth-mode login \
  --account-name "${STORAGE_ACCOUNT}" \
  --container-name processing \
  --name "${RESULT_BLOB}" \
  --query exists -o tsv 2>/dev/null || echo "false")

if [[ "${BLOB_EXISTS}" != "true" ]]; then
  echo "ERROR: processing/${RESULT_BLOB} does not exist." >&2
  echo "       Step 7 (Azure AI Search indexing) has not completed for this" >&2
  echo "       doc/run — refusing to publish generation ${NEW_GENERATION}." >&2
  exit 1
fi
echo "      OK — processing/${RESULT_BLOB} exists"

if [[ -n "${INSTANCE_ID}" ]]; then
  INSTANCES_TABLE="${TASK_HUB}Instances"
  RUNTIME_STATUS=$(az storage entity query \
    --auth-mode login \
    --account-name "${STORAGE_ACCOUNT}" \
    --table-name "${INSTANCES_TABLE}" \
    --filter "PartitionKey eq '${INSTANCE_ID}'" \
    --select RuntimeStatus \
    -o json 2>/dev/null \
    | jq -r '.items[0].RuntimeStatus // empty')

  if [[ "${RUNTIME_STATUS}" != "Completed" ]]; then
    echo "ERROR: orchestration instance ${INSTANCE_ID} in ${INSTANCES_TABLE}" >&2
    echo "       has RuntimeStatus='${RUNTIME_STATUS:-<not found>}', not 'Completed'." >&2
    echo "       Refusing to publish generation ${NEW_GENERATION}." >&2
    exit 1
  fi
  echo "      OK — orchestration instance ${INSTANCE_ID} is Completed"
fi

# ── Check 2: successful queryability ───────────────────────────────────────
echo ""
echo "[2/3] Verifying the new corpus is queryable via /rag/baseline..."

AUTH_HEADER=()
if [[ "${USE_SUBSCRIPTION_KEY}" -eq 1 ]]; then
  # Read once, use once, never print, never write to a file.
  ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
  LIST_SECRETS_URL="https://management.azure.com/subscriptions/${ARM_SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.ApiManagement/service/${APIM_NAME}/subscriptions/${SUBSCRIPTION_NAME}/listSecrets?api-version=2024-05-01"
  SUBSCRIPTION_KEY=$(az rest \
    --method post \
    --url "${LIST_SECRETS_URL}" \
    --query primaryKey -o tsv 2>/dev/null || echo "")
  if [[ -z "${SUBSCRIPTION_KEY}" ]]; then
    echo "ERROR: could not read APIM subscription '${SUBSCRIPTION_NAME}'." >&2
    echo "       Confirm you have Reader access on ${APIM_NAME}, or pass" >&2
    echo "       --no-subscription-key if apimSubscriptionRequired=false." >&2
    exit 1
  fi
  AUTH_HEADER=(-H "Ocp-Apim-Subscription-Key: ${SUBSCRIPTION_KEY}")
fi

PROBE_BODY=$(jq -n --arg q "${PROBE_QUESTION}" '{question: $q}')
RAW_RESPONSE=$(curl -sS --max-time "${TIMEOUT_SECONDS}" \
  -w '\n%{http_code}' \
  -X POST "${GATEWAY_URL%/}/rag/baseline" \
  -H "Content-Type: application/json" \
  "${AUTH_HEADER[@]}" \
  -d "${PROBE_BODY}") || {
    echo "ERROR: probe request to ${GATEWAY_URL%/}/rag/baseline failed to complete." >&2
    exit 1
  }
unset SUBSCRIPTION_KEY

PROBE_STATUS="${RAW_RESPONSE##*$'\n'}"
PROBE_BODY_TEXT="${RAW_RESPONSE%$'\n'*}"

if [[ "${PROBE_STATUS}" != "200" ]]; then
  echo "ERROR: probe question returned HTTP ${PROBE_STATUS}, not 200." >&2
  echo "       Refusing to publish generation ${NEW_GENERATION}." >&2
  exit 1
fi

PROBE_MATCH=$(echo "${PROBE_BODY_TEXT}" | jq -r --arg s "${PROBE_EXPECT}" '
  ( ( .answer // "" ) | test($s; "i") ) or
  ( ( [ (.citations // [])[] .sourceFile ] | join(" ") ) | test($s; "i") )
' 2>/dev/null || echo "false")

if [[ "${PROBE_MATCH}" != "true" ]]; then
  echo "ERROR: probe response did not contain the expected substring '${PROBE_EXPECT}'" >&2
  echo "       in the answer or a citation source file. Refusing to publish." >&2
  exit 1
fi
echo "      OK — probe question answered from the corpus (HTTP 200, expected content present)"

# ── Publish ─────────────────────────────────────────────────────────────
echo ""
echo "[3/3] Publishing generation ${NEW_GENERATION}..."

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "      DRY RUN — would set named value 'rag-knowledge-generation' to '${NEW_GENERATION}'."
  echo "      Both checks passed; re-run without --dry-run to publish."
  exit 0
fi

PREVIOUS_GENERATION=$(az apim nv show \
  --resource-group "${RESOURCE_GROUP}" \
  --service-name "${APIM_NAME}" \
  --named-value-id rag-knowledge-generation \
  --query value -o tsv 2>/dev/null || echo "<unknown>")

az apim nv update \
  --resource-group "${RESOURCE_GROUP}" \
  --service-name "${APIM_NAME}" \
  --named-value-id rag-knowledge-generation \
  --value "${NEW_GENERATION}" >/dev/null

echo "      OK — rag-knowledge-generation: '${PREVIOUS_GENERATION}' -> '${NEW_GENERATION}'"
echo ""
echo "Requests using generation '${PREVIOUS_GENERATION}' are now cache misses; entries"
echo "from that generation expire by TTL and are never bulk-purged."
