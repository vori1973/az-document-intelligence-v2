"""
Make the `query/` application directory importable as `rag` (its top-level
package) for tests, matching the `sys.path.insert(..., "src")` pattern used
by `tests/unit/*.py` for the ingestion app.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "query"))
