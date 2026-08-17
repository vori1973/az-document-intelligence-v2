#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Full deployment for az-document-intelligence-v2
#
# Usage:
#   ./scripts/deploy.sh [dev|prod]
#
# Prerequisites:
#   az login                  # authenticated Azure CLI
#   func --version            # Azure Functions Core Tools installed
#
# Step 1 (manual, one-time):
#   Create Azure AI Foundry resource + Mistral OCR deployment in the portal,
#   then update infra/parameters/<env>.bicepparam with the foundryEndpoint.
# =============================================================================

set -euo pipefail

ENV="${1:-dev}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PARAMS_FILE="${REPO_ROOT}/infra/parameters/${ENV}.bicepparam"

if [[ ! -f "${PARAMS_FILE}" ]]; then
  echo "ERROR: Parameter file not found: ${PARAMS_FILE}"
  exit 1
fi

# ── Read baseName from bicepparam ─────────────────────────────────────────
BASE_NAME=$(grep "param baseName" "${PARAMS_FILE}" | sed "s/.*= '//;s/'.*//")
LOCATION=$(grep "param location" "${PARAMS_FILE}" | sed "s/.*= '//;s/'.*//")
RESOURCE_GROUP="${BASE_NAME}-rg"

echo "=============================================="
echo "  Deploying: ${ENV}"
echo "  Base name: ${BASE_NAME}"
echo "  Location:  ${LOCATION}"
echo "  RG:        ${RESOURCE_GROUP}"
echo "=============================================="

# ── Step 1: Check Foundry endpoint is set (skip when OCR disabled) ───────
OCR_ENABLED_PARAM=$(grep "param ocrEnabled" "${PARAMS_FILE}" 2>/dev/null | sed "s/.*= '//;s/'.*//" || echo "true")
if [[ "${OCR_ENABLED_PARAM}" != "false" ]] && grep -q "<foundry-resource>" "${PARAMS_FILE}"; then
  echo ""
  echo "ERROR: foundryEndpoint still contains placeholder in ${PARAMS_FILE}"
  echo ""
  echo "Before running this script:"
  echo "  1. Go to https://ai.azure.com → Create project → Model catalog"
  echo "  2. Search 'mistral-ocr' → Deploy → Classic deployment"
  echo "  3. Copy the endpoint URL and update ${PARAMS_FILE}"
  echo "     param foundryEndpoint = 'https://<your-resource>.services.ai.azure.com'"
  echo "  -- OR -- set param ocrEnabled = 'false' to skip Mistral for now."
  echo ""
  exit 1
fi
if [[ "${OCR_ENABLED_PARAM}" == "false" ]]; then
  echo "  NOTE: ocrEnabled=false — Mistral OCR will be skipped (ADI-only mode)."
fi

# ── Step 2: Create resource group ────────────────────────────────────────
echo ""
echo "[1/5] Creating resource group '${RESOURCE_GROUP}'..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --output none
echo "      OK"

# ── Step 3: Deploy Bicep (all resources except Foundry) ──────────────────
echo ""
echo "[2/5] Deploying Bicep infrastructure..."
DEPLOYER_OID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || echo "")
DEPLOYMENT_OUTPUT=$(az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${REPO_ROOT}/infra/main.bicep" \
  --parameters "${PARAMS_FILE}" \
  --parameters deployerPrincipalId="${DEPLOYER_OID}" \
  --output json)

echo "      OK"

# ── Step 4: Extract outputs ───────────────────────────────────────────────
FUNCTION_APP_NAME=$(echo "${DEPLOYMENT_OUTPUT}" | jq -r '.properties.outputs.functionAppName.value')
KEY_VAULT_NAME=$(echo "${DEPLOYMENT_OUTPUT}"    | jq -r '.properties.outputs.keyVaultName.value')
ADI_ENDPOINT=$(echo "${DEPLOYMENT_OUTPUT}"      | jq -r '.properties.outputs.adiEndpoint.value')
AOAI_ENDPOINT=$(echo "${DEPLOYMENT_OUTPUT}"     | jq -r '.properties.outputs.aoaiEndpoint.value')
SEARCH_ENDPOINT=$(echo "${DEPLOYMENT_OUTPUT}"   | jq -r '.properties.outputs.searchEndpoint.value')
STORAGE_URL=$(echo "${DEPLOYMENT_OUTPUT}"       | jq -r '.properties.outputs.storageAccountUrl.value')

echo ""
echo "  Function App : ${FUNCTION_APP_NAME}"
echo "  Key Vault    : ${KEY_VAULT_NAME}"
echo "  ADI endpoint : ${ADI_ENDPOINT}"
echo "  AOAI endpoint: ${AOAI_ENDPOINT}"
echo "  Search       : ${SEARCH_ENDPOINT}"
echo "  Storage      : ${STORAGE_URL}"

# ── Step 5: Store Foundry key in Key Vault ────────────────────────────────
# Grant the deploying user Key Vault Secrets Officer so they can write secrets
DEPLOYER_OID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || \
               az account show --query user.name -o tsv | xargs -I{} az ad user show --id {} --query id -o tsv 2>/dev/null || echo "")
KV_RESOURCE_ID=$(az keyvault show --name "${KEY_VAULT_NAME}" --resource-group "${RESOURCE_GROUP}" --query id -o tsv)
if [[ -n "${DEPLOYER_OID}" ]]; then
  echo ""
  echo "  Granting Key Vault Secrets Officer to deploying user..."
  az role assignment create \
    --role "Key Vault Secrets Officer" \
    --assignee-object-id "${DEPLOYER_OID}" \
    --assignee-principal-type User \
    --scope "${KV_RESOURCE_ID}" \
    --output none 2>/dev/null || true
  echo "  Waiting 15s for RBAC propagation..."
  sleep 15
fi

echo ""
if [[ "${OCR_ENABLED_PARAM}" == "false" ]]; then
  echo "[3/5] Skipping Foundry key (OCR disabled) — storing placeholder..."
  # Non-fatal: the placeholder is unused while OCR is disabled, and org policy
  # may force publicNetworkAccess=Disabled on the vault, blocking CLI writes.
  if az keyvault secret set \
    --vault-name "${KEY_VAULT_NAME}" \
    --name "foundry-key" \
    --value "placeholder-ocr-disabled" \
    --output none 2>/dev/null; then
    echo "      OK (placeholder stored; update when OCR is enabled)"
  else
    echo "      SKIPPED (vault not reachable from here; unused while OCR disabled)"
  fi
else
  echo "[3/5] Storing Foundry key in Key Vault '${KEY_VAULT_NAME}'..."
  echo ""
  echo "  You need to paste the Mistral OCR endpoint key from the Foundry portal."
  echo "  (AI Foundry → your project → Settings → Keys and Endpoint)"
  echo ""
  read -r -s -p "  Foundry API key: " FOUNDRY_KEY
  echo ""

  if [[ -z "${FOUNDRY_KEY}" ]]; then
    echo "  WARNING: No key entered — skipping Key Vault secret. Set it manually:"
    echo "  az keyvault secret set --vault-name ${KEY_VAULT_NAME} --name foundry-key --value <key>"
  else
    az keyvault secret set \
      --vault-name "${KEY_VAULT_NAME}" \
      --name "foundry-key" \
      --value "${FOUNDRY_KEY}" \
      --output none
    echo "      OK"
  fi
fi

# ── Step 6: Deploy Function App code ─────────────────────────────────────
echo ""
echo "[4/5] Deploying Function App code to '${FUNCTION_APP_NAME}'..."
cd "${REPO_ROOT}/src"
func azure functionapp publish "${FUNCTION_APP_NAME}" --python
cd "${REPO_ROOT}"
echo "      OK"

# ── Step 7: Wire Event Grid subscriptions (requires functions to exist) ───
SYSTEM_TOPIC_NAME=$(echo "${DEPLOYMENT_OUTPUT}" | jq -r '.properties.outputs.systemTopicName.value // empty')
if [[ -z "${SYSTEM_TOPIC_NAME}" ]]; then
  SYSTEM_TOPIC_NAME="${storageAccountName}-topic"
fi
STORAGE_ACCOUNT_NAME=$(echo "${STORAGE_URL}" | sed 's|https://||;s|\.blob.*||')
SYSTEM_TOPIC_NAME="${STORAGE_ACCOUNT_NAME}-topic"

echo ""
echo "[5/5] Creating Event Grid subscriptions..."

INGEST_RESOURCE_ID="/subscriptions/$(az account show --query id -o tsv)/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Web/sites/${FUNCTION_APP_NAME}/functions/ingest_trigger"
DELETE_RESOURCE_ID="/subscriptions/$(az account show --query id -o tsv)/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Web/sites/${FUNCTION_APP_NAME}/functions/delete_trigger"

az eventgrid system-topic event-subscription create \
  --name "ingest-pdf" \
  --resource-group "${RESOURCE_GROUP}" \
  --system-topic-name "${SYSTEM_TOPIC_NAME}" \
  --endpoint-type azurefunction \
  --endpoint "${INGEST_RESOURCE_ID}" \
  --included-event-types "Microsoft.Storage.BlobCreated" \
  --advanced-filter subject StringEndsWith ".pdf" \
  --advanced-filter subject StringBeginsWith "/blobServices/default/containers/documents/" \
  --max-delivery-attempts 30 \
  --event-ttl 1440 \
  --output none 2>/dev/null || \
az eventgrid system-topic event-subscription update \
  --name "ingest-pdf" \
  --resource-group "${RESOURCE_GROUP}" \
  --system-topic-name "${SYSTEM_TOPIC_NAME}" \
  --endpoint "${INGEST_RESOURCE_ID}" \
  --output none

az eventgrid system-topic event-subscription create \
  --name "delete-pdf" \
  --resource-group "${RESOURCE_GROUP}" \
  --system-topic-name "${SYSTEM_TOPIC_NAME}" \
  --endpoint-type azurefunction \
  --endpoint "${DELETE_RESOURCE_ID}" \
  --included-event-types "Microsoft.Storage.BlobDeleted" \
  --advanced-filter subject StringEndsWith ".pdf" \
  --advanced-filter subject StringBeginsWith "/blobServices/default/containers/documents/" \
  --output none 2>/dev/null || \
az eventgrid system-topic event-subscription update \
  --name "delete-pdf" \
  --resource-group "${RESOURCE_GROUP}" \
  --system-topic-name "${SYSTEM_TOPIC_NAME}" \
  --endpoint "${DELETE_RESOURCE_ID}" \
  --output none

echo "      OK"

# ── Step 8: Print summary ─────────────────────────────────────────────────
echo ""
echo "=============================================="
echo "  Deployment complete!"
echo "=============================================="
echo ""
echo "  Environment  : ${ENV}"
echo "  Resource group: ${RESOURCE_GROUP}"
echo ""
echo "  Endpoints:"
echo "    ADI          : ${ADI_ENDPOINT}"
echo "    OpenAI       : ${AOAI_ENDPOINT}"
echo "    AI Search    : ${SEARCH_ENDPOINT}"
echo "    Storage      : ${STORAGE_URL}"
echo ""
echo "  Next steps:"
echo "    - Upload a PDF to the 'documents' container to trigger the pipeline"
echo "    - Monitor runs (App Insights): az monitor app-insights query --apps ${FUNCTION_APP_NAME/func/ai} --resource-group ${RESOURCE_GROUP} --analytics-query 'traces | where timestamp > ago(30m) | order by timestamp desc | take 50' --output table"
echo "    - View logs: az monitor app-insights query ..."
echo ""
echo "  To run integration tests:"
echo "    RESOURCE_GROUP=${RESOURCE_GROUP} \\"
echo "    FUNCTION_APP=${FUNCTION_APP_NAME} \\"
echo "    SEARCH_ENDPOINT=${SEARCH_ENDPOINT} \\"
echo "    STORAGE_URL=${STORAGE_URL} \\"
echo "    .venv/bin/python -m pytest tests/integration/ -v"
echo ""
