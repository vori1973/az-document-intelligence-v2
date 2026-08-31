"""Unit tests for managed-identity credential resolution (task 2.1)."""

from __future__ import annotations

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from rag.auth import get_credential, is_local_development


def test_is_local_development_true_for_development_value():
    assert is_local_development("Development") is True
    assert is_local_development("development") is True


def test_is_local_development_false_for_explicit_production_value():
    assert is_local_development("Production") is False
    assert is_local_development("anything-else") is False


def test_is_local_development_reads_env_var_when_not_overridden(monkeypatch):
    monkeypatch.delenv("AZURE_FUNCTIONS_ENVIRONMENT", raising=False)
    assert is_local_development() is False
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Development")
    assert is_local_development() is True


def test_get_credential_uses_default_azure_credential_in_local_development(monkeypatch):
    get_credential.cache_clear()
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Development")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    try:
        credential = get_credential()
        assert isinstance(credential, DefaultAzureCredential)
    finally:
        get_credential.cache_clear()


def test_get_credential_uses_managed_identity_credential_in_production(monkeypatch):
    get_credential.cache_clear()
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Production")
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    try:
        credential = get_credential()
        assert isinstance(credential, ManagedIdentityCredential)
    finally:
        get_credential.cache_clear()


def test_get_credential_uses_managed_identity_credential_when_unset(monkeypatch):
    """A deployed Function App does not set `AZURE_FUNCTIONS_ENVIRONMENT` —
    production auth must default to `ManagedIdentityCredential`, never fall
    through to `DefaultAzureCredential`."""
    get_credential.cache_clear()
    monkeypatch.delenv("AZURE_FUNCTIONS_ENVIRONMENT", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
    try:
        credential = get_credential()
        assert isinstance(credential, ManagedIdentityCredential)
    finally:
        get_credential.cache_clear()


def test_get_credential_uses_user_assigned_identity_client_id_when_set(monkeypatch):
    get_credential.cache_clear()
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Production")
    monkeypatch.setenv("AZURE_CLIENT_ID", "11111111-1111-1111-1111-111111111111")
    try:
        credential = get_credential()
        assert isinstance(credential, ManagedIdentityCredential)
    finally:
        monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)
        get_credential.cache_clear()


def test_get_credential_is_cached_across_calls(monkeypatch):
    get_credential.cache_clear()
    monkeypatch.setenv("AZURE_FUNCTIONS_ENVIRONMENT", "Production")
    try:
        assert get_credential() is get_credential()
    finally:
        get_credential.cache_clear()
