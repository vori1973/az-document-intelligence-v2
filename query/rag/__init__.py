"""
rag — reusable RAG query domain shared by the query Function App and
`scripts/demo.py`.

Pure modules (no Azure Functions / HTTP framework dependency):
  contracts   — typed Pydantic request/response/citation/execution/error models
  validation  — bounded question validation
  normalize   — question normalization, hashing, and cache-key identity
  auth        — managed-identity credential resolution
  clients     — Azure AI Search / Azure OpenAI client construction
  retrieval   — query embedding + hybrid retrieval + result mapping
  answer      — grounded prompt construction, answer generation, citations
  telemetry   — structured, privacy-preserving telemetry helpers
  config      — environment-driven configuration for the query Function App
  service     — orchestrates validation → retrieval → answer → response
"""

from __future__ import annotations
