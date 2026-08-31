"""
Environment-driven configuration for the query Function App (task 3.1 / 3.3).

No keys or connection strings — only endpoints, deployment/model names, and
non-secret demo defaults. Managed-identity clients are constructed separately
in `rag.clients` using `rag.auth`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SEARCH_API_VERSION = "2024-07-01"
DEFAULT_AOAI_API_VERSION = "2024-10-21"
DEFAULT_TOP_K = 8
DEFAULT_MAX_QUESTION_LENGTH = 2000


@dataclass(frozen=True)
class QueryConfig:
    search_endpoint: str
    search_index: str
    aoai_endpoint: str
    chat_model: str
    embed_model: str
    search_api_version: str = DEFAULT_SEARCH_API_VERSION
    aoai_api_version: str = DEFAULT_AOAI_API_VERSION
    default_top_k: int = DEFAULT_TOP_K
    max_question_length: int = DEFAULT_MAX_QUESTION_LENGTH

    # Trusted cache-partition defaults, used only when APIM's trusted context
    # headers are absent (local development / direct testing). A real
    # deployment always receives these from APIM — see
    # `openspec/changes/add-apim-exact-cache-demo/design.md`.
    default_knowledge_generation: str = "0"
    default_security_scope: str = "demo-public"
    default_prompt_version: str = "v1"
    default_logical_model_version: str = "v1"

    @classmethod
    def from_env(cls) -> "QueryConfig":
        return cls(
            search_endpoint=os.environ.get(
                "AZURE_SEARCH_ENDPOINT", "https://docintv2-dev-search.search.windows.net"
            ),
            search_index=os.environ.get("AZURE_SEARCH_INDEX", "document-chunks"),
            aoai_endpoint=os.environ.get(
                "AOAI_ENDPOINT", "https://docintv2-dev-oai-e8436.openai.azure.com/"
            ),
            chat_model=os.environ.get("AOAI_CHAT_DEPLOYMENT", "gpt-4o-mini"),
            embed_model=os.environ.get("AOAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002"),
            search_api_version=os.environ.get(
                "AZURE_SEARCH_API_VERSION", DEFAULT_SEARCH_API_VERSION
            ),
            aoai_api_version=os.environ.get("AOAI_API_VERSION", DEFAULT_AOAI_API_VERSION),
            default_top_k=int(os.environ.get("QUERY_DEFAULT_TOP_K", DEFAULT_TOP_K)),
            max_question_length=int(
                os.environ.get("QUERY_MAX_QUESTION_LENGTH", DEFAULT_MAX_QUESTION_LENGTH)
            ),
            default_knowledge_generation=os.environ.get("QUERY_DEFAULT_GENERATION", "0"),
            default_security_scope=os.environ.get("QUERY_DEFAULT_SECURITY_SCOPE", "demo-public"),
            default_prompt_version=os.environ.get("QUERY_DEFAULT_PROMPT_VERSION", "v1"),
            default_logical_model_version=os.environ.get("QUERY_DEFAULT_MODEL_VERSION", "v1"),
        )
