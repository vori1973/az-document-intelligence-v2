"""
Managed-identity Azure authentication for the query domain (task 2.1 / 3.3).

Production Azure auth MUST use `ManagedIdentityCredential`. Local development
may use `DefaultAzureCredential`, matching `src/shared/auth.py`'s pattern for
the ingestion app but deliberately narrower for the query app: this backend
should never fall through a broad credential chain in a deployed environment.

Environment selection:
  - `AZURE_FUNCTIONS_ENVIRONMENT=Development` (set by `func start` / Core Tools)
    selects `DefaultAzureCredential` for local development.
  - Anything else (including unset, which is what Azure sets in a deployed
    Function App) selects `ManagedIdentityCredential`.
  - `AZURE_CLIENT_ID`, when present, selects a user-assigned managed identity.
"""

from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import (
    DefaultAzureCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)

SEARCH_SCOPE = "https://search.azure.com/.default"
COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

_DEVELOPMENT_ENV_VALUE = "development"


def is_local_development(environment: str | None = None) -> bool:
    env_value = environment if environment is not None else os.environ.get(
        "AZURE_FUNCTIONS_ENVIRONMENT", ""
    )
    return env_value.strip().lower() == _DEVELOPMENT_ENV_VALUE


@lru_cache(maxsize=1)
def get_credential():
    """Return a shared, process-lifetime credential.

    Cached so repeated Search/OpenAI calls within the same Function App
    instance reuse one token cache rather than re-resolving identity per
    request.
    """
    if is_local_development():
        return DefaultAzureCredential()
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id:
        return ManagedIdentityCredential(client_id=client_id)
    return ManagedIdentityCredential()


def get_search_bearer_token(credential) -> str:
    return credential.get_token(SEARCH_SCOPE).token


def get_openai_token_provider(credential):
    return get_bearer_token_provider(credential, COGNITIVE_SERVICES_SCOPE)
