"""
Stub out all Azure SDK modules before any src imports.
Unit tests only exercise pure Python logic — no Azure calls needed.
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _make_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    mod.__path__ = []  # mark as package
    return mod


AZURE_STUBS = [
    "azure",
    "azure.storage",
    "azure.storage.blob",
    "azure.identity",
    "azure.keyvault",
    "azure.keyvault.secrets",
    "azure.ai",
    "azure.ai.documentintelligence",
    "azure.ai.documentintelligence.models",
    "azure.search",
    "azure.search.documents",
    "azure.search.documents.indexes",
    "azure.search.documents.indexes.models",
    "azure.core",
    "azure.core.credentials",
    "openai",
    "fitz",
    "opencensus",
    "opencensus.ext",
    "opencensus.ext.azure",
    "opencensus.ext.azure.log_exporter",
    "httpx",
]

for _name in AZURE_STUBS:
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock()
