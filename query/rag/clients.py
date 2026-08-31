"""
Managed-identity Azure AI Search / Azure OpenAI client construction
(task 2.1 / 3.3).

No API keys or connection strings — every client is built from the shared
credential in `rag.auth`.
"""

from __future__ import annotations

from openai import AzureOpenAI

from .auth import get_openai_token_provider, get_search_bearer_token
from .config import QueryConfig


def build_search_headers(credential) -> dict:
    """Bearer-token headers for direct Azure AI Search REST calls.

    A raw `requests` call (rather than the `azure-search-documents` SDK) is
    used deliberately so hybrid retrieval matches `scripts/demo.py`'s proven
    request shape exactly (task 2.1) — see `rag.retrieval.hybrid_search`.
    """
    token = get_search_bearer_token(credential)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_aoai_client(credential, config: QueryConfig) -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=config.aoai_endpoint,
        azure_ad_token_provider=get_openai_token_provider(credential),
        api_version=config.aoai_api_version,
    )
