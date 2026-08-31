"""Bicep contract tests for the query app, its RBAC, and the APIM gateway
(tasks 4.1 - 4.5, 5.1, 5.2, 6.1).

Static source assertions only — nothing here deploys or contacts Azure. They
protect the parts of the deployment whose failure mode is silent: a role
assignment that is broader than intended, an authentication setting that lets
anonymous traffic through, a named value the policies reference but nothing
creates, or an APIM SKU with no built-in cache.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INFRA = os.path.join(REPO_ROOT, "infra")
MODULES = os.path.join(INFRA, "modules")
POLICIES = os.path.join(INFRA, "policies")

MAIN = os.path.join(INFRA, "main.bicep")
QUERY_FUNCTIONS = os.path.join(MODULES, "query_functions.bicep")
QUERY_RBAC = os.path.join(MODULES, "query_rbac.bicep")
GATEWAY_IDENTITY = os.path.join(MODULES, "gateway_identity.bicep")
APIM = os.path.join(MODULES, "apim.bicep")

# Built-in role definition IDs. Wrong GUIDs deploy cleanly and fail at runtime.
SEARCH_INDEX_DATA_READER = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
COGNITIVE_SERVICES_OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
SEARCH_INDEX_DATA_CONTRIBUTOR = "8ebe5a00-799e-43f5-93ac-243d3dce84a7"
SEARCH_SERVICE_CONTRIBUTOR = "7ca78c08-252a-4471-8644-bb5ff32d4ba0"


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def app_setting_names(text: str) -> list[str]:
    return re.findall(r"\{\s*name:\s*'([^']+)'\s*,\s*value:", text)


# ── Query compute (task 4.1) ─────────────────────────────────────────────


def test_query_app_is_separate_from_the_ingestion_app():
    text = read(QUERY_FUNCTIONS)
    # Its own plan, its own storage account, its own identity.
    assert "Microsoft.Web/serverfarms" in text
    assert "param queryPlanName string" in text
    assert "Microsoft.Storage/storageAccounts@" in text
    assert "type: 'SystemAssigned'" in text

    main = read(MAIN)
    assert "var queryPlanName" in main
    assert "var planName" in main
    assert "queryPlanName: queryPlanName" in main


def test_query_app_capacity_is_configurable():
    text = read(QUERY_FUNCTIONS)
    for parameter in (
        "param maximumInstanceCount int",
        "param instanceMemoryMB int",
        "param httpPerInstanceConcurrency int",
        "param alwaysReadyInstanceCount int",
    ):
        assert parameter in text
    assert "maximumInstanceCount: maximumInstanceCount" in text
    assert "instanceMemoryMB: instanceMemoryMB" in text
    assert "perInstanceConcurrency: httpPerInstanceConcurrency" in text


def test_query_app_reuses_the_existing_application_insights():
    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" in read(QUERY_FUNCTIONS)
    main = read(MAIN)
    assert "appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString" in main
    # ... and the gateway logs to the same instance rather than a new one.
    assert "appInsightsId: monitoring.outputs.appInsightsId" in main
    assert "workspaceId: monitoring.outputs.workspaceId" in main


def test_query_app_settings_carry_no_keys_or_connection_strings():
    """spec: "Query dependency authentication" — managed identity only. The
    Application Insights connection string is the single documented exception."""
    settings = app_setting_names(read(QUERY_FUNCTIONS))
    assert settings, "expected app settings to be parsed"
    for name in settings:
        if name == "APPLICATIONINSIGHTS_CONNECTION_STRING":
            continue
        upper = name.upper()
        for forbidden in ("KEY", "SECRET", "PASSWORD", "CONNECTIONSTRING", "CONNECTION_STRING", "SAS"):
            assert forbidden not in upper, f"{name} looks like a credential setting"


def test_query_app_settings_match_the_application_configuration_contract():
    settings = set(app_setting_names(read(QUERY_FUNCTIONS)))
    expected = {
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_INDEX",
        "AZURE_SEARCH_API_VERSION",
        "AOAI_ENDPOINT",
        "AOAI_CHAT_DEPLOYMENT",
        "AOAI_EMBEDDING_DEPLOYMENT",
        "AOAI_API_VERSION",
        "QUERY_DEFAULT_TOP_K",
        "QUERY_MAX_QUESTION_LENGTH",
        "QUERY_DEFAULT_GENERATION",
        "QUERY_DEFAULT_SECURITY_SCOPE",
        "QUERY_DEFAULT_PROMPT_VERSION",
        "QUERY_DEFAULT_MODEL_VERSION",
    }
    missing = expected - settings
    assert not missing, f"query app is missing settings its config reads: {sorted(missing)}"


# ── Backend authentication (task 4.3) ────────────────────────────────────


def test_backend_authentication_rejects_unauthenticated_callers():
    text = read(QUERY_FUNCTIONS)
    assert "name: 'authsettingsV2'" in text
    assert "requireAuthentication: true" in text
    # An API must reject rather than redirect to an interactive login.
    assert "unauthenticatedClientAction: 'Return401'" in text
    assert "redirect" not in text.lower().split("unauthenticatedclientaction")[1][:200]


def test_backend_authentication_is_restricted_to_approved_applications():
    text = read(QUERY_FUNCTIONS)
    assert "defaultAuthorizationPolicy" in text
    assert "allowedApplications: allowedClientIds" in text
    assert "allowedAudiences: resolvedAudiences" in text
    assert "clientId: backendClientId" in text


def test_apim_identity_is_user_assigned_so_its_client_id_can_be_allow_listed():
    """A system-assigned identity has no client ID until its parent exists,
    which would force a manual post-deployment step."""
    identity = read(GATEWAY_IDENTITY)
    assert "Microsoft.ManagedIdentity/userAssignedIdentities" in identity
    assert "output clientId string = gatewayIdentity.properties.clientId" in identity

    main = read(MAIN)
    assert "gatewayIdentity!.outputs.clientId" in main
    assert "allowedClientIds: queryAllowedClientIds" in main
    assert "param queryBackendAdditionalAllowedClientIds array" in main


def test_auth_is_only_enabled_when_a_backend_application_is_supplied():
    main = read(MAIN)
    assert "var queryAuthConfigured = !empty(queryBackendClientId)" in main
    assert "var queryDeploymentEnabled = deployQuery && queryAuthConfigured" in main
    assert "authEnabled: true" in main
    assert "output queryBackendAuthEnabled bool" in main


def test_backend_audience_is_derived_from_the_backend_application():
    main = read(MAIN)
    assert "var queryBackendAudience = empty(queryBackendClientId) ? '' : 'api://${queryBackendClientId}'" in main
    assert "backendAudience: queryBackendAudience" in main


def test_managed_identity_token_issuer_matches_the_managed_identity_endpoint():
    """APIM's managed-identity token is a v1 token; validating it against the v2
    issuer would reject every gateway call."""
    text = read(QUERY_FUNCTIONS)
    assert "param authIssuer string = 'https://sts.windows.net/${subscription().tenantId}/'" in text
    assert "openIdIssuer: authIssuer" in text


# ── Least privilege (task 4.2) ───────────────────────────────────────────


def test_query_identity_gets_reader_level_data_plane_roles_only():
    text = read(QUERY_RBAC)
    assert SEARCH_INDEX_DATA_READER in text
    assert COGNITIVE_SERVICES_OPENAI_USER in text
    assert SEARCH_INDEX_DATA_CONTRIBUTOR not in text
    assert SEARCH_SERVICE_CONTRIBUTOR not in text
    assert text.count("Microsoft.Authorization/roleAssignments") == 2


def test_query_identity_has_no_access_to_ingestion_storage():
    """The query app gets its own host storage account, so the online query
    path cannot read ingested documents or processing artifacts."""
    main = read(MAIN)
    assert "var queryStorageAccountName" in main
    assert "queryStorageAccountName: queryStorageAccountName" in main
    storage_module = read(os.path.join(MODULES, "storage.bicep"))
    assert "query" not in storage_module.lower()


# ── APIM (tasks 5.1, 5.2, 6.1) ───────────────────────────────────────────


def test_default_sku_is_the_lowest_cost_tier_with_a_built_in_cache():
    text = read(APIM)
    assert "param sku string = 'BasicV2'" in text
    allowed = re.search(r"@allowed\(\[(.*?)\]\)\s*param sku", text, re.DOTALL)
    assert allowed is not None
    values = re.findall(r"'([A-Za-z0-9]+)'", allowed.group(1))
    assert "BasicV2" in values
    # The Consumption tier has no internal cache, so it can never satisfy the
    # cache-lookup-value / cache-store-value policies this demo depends on.
    assert "Consumption" not in values


def test_apim_uses_managed_identity_to_reach_the_backend():
    text = read(APIM)
    assert "type: 'SystemAssigned, UserAssigned'" in text
    assert "gatewayIdentityClientId" in text
    assert "rag-apim-identity-client-id" in text
    assert "authentication-managed-identity" in read(os.path.join(POLICIES, "rag-api.xml"))


def test_apim_defines_the_backend_api_and_both_demo_operations():
    text = read(APIM)
    assert "Microsoft.ApiManagement/service/backends@" in text
    assert "Microsoft.ApiManagement/service/apis@" in text
    assert "urlTemplate: '/baseline'" in text
    assert "urlTemplate: '/apim-built-in'" in text
    assert "path: 'rag'" in text
    assert text.count("Microsoft.ApiManagement/service/apis/operations@") == 2


def test_both_operations_resolve_to_the_same_backend_entity():
    """Identical backends are what makes the two operations comparable; the
    backend id is a contract between apim.bicep and the API policy."""
    apim = read(APIM)
    backend_name = re.search(r"var backendName = '([a-z0-9-]+)'", apim)
    assert backend_name is not None
    api_policy = read(os.path.join(POLICIES, "rag-api.xml"))
    assert f'<set-backend-service backend-id="{backend_name.group(1)}" />' in api_policy

    # Neither operation may point somewhere else.
    for policy in ("rag-baseline.xml", "rag-apim-built-in.xml"):
        operation_policy = read(os.path.join(POLICIES, policy))
        assert "set-backend-service" not in operation_policy
        assert '<rewrite-uri template="/internal/query"' in operation_policy


def test_operation_names_match_the_identifier_the_policy_branches_on():
    """rag-api.xml derives the reported cache type from context.Operation.Id."""
    apim = read(APIM)
    assert "var baselineOperationName = 'rag-baseline'" in apim
    assert "var builtInCacheOperationName = 'rag-apim-built-in'" in apim
    assert 'context.Operation.Id == "rag-apim-built-in"' in read(os.path.join(POLICIES, "rag-api.xml"))


def test_policies_are_loaded_from_the_checked_in_xml_files():
    text = read(APIM)
    for policy in ("rag-api.xml", "rag-baseline.xml", "rag-apim-built-in.xml"):
        assert f"loadTextContent('../policies/{policy}')" in text
    assert text.count("format: 'rawxml'") == 3


def test_every_named_value_referenced_by_a_policy_is_created_by_the_template():
    declared = set(re.findall(r"\{\s*name:\s*'(rag-[a-z0-9-]+)'\s*,\s*value:", read(APIM)))
    declared.add("rag-appinsights-connection-string")

    referenced: set[str] = set()
    for policy in ("rag-api.xml", "rag-baseline.xml", "rag-apim-built-in.xml"):
        referenced |= set(re.findall(r"\{\{([a-z0-9-]+)\}\}", read(os.path.join(POLICIES, policy))))

    missing = referenced - declared
    assert not missing, f"policies reference named values nothing creates: {sorted(missing)}"

    unused = declared - referenced - {"rag-appinsights-connection-string"}
    assert not unused, f"named values are created but never referenced: {sorted(unused)}"


def test_active_generation_is_deployment_managed_configuration():
    """task 6.1: the generation is trusted APIM configuration with a non-secret
    development default, never a caller-supplied value."""
    apim = read(APIM)
    assert "param knowledgeGeneration string = '0'" in apim
    assert "{ name: 'rag-knowledge-generation', value: knowledgeGeneration }" in apim
    assert "secret: false" in apim

    main = read(MAIN)
    assert "param knowledgeGeneration string = '0'" in main
    # The same value reaches the backend so a response reports the generation
    # that produced it.
    assert "knowledgeGeneration: knowledgeGeneration" in main
    assert "output activeKnowledgeGeneration string = knowledgeGeneration" in main


def test_apim_diagnostics_target_the_existing_monitoring_resources():
    text = read(APIM)
    assert "Microsoft.ApiManagement/service/loggers@" in text
    assert "loggerType: 'applicationInsights'" in text
    assert "loggerType: 'azureMonitor'" in text
    assert "Microsoft.Insights/diagnosticSettings@" in text
    assert "workspaceId: workspaceId" in text
    assert "httpCorrelationProtocol: 'W3C'" in text


def test_apim_diagnostics_never_capture_request_or_response_bodies():
    """spec: telemetry must not record raw questions, prompts, retrieved text,
    or cached response bodies."""
    text = read(APIM)
    assert "body:" not in text
    assert "logClientIp: false" in text


def test_only_the_application_insights_connection_string_is_marked_secret():
    text = read(APIM)
    assert text.count("secret: true") == 1
    assert "rag-appinsights-connection-string" in text
    assert "@secure()" in text


def test_apim_subscription_key_is_not_emitted_as_a_template_output():
    text = read(APIM)
    assert "listSecrets" not in text
    assert "primaryKey" not in text
    assert "param subscriptionRequired bool = true" in text


# ── main.bicep wiring (task 4.4) ─────────────────────────────────────────


def test_deployment_switches_default_to_off():
    main = read(MAIN)
    assert "param deployQuery bool = false" in main
    assert "param deployApim bool = false" in main
    assert "module queryFunctions './modules/query_functions.bicep' = if (queryDeploymentEnabled)" in main
    assert "module queryRbac './modules/query_rbac.bicep' = if (queryDeploymentEnabled)" in main
    assert "module apim './modules/apim.bicep' = if (apimDeploymentEnabled)" in main


def test_main_exposes_the_endpoints_and_identifiers_the_demo_needs():
    main = read(MAIN)
    for output in (
        "output queryFunctionAppName string",
        "output queryBackendUrl string",
        "output queryBackendAuthEnabled bool",
        "output gatewayIdentityClientId string",
        "output apimName string",
        "output apimGatewayUrl string",
        "output ragBaselineUrl string",
        "output ragBuiltInCacheUrl string",
        "output activeKnowledgeGeneration string",
    ):
        assert output in main, f"missing {output}"


def test_cache_dimensions_are_shared_between_gateway_and_backend():
    """The gateway is authoritative, but the backend must report the same
    dimensions or the demonstration contradicts itself."""
    main = read(MAIN)
    for parameter in ("knowledgeGeneration", "securityScope", "promptVersion", "logicalModelVersion"):
        assert main.count(f"{parameter}: {parameter}") == 2, (
            f"{parameter} should be passed to both the query app and APIM"
        )


def test_question_length_limit_is_shared_between_gateway_and_backend():
    main = read(MAIN)
    assert "maxQuestionLength: queryMaxQuestionLength" in main
    assert main.count("maxQuestionLength: queryMaxQuestionLength") == 2


def test_deploy_script_refuses_an_unauthenticated_query_backend():
    script = read(os.path.join(REPO_ROOT, "scripts", "deploy.sh"))
    assert "deployQuery" in script
    assert "queryBackendClientId" in script
    assert "func azure functionapp publish \"${QUERY_FUNCTION_APP}\"" in script


# ── Compilation ──────────────────────────────────────────────────────────


@pytest.mark.skipif(shutil.which("az") is None, reason="Azure CLI not available")
@pytest.mark.skipif(
    os.environ.get("SKIP_BICEP_BUILD") == "1", reason="SKIP_BICEP_BUILD=1"
)
def test_main_bicep_compiles_without_errors():
    result = subprocess.run(
        ["az", "bicep", "build", "--file", MAIN, "--stdout"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    # Warnings are tolerated; errors are not.
    assert " : Error " not in result.stderr
