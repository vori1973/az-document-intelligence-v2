"""Unit tests for the query Function App (openspec/changes/add-apim-exact-cache-demo).

Kept out of tests/unit/ deliberately: that package's conftest.py stubs Azure
SDK modules as MagicMocks for the ingestion app's pure-logic tests, which
would interfere with real `azure.identity`, `azure.functions`, and `openai`
imports used here.
"""
