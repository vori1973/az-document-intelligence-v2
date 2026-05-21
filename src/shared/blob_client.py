"""
Blob Storage helpers for reading/writing pipeline artifacts.

All operations use DefaultAzureCredential (Managed Identity in Azure,
az login locally). The Function App MI must have Storage Blob Data Contributor
on the storage account.

Artifact layout:
    processing/{doc_id}/{run_id}/step1-result.json
    processing/{doc_id}/{run_id}/adi-raw.json
    processing/{doc_id}/{run_id}/adi-content.md
    processing/{doc_id}/{run_id}/routing.json
    processing/{doc_id}/{run_id}/pages/page-{N}.pdf
    processing/{doc_id}/{run_id}/ocr-page-{N}.md
    processing/{doc_id}/{run_id}/p{N}-img-{M}.jpeg
    processing/{doc_id}/{run_id}/chunks.json
    processing/{doc_id}/{run_id}/chunks-embedded.json
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from azure.storage.blob import (
    BlobSasPermissions,
    BlobServiceClient,
    generate_blob_sas,
)

from .auth import get_credential

DOCUMENTS_CONTAINER = os.environ.get("DOCUMENTS_CONTAINER", "documents")
PROCESSING_CONTAINER = os.environ.get("PROCESSING_CONTAINER", "processing")


@lru_cache(maxsize=1)
def _get_service_client() -> BlobServiceClient:
    account_url = os.environ["STORAGE_ACCOUNT_URL"]
    return BlobServiceClient(account_url=account_url, credential=get_credential())


def _processing_path(doc_id: str, run_id: str, filename: str) -> str:
    return f"{doc_id}/{run_id}/{filename}"


# ── Document (source PDF) ──────────────────────────────────────────────────


def download_document(blob_name: str) -> bytes:
    """Download a PDF from the documents container."""
    client = _get_service_client()
    blob = client.get_blob_client(container=DOCUMENTS_CONTAINER, blob=blob_name)
    return blob.download_blob().readall()


# ── Processing artifacts ───────────────────────────────────────────────────


def upload_artifact(doc_id: str, run_id: str, filename: str, content: bytes | str) -> None:
    """Write an artifact to processing/{doc_id}/{run_id}/{filename}."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    client = _get_service_client()
    blob_name = _processing_path(doc_id, run_id, filename)
    blob = client.get_blob_client(container=PROCESSING_CONTAINER, blob=blob_name)
    blob.upload_blob(content, overwrite=True)


def upload_json_artifact(doc_id: str, run_id: str, filename: str, data: Any) -> None:
    """Serialise data as JSON and upload as an artifact."""
    upload_artifact(doc_id, run_id, filename, json.dumps(data, indent=2))


def download_artifact(doc_id: str, run_id: str, filename: str) -> bytes:
    """Download an artifact from processing/{doc_id}/{run_id}/{filename}."""
    client = _get_service_client()
    blob_name = _processing_path(doc_id, run_id, filename)
    blob = client.get_blob_client(container=PROCESSING_CONTAINER, blob=blob_name)
    return blob.download_blob().readall()


def download_json_artifact(doc_id: str, run_id: str, filename: str) -> Any:
    return json.loads(download_artifact(doc_id, run_id, filename))


def list_artifacts(doc_id: str, run_id: str) -> list[str]:
    """List all artifact blob names under processing/{doc_id}/{run_id}/."""
    client = _get_service_client()
    prefix = f"{doc_id}/{run_id}/"
    container = client.get_container_client(PROCESSING_CONTAINER)
    return [b.name for b in container.list_blobs(name_starts_with=prefix)]


def delete_doc_artifacts(doc_id: str) -> int:
    """Delete all processing artifacts for a document. Returns the number of blobs deleted."""
    client = _get_service_client()

    # Remove the reverse name-index entry so resolve_doc_id won't return stale results
    try:
        blob_name = download_artifact(doc_id, "_meta", "blob-name.txt").decode().strip()
        key = hashlib.sha256(blob_name.encode()).hexdigest()[:32]
        client.get_blob_client(
            container=PROCESSING_CONTAINER, blob=f"_name-index/{key}.txt"
        ).delete_blob()
    except Exception:
        pass  # mapping absent (pre-index documents) — safe to ignore

    prefix = f"{doc_id}/"
    container = client.get_container_client(PROCESSING_CONTAINER)
    blobs = list(container.list_blobs(name_starts_with=prefix))
    for blob in blobs:
        container.delete_blob(blob.name)
    return len(blobs)


# ── SAS URL generation (for Mistral OCR step4) ────────────────────────────


def generate_page_sas_url(doc_id: str, run_id: str, page: int, expiry_hours: int = 1) -> str:
    """
    Generate a short-lived SAS URL for a page PDF artifact.
    Used by step4 to pass to Mistral OCR without base64 encoding.

    Requires the MI to have Storage Blob Delegator + Storage Blob Data Reader,
    or falls back to account-key SAS if STORAGE_ACCOUNT_KEY is set (local dev).
    """
    client = _get_service_client()
    account_url = os.environ["STORAGE_ACCOUNT_URL"]
    # Extract account name from URL: https://<account>.blob.core.windows.net
    account_name = account_url.split("//")[1].split(".")[0]
    blob_name = _processing_path(doc_id, run_id, f"pages/page-{page}.pdf")
    expiry = datetime.now(timezone.utc) + timedelta(hours=expiry_hours)

    account_key = os.environ.get("STORAGE_ACCOUNT_KEY")
    if account_key:
        # Local dev: use account key SAS
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=PROCESSING_CONTAINER,
            blob_name=blob_name,
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
    else:
        # Production: user delegation SAS via Managed Identity
        user_delegation_key = client.get_user_delegation_key(
            key_start_time=datetime.now(timezone.utc),
            key_expiry_time=expiry,
        )
        sas_token = generate_blob_sas(
            account_name=account_name,
            container_name=PROCESSING_CONTAINER,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )

    return f"{account_url}/{PROCESSING_CONTAINER}/{blob_name}?{sas_token}"


# ── doc_id ↔ blob_name mapping ────────────────────────────────────────────


def _name_index_path(blob_name: str) -> str:
    """Stable blob path for the reverse blob_name → doc_id index entry."""
    key = hashlib.sha256(blob_name.encode()).hexdigest()[:32]
    return f"_name-index/{key}.txt"


def store_doc_id_mapping(blob_name: str, doc_id: str) -> None:
    """Persist blob_name → doc_id so delete_trigger can resolve the ID.

    Two blobs are written:
      processing/{doc_id}/_meta/blob-name.txt  — forward mapping (human-readable)
      processing/_name-index/{hash}.txt        — reverse index for O(1) lookup
    """
    upload_artifact(doc_id, "_meta", "blob-name.txt", blob_name)
    # Reverse index: overwrite so re-uploads with the same name always point to the latest doc_id
    client = _get_service_client()
    index_blob = client.get_blob_client(
        container=PROCESSING_CONTAINER, blob=_name_index_path(blob_name)
    )
    index_blob.upload_blob(doc_id.encode(), overwrite=True)


def resolve_doc_id(blob_name: str) -> str | None:
    """Look up doc_id from a blob_name stored during ingestion.

    Reads directly from the reverse name-index — O(1), no container scan.
    Falls back to None if no mapping exists (document not yet ingested or already cleaned up).
    """
    client = _get_service_client()
    index_blob = client.get_blob_client(
        container=PROCESSING_CONTAINER, blob=_name_index_path(blob_name)
    )
    try:
        return index_blob.download_blob().readall().decode().strip()
    except Exception:
        return None
