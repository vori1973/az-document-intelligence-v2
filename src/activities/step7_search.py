"""
Step 7 — Index into Azure AI Search.

Reads chunks-embedded.json, ensures the HNSW vector index exists (creates/updates it),
then upserts all chunks in batches of 500.

Auth: DefaultAzureCredential — Function App MI must have
      Search Index Data Contributor on the AI Search resource.

Schema ported 1:1 from v1 step7-search.ts.
"""

from __future__ import annotations

import logging
import os

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    ScalarQuantizationCompression,
    ScalarQuantizationParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)

from shared.auth import get_credential
from shared.blob_client import download_json_artifact
from shared.telemetry import timed_step, track_metric
from models.types import RagChunk

logger = logging.getLogger(__name__)

UPLOAD_BATCH = 500
SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "")
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "document-chunks")


def _build_index_schema() -> SearchIndex:
    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SimpleField(name="type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True, retrievable=True),
        SearchField(name="text_for_embedding", type=SearchFieldDataType.String, searchable=True, retrievable=True),
        SimpleField(name="image_blob", type=SearchFieldDataType.String, retrievable=True),
        SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="page", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
        SimpleField(name="table_index", type=SearchFieldDataType.Int32, filterable=True, retrievable=True),
        SimpleField(name="row_index", type=SearchFieldDataType.Int32, filterable=True, retrievable=True),
        SimpleField(name="figure_index", type=SearchFieldDataType.Int32, filterable=True, retrievable=True),
        SimpleField(
            name="bounding_polygon",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Double),
            retrievable=True,
        ),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            retrievable=False,
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="default-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="hnsw-config",
                parameters=HnswParameters(
                    metric=VectorSearchAlgorithmMetric.COSINE,
                    m=4,
                    ef_construction=400,
                    ef_search=500,
                ),
            )
        ],
        compressions=[
            ScalarQuantizationCompression(
                compression_name="scalar-quantization",
                parameters=ScalarQuantizationParameters(quantized_data_type="int8"),
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="default-profile",
                algorithm_configuration_name="hnsw-config",
                compression_name="scalar-quantization",
            )
        ],
    )

    semantic = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="semantic-config",
                prioritized_fields=SemanticPrioritizedFields(
                    content_fields=[SemanticField(field_name="text_for_embedding")]
                ),
            )
        ]
    )

    return SearchIndex(
        name=SEARCH_INDEX,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic,
    )


def _ensure_index(index_client: SearchIndexClient) -> None:
    schema = _build_index_schema()
    try:
        index_client.get_index(SEARCH_INDEX)
        logger.info("[step7] Updating existing index '%s'", SEARCH_INDEX)
        index_client.create_or_update_index(schema)
    except Exception:
        logger.info("[step7] Creating new index '%s'", SEARCH_INDEX)
        index_client.create_index(schema)


def _chunk_to_doc(chunk: RagChunk) -> dict:
    return {
        "@search.action": "mergeOrUpload",
        "id": chunk.chunk_id,
        "type": chunk.type,
        "source": chunk.source,
        "source_file": chunk.source_file,
        "text_for_embedding": chunk.text_for_embedding,
        "image_blob": chunk.image_blob,
        "document_id": chunk.citation.document_id,
        "page": chunk.citation.page,
        "table_index": chunk.citation.table_index,
        "row_index": chunk.citation.row_index,
        "figure_index": chunk.citation.figure_index,
        "bounding_polygon": chunk.citation.bounding_polygon,
        "embedding": chunk.embedding or [],
    }


def step7_search_main(ctx: dict) -> dict:
    doc_id: str = ctx["doc_id"]
    run_id: str = ctx["run_id"]

    with timed_step("step7_search", doc_id, run_id):
        chunks_raw = download_json_artifact(doc_id, run_id, "chunks-embedded.json")
        chunks = [RagChunk.model_validate(c) for c in chunks_raw]

        missing = [c.chunk_id for c in chunks if not c.embedding]
        if missing:
            raise ValueError(f"{len(missing)} chunks missing embeddings — run step6 first")

        credential = get_credential()
        index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
        _ensure_index(index_client)

        search_client = SearchClient(
            endpoint=SEARCH_ENDPOINT,
            index_name=SEARCH_INDEX,
            credential=credential,
        )

        total_indexed = 0
        total_batches = (len(chunks) + UPLOAD_BATCH - 1) // UPLOAD_BATCH

        for b_start in range(0, len(chunks), UPLOAD_BATCH):
            batch = chunks[b_start : b_start + UPLOAD_BATCH]
            docs = [_chunk_to_doc(c) for c in batch]
            batch_num = b_start // UPLOAD_BATCH + 1
            logger.info(
                "[step7] Batch %d/%d — %d docs (%s…%s)",
                batch_num, total_batches, len(docs), docs[0]["id"], docs[-1]["id"],
            )
            result = search_client.upload_documents(docs)
            succeeded = sum(1 for r in result if r.succeeded)
            total_indexed += succeeded
            logger.info("[step7] Batch %d: %d/%d succeeded", batch_num, succeeded, len(docs))

        track_metric("chunks_indexed", total_indexed, doc_id=doc_id)
        logger.info("[step7] doc_id=%s indexed=%d/%d", doc_id, total_indexed, len(chunks))
        return {"chunks_indexed": total_indexed}
