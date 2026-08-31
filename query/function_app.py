"""
Azure Functions entry point for the RAG Query API (task 3.1).

Deliberately a separate, non-Durable Python Function App from
`src/function_app.py`: independent scaling, deployment, identity, and
availability from the ingestion pipeline (see
`openspec/changes/add-apim-exact-cache-demo/design.md`, "Deploy a separate
Python Function App for online queries").

Auth level is ANONYMOUS at the Functions-runtime layer because the trust
boundary for this backend is App Service Authentication/Authorization scoped
to the APIM gateway's managed identity (configured in
`infra/modules/query_functions.bicep`), not a function key.
"""

import azure.functions as func

from rag.route import handle_query_request

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


@app.route(route="internal/query", methods=["POST"])
def query(req: func.HttpRequest) -> func.HttpResponse:
    return handle_query_request(req)
