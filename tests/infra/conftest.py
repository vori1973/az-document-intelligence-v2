"""
Static contract tests for the query/APIM infrastructure.

These read the checked-in Bicep and APIM policy sources directly — no Azure
resources and no deployment are involved. They exist because the APIM policy and
the Python query domain implement the *same* cache-identity contract in two
languages, and nothing else would catch them drifting apart.

`query/` is added to `sys.path` so `rag.normalize` (the authoritative Python
implementation of that contract) can be imported, matching the pattern in
`tests/query/conftest.py`.
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "query"))
