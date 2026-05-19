"""
Centralised Entra authentication for all Azure SDK clients.

Uses DefaultAzureCredential which resolves credentials in order:
  1. EnvironmentCredential (CI / local env vars)
  2. WorkloadIdentityCredential (AKS)
  3. ManagedIdentityCredential (Function App in Azure)
  4. SharedTokenCacheCredential / VisualStudioCodeCredential / AzureCliCredential (local dev)

No API keys — all access granted via Azure RBAC roles assigned to the
Function App's system-assigned Managed Identity.
"""

from __future__ import annotations

import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential, get_bearer_token_provider


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    """Return a shared DefaultAzureCredential instance (cached for the function app lifetime)."""
    return DefaultAzureCredential()


def get_openai_token_provider():
    """Return a token provider suitable for use with the Azure OpenAI SDK."""
    return get_bearer_token_provider(
        get_credential(),
        "https://cognitiveservices.azure.com/.default",
    )


def get_foundry_key() -> str:
    """
    Retrieve the Azure AI Foundry (Mistral OCR) API key from Key Vault.

    Foundry Classic deployments (Mistral) do not yet support Managed Identity;
    the key is stored in Key Vault and retrieved once at cold start using MI.

    See GitHub issue: "Entra auth: replace Foundry key with Managed Identity once supported"
    """
    from azure.keyvault.secrets import SecretClient

    vault_url = os.environ["KEY_VAULT_URL"]
    secret_name = os.environ.get("FOUNDRY_KEY_SECRET_NAME", "foundry-key")
    client = SecretClient(vault_url=vault_url, credential=get_credential())
    secret = client.get_secret(secret_name)
    return secret.value
