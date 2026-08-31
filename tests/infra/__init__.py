"""Static contract tests for the query and APIM infrastructure sources
(openspec/changes/add-apim-exact-cache-demo, tasks 4.5 / 5.x).

Kept out of tests/unit/ for the same reason as tests/query/: that package's
conftest.py replaces Azure SDK modules with MagicMocks, and these tests import
the real `rag.normalize`.
"""
