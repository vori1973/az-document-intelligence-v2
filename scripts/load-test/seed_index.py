#!/usr/bin/env python3
"""
seed_index.py — Inject synthetic chunks into Azure AI Search for load testing.

Generates documents that conform to the existing `document-chunks` index schema,
using random unit vectors for the embedding field. Synthetic chunks use IDs
prefixed with `synthetic-` so they can be identified and removed after testing.

Usage:
    python seed_index.py --chunks 50000
    python seed_index.py --chunks 10000 --batch-size 200
    python seed_index.py --delete

Environment variables required:
    AZURE_SEARCH_ENDPOINT   https://<name>.search.windows.net
    AZURE_SEARCH_INDEX      document-chunks (or your index name)
"""

import argparse
import math
import os
import sys
import time
import uuid
from typing import Iterator

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

EMBEDDING_DIMS = 1536
DEFAULT_BATCH_SIZE = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Azure AI Search index with synthetic chunks for load testing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--chunks",
        type=int,
        default=10_000,
        help="Number of synthetic chunks to upload",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Documents per upload batch (max 1000 per Azure SDK limit)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete all synthetic chunks (id prefix 'synthetic-') instead of seeding",
    )
    parser.add_argument(
        "--create-index",
        action="store_true",
        help=(
            "Create the index before seeding with no vector compression (float32). "
            "Simulates an uncompressed production index like aiadvisor-prod-index-hcc. "
            "Fails if the index already exists."
        ),
    )
    parser.add_argument(
        "--dims",
        type=int,
        default=EMBEDDING_DIMS,
        help=(
            "Vector dimensions for --create-index. "
            "Use 1536 (default, compatible with existing query_bank.json) or "
            "3072 to match text-embedding-3-large (requires re-running embed_queries.py)."
        ),
    )
    parser.add_argument(
        "--delete-index",
        action="store_true",
        help="Drop the entire index (not just synthetic chunks). Use after load testing to clean up.",
    )
    return parser.parse_args()


def _handle_http_error(err: HttpResponseError, operation: str) -> None:
    """Print a human-readable error message and exit."""
    status = err.status_code
    if status == 403:
        sys.exit(
            f"\nERROR: Permission denied while {operation}.\n"
            "Your identity does not have 'Search Index Data Contributor' on this "
            "Azure AI Search service.\n\n"
            "Fix it with:\n"
            "  USER_OID=$(az ad signed-in-user show --query id -o tsv)\n"
            "  az role assignment create \\\n"
            "    --role \"Search Index Data Contributor\" \\\n"
            "    --assignee $USER_OID \\\n"
            "    --scope /subscriptions/<sub>/resourceGroups/<rg>"
            "/providers/Microsoft.Search/searchServices/<service>\n\n"
            "Wait 1-2 minutes for RBAC propagation, then retry."
        )
    elif status == 400:
        sys.exit(
            f"\nERROR: Bad request while {operation}.\n\n"
            f"Azure said: {err.message}\n\n"
            "Possible causes:\n"
            "  - Index schema has changed: compare make_synthetic_chunk() in\n"
            "    seed_index.py against field definitions in src/activities/step7_search.py\n"
            "  - OData filter syntax not supported by this API version"
        )
    elif status == 401:
        sys.exit(
            f"\nERROR: Unauthenticated while {operation}.\n"
            "DefaultAzureCredential could not obtain a token.\n\n"
            "Run 'az login' (or ensure your managed identity / service principal "
            "credentials are configured) and retry."
        )
    else:
        sys.exit(f"\nERROR: Azure Search returned HTTP {status} while {operation}.\n{err.message}")


def get_index_client() -> SearchIndexClient:
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    if not endpoint:
        sys.exit("ERROR: AZURE_SEARCH_ENDPOINT environment variable is not set.")
    return SearchIndexClient(endpoint=endpoint, credential=DefaultAzureCredential())


def create_uncompressed_index(dims: int) -> None:
    """Create a new index with float32 vectors and no compression.

    This mirrors what the customer's uncompressed indexes look like (e.g.
    aiadvisor-prod-index-hcc: 3072-dim float32, ~12,288 bytes/chunk in the HNSW
    graph). Even at 1536 dims (default), omitting compression makes each HNSW
    traversal step read 6,144 bytes/chunk vs ~384 bytes for binary-quantized
    indexes — ~16× more CPU per query.
    """
    index_name = os.environ.get("AZURE_SEARCH_INDEX")
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    if not index_name:
        sys.exit("ERROR: AZURE_SEARCH_INDEX environment variable is not set.")
    if not endpoint:
        sys.exit("ERROR: AZURE_SEARCH_ENDPOINT environment variable is not set.")

    index = SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="text_for_embedding", type=SearchFieldDataType.String),
            SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True),
            SearchField(
                name="embedding",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=dims,
                vector_search_profile_name="hnsw-profile",
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
            profiles=[VectorSearchProfile(
                name="hnsw-profile",
                algorithm_configuration_name="hnsw-config",
                # no compression_name → float32, no quantization
            )],
        ),
    )

    client = get_index_client()
    try:
        client.create_index(index)
    except HttpResponseError as err:
        _handle_http_error(err, f"creating index '{index_name}'")

    bytes_per_chunk = dims * 4
    print(
        f"Created uncompressed index '{index_name}':\n"
        f"  dims={dims}  encoding=float32  compression=none\n"
        f"  {bytes_per_chunk:,} bytes/chunk in HNSW graph  "
        f"(vs ~{dims // 8} bytes binary-quantized — {dims * 4 // (dims // 8)}× more expensive per query)\n"
    )


def delete_index() -> None:
    """Drop the entire index. Used to clean up after load testing."""
    index_name = os.environ.get("AZURE_SEARCH_INDEX")
    if not index_name:
        sys.exit("ERROR: AZURE_SEARCH_INDEX environment variable is not set.")
    client = get_index_client()
    try:
        client.delete_index(index_name)
    except HttpResponseError as err:
        _handle_http_error(err, f"deleting index '{index_name}'")
    print(f"Deleted index '{index_name}'.")


def get_search_client() -> SearchClient:
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    index = os.environ.get("AZURE_SEARCH_INDEX")
    if not endpoint:
        sys.exit("ERROR: AZURE_SEARCH_ENDPOINT environment variable is not set.")
    if not index:
        sys.exit("ERROR: AZURE_SEARCH_INDEX environment variable is not set.")
    credential = DefaultAzureCredential()
    return SearchClient(endpoint=endpoint, index_name=index, credential=credential)


def random_unit_vector(dims: int = EMBEDDING_DIMS) -> list[float]:
    """Draw from standard normal distribution and L2-normalise to unit length."""
    import random
    import math

    components = [random.gauss(0.0, 1.0) for _ in range(dims)]
    norm = math.sqrt(sum(x * x for x in components))
    return [x / norm for x in components]


def make_synthetic_chunk(seq: int, dims: int = EMBEDDING_DIMS) -> dict:
    """Build a synthetic document chunk with only the fields common to all schemas.

    Extra fields from the original document-chunks schema (type, document_id,
    page, etc.) are omitted — they are nullable there and cause errors on the
    minimal load-test-uncompressed schema.
    """
    return {
        "id": f"synthetic-{uuid.uuid4().hex}",
        "source_file": f"synthetic-document-{seq // 10}.pdf",
        "text_for_embedding": (
            f"Synthetic chunk {seq}. Placeholder text for load testing. "
            "Does not represent real medical device documentation."
        ),
        "embedding": random_unit_vector(dims),
    }


def _batches(chunks: int, batch_size: int) -> Iterator[range]:
    """Yield ranges representing each batch of chunk sequence numbers."""
    for start in range(0, chunks, batch_size):
        yield range(start, min(start + batch_size, chunks))


def seed(client: SearchClient, chunks: int, batch_size: int, dims: int = EMBEDDING_DIMS) -> None:
    """Upload synthetic chunks in batches, printing per-batch progress."""
    total_batches = math.ceil(chunks / batch_size)
    uploaded = 0
    t0 = time.monotonic()

    print(f"Seeding {chunks:,} synthetic chunks in batches of {batch_size} (dims={dims})...")

    for batch_num, seq_range in enumerate(_batches(chunks, batch_size), start=1):
        docs = [make_synthetic_chunk(seq, dims) for seq in seq_range]
        try:
            client.upload_documents(docs)
        except HttpResponseError as err:
            _handle_http_error(err, f"uploading batch {batch_num}")
        uploaded += len(docs)
        elapsed = time.monotonic() - t0
        rate = uploaded / elapsed if elapsed > 0 else 0.0
        print(
            f"  Batch {batch_num}/{total_batches} "
            f"({len(docs)} docs) | "
            f"cumulative: {uploaded:,} | "
            f"elapsed: {elapsed:.1f}s | "
            f"{rate:.0f} chunks/sec"
        )

    elapsed = time.monotonic() - t0
    print(
        f"\nDone. Uploaded {uploaded:,} synthetic chunks in {elapsed:.1f}s "
        f"({uploaded / elapsed:.0f} chunks/sec)."
    )
    print(
        "Wait 2-5 minutes for the HNSW graph to stabilise before running the load test."
    )


def delete_synthetic(client: SearchClient) -> None:
    """Search for all documents with id prefix 'synthetic-' and delete them."""
    print("Searching for synthetic chunks...")

    ids: list[str] = []
    try:
        results = client.search(
            search_text="*",
            filter="id ge 'synthetic-' and id lt 'synthetic.'",
            select=["id"],
            top=1000,
        )
        for doc in results:
            ids.append(doc["id"])
    except HttpResponseError as err:
        _handle_http_error(err, "searching for synthetic chunks")

    if not ids:
        print("No synthetic chunks found. Nothing to delete.")
        return

    print(f"Found {len(ids):,} synthetic chunks. Deleting...")

    batch_size = DEFAULT_BATCH_SIZE
    deleted = 0
    for start in range(0, len(ids), batch_size):
        batch_ids = ids[start : start + batch_size]
        docs_to_delete = [{"id": chunk_id} for chunk_id in batch_ids]
        try:
            client.delete_documents(docs_to_delete)
        except HttpResponseError as err:
            _handle_http_error(err, f"deleting batch at offset {start}")
        deleted += len(batch_ids)
        print(f"  Deleted {deleted:,}/{len(ids):,}")

    print(f"\nDone. Deleted {deleted:,} synthetic chunks.")


def main() -> None:
    args = parse_args()

    if args.delete_index:
        delete_index()
        return

    if args.create_index:
        create_uncompressed_index(args.dims)

    client = get_search_client()
    if args.delete:
        delete_synthetic(client)
    else:
        seed(client, args.chunks, args.batch_size, args.dims)


if __name__ == "__main__":
    main()
