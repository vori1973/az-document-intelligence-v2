from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_both_function_apps_enable_explicit_python_telemetry():
    ingestion = (ROOT / "infra/modules/functions.bicep").read_text()
    query = (ROOT / "infra/modules/query_functions.bicep").read_text()

    for source in (ingestion, query):
        assert "APPLICATIONINSIGHTS_CONNECTION_STRING" in source
        assert "PYTHON_APPLICATIONINSIGHTS_ENABLE_TELEMETRY" in source
        assert "OTEL_SERVICE_NAME" in source


def test_both_python_apps_include_azure_monitor_exporter():
    ingestion = (ROOT / "src/requirements.txt").read_text()
    query = (ROOT / "query/requirements.txt").read_text()

    assert "azure-monitor-opentelemetry==" in ingestion
    assert "azure-monitor-opentelemetry==" in query


def test_query_and_apim_deployment_fails_closed_without_auth_metadata():
    main = (ROOT / "infra/main.bicep").read_text()

    assert "var queryAuthConfigured = !empty(queryBackendClientId)" in main
    assert "var queryDeploymentEnabled = deployQuery && queryAuthConfigured" in main
    assert "var apimDeploymentEnabled = queryDeploymentEnabled && deployApim" in main
    assert "module queryFunctions" in main
    assert "if (queryDeploymentEnabled)" in main
    assert "module apim" in main
    assert "if (apimDeploymentEnabled)" in main
