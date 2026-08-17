"""
Pydantic data models for all inter-step data contracts.
These replace the TypeScript interfaces in types.ts from v1.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PipelineContext(BaseModel):
    """Passed from the trigger into the orchestrator and through all activities."""

    doc_id: str
    run_id: str
    blob_name: str  # path inside documents/ container, e.g. "folder/report.pdf"
    blob_url: str


# ── Step 1 ────────────────────────────────────────────────────────────────


class PreAnalysisResult(BaseModel):
    blob_name: str
    doc_id: str  # SHA-256 hex[:16] of PDF content
    page_count: int
    has_text: bool  # False = scanned/image-only PDF
    file_size_bytes: int


# ── Step 2 ────────────────────────────────────────────────────────────────


class TableConfidence(BaseModel):
    table_index: int
    page_number: int
    average_cell_confidence: float
    min_cell_confidence: float
    cell_count: int
    unmatched_cells: int
    requires_ocr: bool
    has_complex_structure: bool
    complexity_reasons: list[str] = Field(default_factory=list)
    polygon: list[float] = Field(default_factory=list)


class FigureLocation(BaseModel):
    figure_index: int
    figure_id: str
    page_number: int
    polygon: list[float]
    caption: Optional[str] = None
    adi_image_blob: Optional[str] = None  # blob path if fetched


class BoundingBox(BaseModel):
    page_number: int
    role: str
    content: str
    polygon: list[float]
    confidence: Optional[float] = None


class AdiPageResult(BaseModel):
    page_number: int
    tables: list[TableConfidence] = Field(default_factory=list)
    figures: list[FigureLocation] = Field(default_factory=list)
    raw_content: str = ""
    bounding_boxes: list[BoundingBox] = Field(default_factory=list)


# ── Step 3 ────────────────────────────────────────────────────────────────


class RoutingDecision(BaseModel):
    doc_id: str
    total_pages: int
    pages_for_ocr: list[int]  # pages needing Mistral OCR (1-based)
    adi_only_pages: list[int]
    low_confidence_tables: list[TableConfidence] = Field(default_factory=list)


# ── Step 4 ────────────────────────────────────────────────────────────────


class OcrPageResult(BaseModel):
    page_number: int
    markdown_content: str
    image_blobs: list[str] = Field(default_factory=list)  # blob paths of extracted images
    source: str = "mistral-ocr"


# ── Step 5 ────────────────────────────────────────────────────────────────


class RagCitation(BaseModel):
    document_id: str
    page: int
    bounding_polygon: list[float] = Field(default_factory=list)
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    figure_index: Optional[int] = None


class RagChunk(BaseModel):
    chunk_id: str
    type: Literal["table_row", "paragraph", "figure"]
    source: str  # "ADI-prebuilt-layout" or OCR deployment name
    source_file: Optional[str] = None
    text_for_embedding: str
    image_blob: Optional[str] = None  # blob path for figure images
    citation: RagCitation
    embedding: Optional[list[float]] = None


# ── Step 4A / 4B — figure candidates ──────────────────────────────────────


class FigureFeatures(BaseModel):
    """Geometric signals used for filtering, routing, and diagnostics.

    These are never embedded as semantic content — they exist to explain and
    reproduce routing decisions.
    """

    width_ratio: float
    height_ratio: float
    area_ratio: float
    aspect_ratio: float
    header_overlap_ratio: float = 0.0
    footer_overlap_ratio: float = 0.0
    normalized_position_group: str = ""


class FigureCandidate(BaseModel):
    """One ADI figure region, qualified by deterministic rules (steps 4A/4B).

    ADI stays the citation authority: page and bounding_polygon are copied
    from ADI unchanged and are never derived from the vision model.
    """

    document_id: str
    source_file: Optional[str] = None
    page: int
    figure_index: int
    figure_id: str
    bounding_polygon: list[float] = Field(default_factory=list)
    caption: Optional[str] = None
    page_width: float = 0.0
    page_height: float = 0.0
    tight_crop_uri: Optional[str] = None
    status: Literal["candidate", "rejected"] = "candidate"
    rejection_reason: Optional[str] = None
    routing_signals: list[str] = Field(default_factory=list)
    features: Optional[FigureFeatures] = None


# ── Pipeline aggregate ────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    doc_id: str
    pre_analysis: PreAnalysisResult
    adi_results: list[AdiPageResult]
    routing: RoutingDecision
    ocr_results: list[OcrPageResult] = Field(default_factory=list)
