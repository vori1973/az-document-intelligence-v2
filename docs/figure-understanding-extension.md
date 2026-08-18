# ADI Figure Understanding and Visual Retrieval Extension

> **Status:** Phase 1 (4A/4B/4C + enriched chunks) is **implemented and deployed**.
> Tracked as OpenSpec change [`add-figure-understanding`](../openspec/changes/add-figure-understanding/)
> and GitHub issue [#4](https://github.com/vori1973/az-document-intelligence-v2/issues/4).
> This document is the original design; the OpenSpec change is the source of truth
> for what was actually built. Operational settings live in [DEPLOYMENT.md](../DEPLOYMENT.md#figure-understanding-settings).
>
> **Known gap:** figures are currently described **without surrounding page text
> or document context**, which measurably weakens retrieval for uncaptioned
> figures. See [Known Gaps](#known-gaps) below.

## Purpose

This design extends an existing Azure Document Intelligence (ADI) RAG pipeline with:

- deterministic figure qualification
- selective vision-based figure understanding
- figure-to-text relationship mapping
- exact page and polygon citations
- optional multimodal and multi-vector retrieval

The goal is to retrieve and return the correct image, device illustration, procedure diagram, chart, or screenshot together with the supporting document text and an exact source citation.

The architecture is customer-neutral. Model, service, deployment type, and preview-feature choices are controlled through customer-approved configuration and measurable quality gates.

---

## Design Priorities

The solution optimizes for the following priorities, in order:

1. **Retrieval and grounding accuracy**
2. **Exact and auditable citations**
3. **Coverage of visually rich content**
4. **Explainable routing and diagnostics**
5. **Operational simplicity**
6. **Ingestion cost and latency**

For document sets that change infrequently, most extraction, figure-understanding, and visual-indexing cost is incurred during ingestion or re-indexing. Retrieval quality is experienced on every user query. The design therefore permits higher one-time ingestion cost when evaluation shows a material improvement in day-to-day retrieval accuracy.

This does not mean cost is ignored. Deterministic filtering, caching, incremental processing, and selective routing remain important. They prevent spend on obvious noise while allowing high-value pages and figures to receive deeper processing.

---

## Core Design Principle

The existing table pipeline follows this rule:

```text
ADI JSON -> structure, confidence, and bounding polygons: WHERE
OCR/VLM  -> clearer or richer content when required:       WHAT
Rules    -> decide when additional processing is required: WHETHER
```

The figure pipeline follows the same pattern:

```text
ADI figures and polygons -> candidate regions and citations: WHERE
Approved vision model    -> qualification and verbalization: WHAT
Deterministic rules      -> filter noise and route processing: WHETHER
```

**ADI remains the citation authority.**

Vision-generated descriptions improve retrieval and understanding, but they do not replace the original PDF, ADI page number, figure index, content spans, or bounding polygon.

---

## Model and Feature Policy

### Customer-approved models

The pipeline does not hard-code a specific model version. Model names change with each release cycle — what matters is the capability class, not the exact version string.

```ini
FIGURE_UNDERSTANDING_PROVIDER=<approved-provider>
FIGURE_UNDERSTANDING_MODEL=<approved-multimodal-gpt-model>
PAGE_UNDERSTANDING_MODEL=<approved-multimodal-gpt-model>
VISUAL_EMBEDDING_MODEL=<approved-visual-embedding-model>
```

> **Deployment status:** only `FIGURE_UNDERSTANDING_PROVIDER` /
> `FIGURE_UNDERSTANDING_MODEL` are live — they configure the Step 4C call this
> document describes, one call per qualified **figure crop**. `PAGE_UNDERSTANDING_MODEL`
> and `VISUAL_EMBEDDING_MODEL` are config slots reserved for capabilities in
> [Phase 2/3](#delivery-phases) that were never built: sending the model a
> **full-page render** (not a crop) when ADI's figure detection may have missed
> vector content, and embedding the image itself rather than its text
> description. Neither replaces ADI or OCR — see
> [PIPELINE.md](PIPELINE.md#data-sources) for what actually reads the document
> text.

**Practical guidance on model size:**

The figure-understanding call (Step 4C) combines classification and description in a single structured request. Task complexity varies:

```
Simple classification (is_meaningful, category, visible labels)
    -> prefer the smallest approved multimodal GPT model (mini or equivalent)
    -> lower cost per call, faster throughput, sufficient for constrained taxonomy

Complex or ambiguous figures (composite, low contrast, missing caption)
    -> prefer a larger approved multimodal GPT model
    -> better grounding, more reliable label extraction

Page-level understanding (page_visual_summary chunk, optional)
    -> prefer mini — task is descriptive, not analytical
```

Model size is a configuration choice, not an architectural one. The model slots are independent — the figure-understanding model and the page-understanding model can point to different approved versions.

A candidate model must be validated for:

- image input support
- structured output or schema-constrained JSON
- visible-label extraction
- grounding behavior
- latency and throughput
- regional and deployment availability
- data-handling requirements
- customer allow-list status
- cost at expected ingestion volume

The lowest-cost model is not automatically the best choice. Select the smallest approved multimodal GPT model that meets the acceptance criteria for each task.

### Preview features

Preview capabilities can be used when they provide a material improvement in accuracy or architectural simplicity and the customer accepts the preview terms and operational risk.

Preview use requires an explicit decision record covering:

- measurable accuracy benefit
- known limitations
- service-level expectations
- supported regions
- security and compliance approval
- rollback or replacement path
- re-indexing impact if the preview interface changes

Preview status is a risk to manage, not an automatic reason to exclude a capability.

---

## POC Scope

The initial POC implements a complete figure-reference path while keeping the architecture open to deeper visual retrieval.

### POC must-have

```text
Pre-pass  Inspect the PDF object layer for reusable structural signals
Step 4A  Extract ADI figure candidates and geometric features
Step 4B  Apply deterministic noise filtering and routing signals
Step 4C  Run one schema-enforced figure-understanding call per surviving candidate
Step 4D  Resolve caption and paragraph relationships
Step 4E  Build and embed figure chunks
Step 4F  Index figure chunks with existing paragraph and table-row chunks
Step 4G  Return image URI, page, polygon, and relationship metadata
```

### Accuracy-first evaluation track

The POC should also benchmark these optional paths when available and approved:

- Azure AI Vision multimodal embeddings
- Azure AI Search multi-vector fields
- selected full-page verbalization
- selected or full-corpus visual page embeddings
- late-interaction visual document retrieval

The final architecture is selected from measured retrieval quality, not from an assumption that verbalization alone is sufficient.

---

## Problem Decomposition

### 1. Detection

Identify graphical regions and their location.

Primary ADI signals:

- `figures[]`
- `boundingRegions[]`
- page number
- polygon coordinates
- caption content and spans, when present
- page dimensions
- paragraph roles
- content and paragraph spans

### 2. Qualification

Determine whether a candidate carries useful knowledge.

Potentially meaningful:

- device photographs
- device components
- procedure illustrations
- anatomical illustrations
- charts and diagrams
- operational screenshots
- meaningful safety symbols
- composite figures

Likely noise:

- logos
- decorative bars
- separators
- headers and footers
- page backgrounds
- blank or partial crops
- unreferenced small icons

Media references (separate lane, not noise):

- embedded video streams
- linked video URIs
- QR codes pointing to video or audio
- audio annotations
- 3D model references

### 3. Understanding and verbalization

Create a grounded textual representation of a retained figure:

- category
- short description
- visible labels
- device or component terms
- procedure actions visible in the figure
- warnings visibly present
- uncertainty

### 4. Association

Link each retained figure to the content it supports:

```text
figure -> ADI caption
figure -> paragraph
figure -> procedure step
figure -> table
figure -> section heading
figure -> warning or note
```

### 5. Retrieval

Support multiple retrieval paths:

- keyword retrieval over captions and labels
- vector retrieval over figure verbalizations
- multimodal image-text embeddings
- optional multi-vector or late-interaction page retrieval
- relationship expansion from text to figures and figures to text

---

## Pre-Pass: PDF Object-Layer Analysis

Run a lightweight PDF inspection before or in parallel with ADI.

The pre-pass contributes structural signals only. ADI remains the source for semantic figure regions, captions, reading order, page numbers, and citation polygons.

### Media type classification — first output of the pre-pass

Identify the type of every non-text object on each page before any figure filtering or VLM call. Media type determines which processing lane the object enters. Sending a video thumbnail to a vision model or rejecting a video link as a low-value graphic are both failures that media type detection prevents.

```python
for page_number, page in enumerate(doc, start=1):

    # Raster images
    for image in page.get_images(full=True):
        record_raster_image(page_number, image)

    # Annotations — video, audio, links, 3D
    for annot in page.annots():
        annot_type = annot.type[0]

        if annot_type in [fitz.PDF_ANNOT_SCREEN, fitz.PDF_ANNOT_RICH_MEDIA]:
            record_embedded_media(page_number, annot)   # video or audio embedded in PDF

        elif annot_type == fitz.PDF_ANNOT_LINK:
            uri = annot.uri or ""
            if looks_like_video(uri):
                record_linked_video(page_number, annot, uri)
            elif looks_like_audio(uri):
                record_linked_audio(page_number, annot, uri)

        elif annot_type == fitz.PDF_ANNOT_3D:
            record_3d_model(page_number, annot)         # U3D/PRC — rare, some technical manuals
```

Media type classification output per page:

```json
{
  "page": 12,
  "raster_images": [...],
  "embedded_videos": [
    {
      "rect": [72, 200, 540, 450],
      "poster_xref": 41,
      "media_uri": "handpiece-setup.mp4",
      "annotation_type": "RichMedia"
    }
  ],
  "linked_videos": [],
  "linked_audio": [],
  "3d_models": []
}
```

This output routes each object to the correct lane before Step 4A begins:

```
raster image    -> figure pipeline  (ADI + deterministic filter + VLM)
vector drawing  -> figure pipeline  (ADI + deterministic filter + VLM)
embedded video  -> video_reference  (poster + URI captured, video indexing deferred)
linked video    -> video_reference  (URI + surrounding text captured, indexing deferred)
audio           -> audio_reference  (URI captured, transcription deferred)
3D model        -> media_reference  (URI captured, no further processing in POC)
```

### Why video indexing is deferred

A referenced video may be 30 minutes long. Returning "see video" as a citation is not useful. Returning the video at the correct timestamp is. That requires a separate downstream pipeline lane — Azure Video Indexer or an equivalent — that:

- transcribes audio with word-level timestamps
- detects scenes and chapters
- reads on-screen text
- identifies objects and actions

This is a separate pipeline lane, not part of the figure pipeline. The pre-pass captures the video URI and poster frame now. Indexing status is recorded as `pending` so the video lane can pick it up later.

### Phase 1 — thumbnail as image, URI as reference

When no video indexing pipeline exists, treat the poster frame as a regular figure and store the video URI as an additional field. This requires no new infrastructure and is immediately useful.

The thumbnail goes through the standard figure pipeline — deterministic filtering, VLM description, association. The VLM prompt includes one additional instruction: describe only what is visible in this frame and do not infer the full video content from a single image.

```json
{
  "chunk_id": "5746428c_p12_vid0",
  "type": "video_reference",
  "source": "ADI+multimodal-gpt",
  "source_file": "device-manual.pdf",
  "text_for_embedding": "Video thumbnail: handpiece being aligned with connection port. Step 3 label visible on screen. Section: Device Setup > Handpiece Connection.",
  "short_description": "Thumbnail showing handpiece attachment at the connection port with Step 3 label visible.",
  "visible_labels": ["Step 3", "Connection port"],
  "video_uri": "https://example.com/videos/handpiece-setup.mp4",
  "image_uri": "processing/5746428c/{run_id}/figures/p12-vid0-poster.jpeg",
  "caption": "Video 2. Handpiece attachment procedure.",
  "citation": {
    "document_id": "5746428c7c3d6225",
    "page": 12,
    "bounding_polygon": [1.0, 3.2, 7.4, 3.2, 7.4, 7.8, 1.0, 7.8]
  }
}
```

The citation gives the user the poster image and a direct link to the video. This is already meaningful — the thumbnail shows a representative frame and the URI opens the full video.

### Phase 2 — video indexing lane added

When a video indexing pipeline is available, `video_reference` chunks are upgraded with scene-level content from Azure Video Indexer or equivalent. Scene chunks with timestamps are written to a dedicated `videos-index` on the same Azure AI Search service.

```
documents-index
    video_reference chunk  ->  video_uri (join key)

videos-index
    video_scene chunks     ->  video_uri + timestamp_start + timestamp_end
                               transcript_segment, on_screen_text
                               text_for_embedding, content_vector
```

The application layer queries both indexes in parallel and expands `video_reference` hits to their scene chunks, returning the exact timestamp so the UI can deep-link into the video at the relevant moment.

```json
{
  "type": "video_scene",
  "video_uri": "https://example.com/videos/handpiece-setup.mp4",
  "timestamp_start": 94,
  "timestamp_end": 187,
  "transcript_segment": "Take the handpiece and align it with the connection port until you hear a click.",
  "on_screen_text": ["Step 3", "Connection port", "Click to lock"],
  "text_for_embedding": "Handpiece attachment: align with connection port, click to lock. Step 3."
}
```

The same `video_uri` referenced by multiple documents is indexed once in `videos-index`. All `video_reference` chunks pointing to the same URI share the same scene chunks.

### Embedded raster image signals

For embedded image placements, collect:

- XObject reference
- page number
- placement rectangle
- pixel width and height
- occurrence count across pages
- overlap with each ADI figure polygon

Example pseudocode:

```python
xref_page_count = {}
page_image_placements = {}

for page_number, page in enumerate(doc, start=1):
    placements = []

    for image in page.get_images(full=True):
        xref = image[0]
        xref_page_count[xref] = xref_page_count.get(xref, 0) + 1

        for rect in page.get_image_rects(xref):
            placements.append({
                "xref": xref,
                "rect": list(rect),
                "width_px": image[2],
                "height_px": image[3]
            })

    page_image_placements[page_number] = placements
```

### Important interpretation rule

Repeated XObject use proves that the same embedded image object is reused. It does **not** prove that the image is irrelevant.

Examples of repeated but potentially meaningful content include:

- safety symbols
- orientation diagrams
- repeatedly referenced components
- standard procedural illustrations

Treat XObject repetition as a strong routing signal, not an unconditional rejection.

### Vector and composite content

Embedded raster image enumeration does not fully represent vector drawings or composite figures. A single ADI figure can contain:

- zero, one, or multiple raster images
- vector paths and shapes
- PDF text labels
- callout lines
- legends and annotations

Vector drawing extraction, when required, is a separate object-layer operation. The candidate model therefore stores an array of overlapping image placements rather than assuming one ADI figure maps to one XObject.

### Possible missed visual content

Raw image-object count alone is not proof that ADI missed a figure.

Use a stronger diagnostic:

```text
meaningful-size image placement
AND low overlap with all ADI figure polygons
AND nontrivial page-area coverage
-> possible_missed_visual_content
```

This signal can route the page to full-page understanding or visual indexing.

---

## Step 4A: Figure Candidate Extraction

Create one candidate record per ADI figure.

```json
{
  "document_id": "5746428c7c3d6225",
  "source_file": "device-manual.pdf",
  "page": 7,
  "figure_index": 0,
  "bounding_polygon": [0.8, 1.2, 7.4, 1.2, 7.4, 5.6, 0.8, 5.6],
  "caption": "Figure 3. Handpiece components.",
  "caption_spans": [
    { "offset": 8120, "length": 31 }
  ],
  "page_width": 8.5,
  "page_height": 11.0,
  "tight_crop_uri": "processing/{document_id}/{run_id}/figures/p7-fig0.jpeg",
  "status": "candidate",
  "features": {
    "width_ratio": 0.78,
    "height_ratio": 0.40,
    "area_ratio": 0.31,
    "aspect_ratio": 1.95,
    "header_overlap_ratio": 0.0,
    "footer_overlap_ratio": 0.0,
    "normalized_position_group": "0.09:0.11:0.78:0.40",
    "overlapping_xobjects": [
      {
        "xref": 34,
        "overlap_ratio": 0.91,
        "page_count": 1,
        "width_px": 640,
        "height_px": 480
      }
    ]
  }
}
```

Features drive filtering, route selection, diagnostics, and evaluation. They are not embedded as semantic content.

---

## Step 4B: Deterministic Filtering and Routing

Deterministic processing removes obvious noise and records signals for ambiguous cases. It should prefer false positives over false negatives when a hard rejection could remove meaningful content.

### Hard-rejection rules

Use only rules with strong evidence.

```text
substantial overlap with ADI pageHeader/pageFooter/pageNumber region
AND no explicit nearby figure or warning reference
-> reject: structural_noise

extremely small page-area ratio
AND no nearby warning, caution, legend, or figure reference
-> reject: low_value_graphic

extreme aspect ratio consistent with a separator or margin marker
AND no caption or explicit reference
-> reject: decorative_geometry

repeated XObject
AND stable normalized position
AND header/footer or configured furniture zone
AND no explicit reference
-> reject: repeated_boilerplate
```

### Routing signals, not automatic rejection

```text
repeated XObject only
repeated position only
caption missing
small figure near caution or warning text
multiple XObjects inside one ADI figure
vector or composite figure
low overlap between ADI figures and meaningful PDF image placements
```

These signals should route to the approved vision model or diagnostics rather than force rejection.

### Initial thresholds

The following are POC starting values, not product defaults:

```ini
FIGURE_HEADER_FOOTER_OVERLAP_THRESHOLD=0.30
FIGURE_MIN_AREA_RATIO=0.01
FIGURE_MAX_AREA_RATIO=0.90
FIGURE_MAX_ASPECT_RATIO=8.0
FIGURE_REPEAT_POSITION_TOLERANCE=0.02
FIGURE_REPEAT_MIN_PAGES=3
```

Tune thresholds against a labeled sample from each major document family.

---

## Step 4C: One-Pass Figure Understanding

Use one schema-enforced vision call per surviving figure candidate. Combining qualification and enrichment reduces calls and avoids disagreement between separate classification and description requests.

### Call unit: per figure, not per page

This is the key operational difference from Mistral OCR in the table pipeline.

**Mistral** is called per routed page because the routing unit is the page — one page may contain multiple low-confidence tables, and Mistral sees all of them together in a single call. The confidence router flags the entire page as needing better OCR.

**Figure understanding** is called per figure candidate because each figure is a distinct visual entity requiring its own decision:

```
A single page may contain:
    figure 0 -> device diagram     -> meaningful, retain
    figure 1 -> company logo       -> non-meaningful, reject
    figure 2 -> horizontal rule    -> already rejected by Step 4B

Sending the full page would produce a page-level assessment.
Sending individual crops produces per-figure decisions, descriptions, and citations.
```

The model receives a figure crop plus ADI context — not a full page render. This keeps the input focused and the output directly usable for indexing without further decomposition.

VLM call count scales with retained figure candidates, not with page count. Deterministic filtering in Step 4B is the cost gate — the same role that confidence scoring plays for Mistral table routing.

### Input

```text
1. Tight figure crop        (PyMuPDF crop of ADI bounding polygon)
2. ADI caption              (when present in caption spans)
3. Nearby paragraph text    (nearest ADI span on the same page)
4. Active section heading   (section scope of the figure)
5. Deterministic signals    (routing context passed for grounding)
```

A padded context crop can be added when the tight crop excludes necessary labels or legends.

### Controlled taxonomy

```text
device_photo
device_component
procedure_illustration
anatomical_illustration
diagram
chart
table_like
safety_symbol
screenshot
logo
decorative
header_footer
background
unknown
```

### Structured output

```json
{
  "is_meaningful": true,
  "category": "device_component",
  "model_confidence_label": "high",
  "contains_text": true,
  "short_description": "Labeled handpiece with a release control and connection port.",
  "visible_labels": [
    "Release control",
    "Connection port"
  ],
  "device_or_component_terms": [
    "handpiece",
    "release control",
    "connection port"
  ],
  "procedure_actions": [],
  "warnings_or_constraints": [],
  "search_keywords": [
    "handpiece components",
    "connection port",
    "release control"
  ],
  "uncertainty": [
    "Exact model is not visible"
  ],
  "needs_larger_context_crop": false
}
```

### Confidence interpretation

A model-reported confidence value is not automatically a calibrated probability. Prefer categorical labels such as `high`, `medium`, and `low`, or treat any numeric value only as a routing signal.

### Grounding rules

The model must not invent:

- device identity or model number
- procedure sequence
- clinical recommendation
- measurements or settings
- warnings not visible in the image or supplied source context
- component names unsupported by visible labels or source text

If text is unreadable, state that it is unreadable.

Generated verbalization is retrieval metadata, not original source text.

### Routing outcome

```text
is_meaningful = false AND confidence_label = high
    -> reject

is_meaningful = true
    -> retain and build figure chunk

unknown or low confidence
    -> retain metadata, generate context crop or route page to deeper processing
```

---

## Step 4D: Figure-to-Text Association

### Explicit caption resolution

When the ADI figure includes caption content or caption spans:

```text
1. Resolve caption spans against the ADI content string.
2. Find paragraph spans that match or overlap the caption spans.
3. Link the matching paragraph when one exists.
4. Otherwise retain the caption directly on the figure chunk.
```

Store:

```json
{
  "association_method": "adi_caption_link",
  "association_strength": "explicit"
}
```

### Spatial fallback

When no explicit caption relationship exists:

```text
1. Restrict candidate paragraphs to the same page.
2. Exclude pageHeader, pageFooter, pageNumber, and table-cell duplicates.
3. Prefer paragraphs in the same section scope.
4. Select the nearest qualifying paragraph using polygon distance and reading order.
```

Store:

```json
{
  "association_method": "inferred_spatial_section",
  "association_strength": "inferred",
  "association_score": 0.62
}
```

The inferred score is an algorithmic routing score, not a probability.

Do not present an inferred relationship as explicit.

---

## Chunk Types

### Figure chunk

```json
{
  "chunk_id": "5746428c_p7_fig0",
  "type": "figure",
  "source": "ADI+approved-vision-model",
  "source_file": "device-manual.pdf",
  "text_for_embedding": "Figure: Labeled handpiece with a release control and connection port. Visible labels: Release control; Connection port. Section: Device Setup > Handpiece Connection.",
  "figure_category": "device_component",
  "caption": "Figure 3. Handpiece components.",
  "short_description": "Labeled handpiece with a release control and connection port.",
  "visible_labels": [
    "Release control",
    "Connection port"
  ],
  "image_uri": "processing/5746428c/{run_id}/figures/p7-fig0.jpeg",
  "description_source": "approved-vision-model",
  "model_confidence_label": "high",
  "related_chunk_ids": [
    "5746428c_p7_para3"
  ],
  "association_method": "adi_caption_link",
  "association_strength": "explicit",
  "citation": {
    "document_id": "5746428c7c3d6225",
    "page": 7,
    "figure_index": 0,
    "bounding_polygon": [0.8, 1.2, 7.4, 1.2, 7.4, 5.6, 0.8, 5.6]
  }
}
```

### Updated paragraph chunk

```json
{
  "chunk_id": "5746428c_p7_para3",
  "type": "paragraph",
  "source": "ADI-prebuilt-layout",
  "source_file": "device-manual.pdf",
  "text_for_embedding": "The handpiece connects to the system through the connection port. [Related figure: p7_fig0]",
  "related_figure_ids": [
    "5746428c_p7_fig0"
  ],
  "citation": {
    "document_id": "5746428c7c3d6225",
    "page": 7,
    "bounding_polygon": [1.0, 5.8, 7.2, 5.8, 7.2, 6.3, 1.0, 6.3]
  }
}
```

### Video reference chunk

Created from embedded or linked video detected in the pre-pass. VLM is not called on video content.

```json
{
  "chunk_id": "5746428c_p12_vid0",
  "type": "video_reference",
  "source_file": "device-manual.pdf",
  "text_for_embedding": "Instructional video: Handpiece attachment procedure. Section: Device Setup > Handpiece Connection.",
  "caption": "Video 2. Handpiece attachment procedure.",
  "video_uri": "https://example.com/videos/handpiece-setup.mp4",
  "poster_image_uri": "processing/5746428c/{run_id}/figures/p12-vid0-poster.jpeg",
  "video_metadata": {
    "duration_seconds": null,
    "relevant_timestamp_seconds": null,
    "indexing_status": "pending"
  },
  "related_chunk_ids": ["5746428c_p12_para2"],
  "citation": {
    "document_id": "5746428c7c3d6225",
    "page": 12,
    "bounding_polygon": [1.0, 3.2, 7.4, 3.2, 7.4, 7.8, 1.0, 7.8]
  }
}
```

`text_for_embedding` is built from the ADI caption and surrounding paragraph text — not from video content. Video content is indexed separately by a downstream video indexing lane (Azure Video Indexer or equivalent) that populates `relevant_timestamp_seconds` and can produce additional scene-level chunks linked back to this citation.

### Page-summary chunk

A page-summary chunk is optional. Use it for selected pages when page context materially improves retrieval.

```json
{
  "chunk_id": "5746428c_p7_visual_summary",
  "type": "page_visual_summary",
  "source": "approved-vision-model",
  "source_file": "device-manual.pdf",
  "text_for_embedding": "Device setup page containing a labeled handpiece diagram, connection instructions, and a warning note.",
  "related_figure_ids": [
    "5746428c_p7_fig0"
  ],
  "citation": {
    "document_id": "5746428c7c3d6225",
    "page": 7
  }
}
```

A page-summary hit should be resolved to more specific ADI entities whenever possible. If no reliable entity-level match exists, return a page citation rather than inventing a figure association.

---

## Embedding Strategy

### Text representation

Embed:

- figure caption
- grounded short description
- visible labels
- device or component terms
- procedure actions
- warning terms
- section heading
- concise reference to linked text

Do not embed:

- raw polygon values
- local file paths
- XObject identifiers
- perceptual hashes
- routing diagnostics
- hidden model reasoning

### Multimodal embeddings

When approved and beneficial, add an image embedding field generated by a supported multimodal embedding model.

This enables:

- text-to-image retrieval
- image-to-image retrieval
- fusion of text and image relevance

Azure AI Search supports vector and multimodal search patterns. Integrated Azure Vision multimodal embeddings are available as a preview capability in supported configurations. Validate region, networking, model, and indexing constraints before adoption.

---

## Index Schema Additions

```json
{
  "figure_id": "Edm.String",
  "figure_category": "Edm.String",
  "caption": "Edm.String",
  "short_description": "Edm.String",
  "image_uri": "Edm.String",
  "visible_labels": "Collection(Edm.String)",
  "related_chunk_ids": "Collection(Edm.String)",
  "related_figure_ids": "Collection(Edm.String)",
  "association_method": "Edm.String",
  "association_strength": "Edm.String",
  "association_score": "Edm.Double",
  "model_confidence_label": "Edm.String",
  "bounding_polygon_json": "Edm.String",
  "content_vector": "Collection(Edm.Single)",
  "image_vector": "Collection(Edm.Single)"
}
```

Suggested filterable fields:

```text
type
source_file
document_id
page
figure_category
association_strength
```

Store image binaries in approved object storage. Store image URIs and embeddings in the search index.

---

## Retrieval Architecture

### Baseline hybrid retrieval

```text
BM25 keyword search
    +
text-vector search
    +
semantic ranking where supported
    -> merged figure, paragraph, and table-row results
```

Figure chunks participate in the same retrieval flow as paragraph and table-row chunks.

### Relationship expansion

For production-quality retrieval, relationship expansion should be evaluated early rather than automatically deferred:

```text
For each retrieved paragraph, table row, or procedure step:
    add related figures

For each retrieved figure:
    add related paragraphs, tables, and procedure steps

Deduplicate by chunk_id and figure_id
Preserve explicit versus inferred relationships
```

This ensures that a highly relevant text chunk can return its supporting image even when the figure verbalization does not independently rank in the initial top K.

### Multimodal fusion

When image embeddings are enabled:

```text
text hybrid score
    +
image-vector score
    +
relationship evidence
    +
optional semantic score
    -> fused candidate ranking
```

Start with transparent score normalization or reciprocal-rank fusion. Introduce a learned reranker only after a labeled evaluation shows a benefit.

---

## Optional Multi-Vector and Visual Page Retrieval

### Azure AI Search multi-vector fields

Azure AI Search provides preview support for multiple child vectors in a document using complex collection fields. This is distinct from having multiple flat vector fields on the same document.

**Critical constraint: semantic ranker is disabled for nested vectors.**

The semantic ranker — currently one of the strongest retrieval quality levers in the pipeline — does not operate on results retrieved from nested complex collection fields. This is a documented limitation:

```
Flat vector fields (content_vector, image_vector)
    -> semantic reranker works normally
    -> affected: none of the current or Phase 2 design

Nested multi-vector complex collection fields
    -> semantic reranker disabled
    -> affected: only ColPali-style patch-vector storage in Azure AI Search
```

**What this means in practice:**

Flat vector fields — including a second `image_vector` field for multimodal image embeddings — are not affected. Every chunk in Phases 1 and 2 uses flat fields and retains full semantic reranking.

The limitation only applies if you attempt to store ColPali or ColQwen patch vectors (one vector per image region, potentially hundreds per page) inside Azure AI Search complex collection fields. That approach also cannot reproduce MaxSim scoring correctly — Azure AI Search uses ANN, not late-interaction. The combination of no semantic reranking and no proper MaxSim scoring means Azure AI Search multi-vector fields are not an equivalent replacement for a dedicated multivector store.

**Conclusion:** Use Azure AI Search multi-vector fields only for scenarios where semantic reranking is not required and ANN scoring is sufficient. For ColPali or ColQwen-style retrieval, use a dedicated multivector store (Qdrant or equivalent) and resolve hits back to ADI citations. For all Phase 1 and Phase 2 retrieval, the flat-field approach retains full semantic reranking capability.

### ColPali, ColQwen, or equivalent visual retrievers

Treat late-interaction visual document retrieval as an implementation option, not as a required dependency and not as categorically unavailable.

Before adoption, confirm:

- customer approval
- model and license
- managed or custom hosting path
- GPU requirements
- multivector storage and scoring path
- operational ownership
- page-image retention policy

### Full-page versus selective indexing

The default figure-understanding call operates on a figure crop plus ADI context.

Visual page retrieval operates on rendered page images because page context can preserve:

- caption and figure relationships
- labels and callouts
- axes and legends
- procedure steps
- table and diagram relationships
- spatial layout

Select between selective and full-corpus page indexing using measured accuracy.

```text
Selective routing:
    lower ingestion and index cost
    risk of missing pages when routing signals fail

Full-corpus visual indexing:
    higher ingestion and index cost
    greater visual recall
    simpler routing assumptions
```

For slowly changing corpora, full-corpus visual indexing can be justified when the retrieval gain is material. The decision should be based on benchmark results, not cost assumptions alone.

---

## Accuracy and Cost Evaluation

### Evaluation principle

Separate one-time ingestion economics from recurring retrieval quality.

Measure:

- ingestion cost per document and page
- re-index cost for changed documents
- index storage size
- query cost and latency
- relevant-figure recall
- irrelevant-graphic rejection precision
- text-to-figure association accuracy
- visual-page recall
- citation correctness
- answer grounding correctness

### Required comparison

Benchmark at least these configurations:

```text
A. ADI text and tables only
B. A + figure verbalization
C. B + relationship expansion
D. C + multimodal image embeddings
E. C + selected-page visual retrieval
F. C + full-corpus visual retrieval
```

Use the same labeled queries and source documents for each configuration.

### Selection rule

Choose the least complex configuration that meets the target accuracy. If a preview or higher-cost ingestion path materially improves daily retrieval quality, retain it with documented operational and rollback controls.

---

## Answer and Citation Contract

```json
{
  "answer": "Attach the handpiece to the connection port as shown in the labeled diagram.",
  "citations": [
    {
      "type": "text",
      "document": "device-manual.pdf",
      "page": 7,
      "chunk_id": "5746428c_p7_para3",
      "bounding_polygon": [1.0, 5.8, 7.2, 5.8, 7.2, 6.3, 1.0, 6.3]
    },
    {
      "type": "figure",
      "document": "device-manual.pdf",
      "page": 7,
      "figure_id": "5746428c_p7_fig0",
      "image_uri": "processing/5746428c/{run_id}/figures/p7-fig0.jpeg",
      "bounding_polygon": [0.8, 1.2, 7.4, 1.2, 7.4, 5.6, 0.8, 5.6],
      "relationship": "illustrates_content",
      "association_method": "adi_caption_link",
      "association_strength": "explicit"
    }
  ]
}
```

The UI can use this contract to:

- display a thumbnail
- open the source PDF at the cited page
- highlight the figure polygon
- highlight supporting text
- distinguish explicit from inferred relationships

---

## Diagnostics

### `figures-debug.md`

```text
Page | Figure | Crop | Area % | Caption | Decision | Reason | Category | Model Called
```

### `figures-routing.jsonl`

```json
{"page":7,"figure_index":0,"decision":"retain","reason":"meaningful_device_component","model_called":true}
```

### `figures-stats.md`

Include:

- total ADI figure candidates
- hard rejected
- routed to figure understanding
- retained as meaningful
- rejected by model
- captioned versus uncaptioned
- explicit versus inferred associations
- orphaned figures
- category distribution
- context-crop retries
- possible missed visual pages

### `visual-retrieval-evaluation.md`

Include side-by-side retrieval metrics for configurations A through F.

---

## Caching and Incremental Processing

### Crop cache

```text
sha256(pdf_bytes)
:page_number
:figure_index
:bounding_polygon_hash
:crop_version
```

### Figure-understanding cache

```text
sha256(image_bytes)
:model_name
:model_version
:prompt_version
:schema_version
:context_text_hash
```

### Page-visual cache

```text
sha256(rendered_page_bytes)
:visual_model
:model_version
:render_version
```

### Incremental update strategy

- unchanged PDF bytes reuse extraction and visual-processing caches
- changed documents are reprocessed
- changed prompts or schemas invalidate only affected enrichment
- changed embedding models invalidate only corresponding vector fields
- visual retrieval experiments can re-index from cached page images

This keeps an accuracy-first design economically manageable.

---

## Configuration

```ini
FIGURE_PROCESSING_ENABLED=true

# Hard-filter thresholds
FIGURE_MIN_AREA_RATIO=0.01
FIGURE_MAX_AREA_RATIO=0.90
FIGURE_MAX_ASPECT_RATIO=8.0
FIGURE_HEADER_FOOTER_OVERLAP_THRESHOLD=0.30
FIGURE_REPEAT_POSITION_TOLERANCE=0.02
FIGURE_REPEAT_MIN_PAGES=3

# Customer-approved figure-understanding model
FIGURE_UNDERSTANDING_PROVIDER=<approved-provider>
FIGURE_UNDERSTANDING_MODEL=<approved-vision-model>
FIGURE_UNDERSTANDING_PROMPT_VERSION=v1
FIGURE_UNDERSTANDING_SCHEMA_VERSION=v1

# Context handling
FIGURE_CONTEXT_CROP_ENABLED=true
FIGURE_CONTEXT_PADDING=0.05

# Relationships
FIGURE_RELATIONSHIP_EXPANSION_ENABLED=true
FIGURE_INFERRED_ASSOCIATION_MIN_SCORE=0.50

# Multimodal retrieval
IMAGE_EMBEDDINGS_ENABLED=false
IMAGE_EMBEDDING_PROVIDER=<approved-provider>
IMAGE_EMBEDDING_MODEL=<approved-model>

# Multi-vector or late-interaction retrieval
VISUAL_PAGE_RETRIEVAL_ENABLED=false
VISUAL_PAGE_ROUTING_MODE=selective
VISUAL_RETRIEVAL_PROVIDER=<approved-provider>
VISUAL_RETRIEVAL_MODEL=<approved-model>

# Preview capabilities
PREVIEW_FEATURES_ALLOWED=true
PREVIEW_FEATURE_DECISION_RECORD_REQUIRED=true
```

---

## Model Abstraction

```python
from typing import Protocol

class FigureUnderstander(Protocol):
    def understand(
        self,
        image_bytes: bytes,
        context: "FigureContext"
    ) -> "FigureUnderstanding": ...


class ImageEmbedder(Protocol):
    def embed_image(self, image_bytes: bytes) -> list[float]: ...
    def embed_text(self, text: str) -> list[float]: ...


class VisualPageRetriever(Protocol):
    def index_page(self, page: "VisualPageInput") -> None: ...
    def search(self, query: str, top_k: int) -> list["VisualPageHit"]: ...
```

The ADI extraction, filtering, association, chunking, and citation logic remain unchanged when a customer switches approved model implementations.

---

## Delivery Phases

### Phase 1: Figure understanding and exact image citations

- PDF object-layer signals
- ADI figure candidates
- conservative deterministic filtering
- one-pass figure understanding
- caption and paragraph association
- figure chunks
- exact citation contract
- diagnostics and caches

### Phase 2: Retrieval strengthening

- relationship expansion
- context-crop retries
- safety-symbol routing
- procedure-step chunks
- page-summary chunks
- multimodal image embeddings

### Phase 3: Visual retrieval evaluation

- Azure AI Search multi-vector preview evaluation
- selected-page visual retrieval
- full-corpus visual retrieval benchmark
- ColPali, ColQwen, or equivalent feasibility test
- score fusion and reranking

A preview feature can move into an earlier phase if it materially improves the acceptance metrics and the customer approves its use.

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| ADI remains the citation authority | Page, spans, figure index, and polygon remain grounded in the source document. |
| Use one figure-understanding call | Qualification and verbalization stay consistent and model-call count is reduced. |
| Use customer-approved models | The architecture is portable across model providers and deployments. |
| Preview capabilities are permitted through an explicit gate | Accuracy improvements can justify preview risk when limitations and rollback are documented. |
| Accuracy is prioritized over one-time ingestion cost | Retrieval quality affects every query while stable corpora are processed infrequently. |
| Deterministic rules are conservative | Hard rejection requires strong evidence to avoid losing meaningful images. |
| Repetition is a signal, not proof of noise | Repeated safety and procedure figures can remain relevant. |
| ADI figures do not map one-to-one to XObjects | Figures can be raster, vector, text, or composite. |
| Model confidence is not treated as calibrated probability | Confidence is retained only as a routing label or signal. |
| Text verbalization is the baseline, not the ceiling | Multimodal and visual retrieval paths remain available when they improve recall. |
| Relationship expansion is part of retrieval quality | Relevant text should be able to bring its supporting figure into the answer. |
| Multi-vector capability requires evaluation | Azure AI Search preview support does not automatically reproduce late-interaction MaxSim behavior. |
| Selective versus full-page indexing is benchmark-driven | Slowly changing corpora can justify broader indexing when recall improves materially. |
| Generated descriptions are metadata, not source text | The original image and ADI citation remain available for inspection. |

---

## Known Gaps

What was actually deployed (Phase 1: 4A/4B/4C + enriched chunks) has one
measured accuracy gap, distinct from the deferred capabilities in
[Delivery Phases](#delivery-phases) above.

### Figures are described without page context ← highest impact

Step 4C's vision call (see [Purpose](#purpose) and the schema above) receives
the cropped image, page number, ADI caption, routing signals, and geometry —
but **no surrounding page text and no document-level context.**

The ADI caption is usually absent: **only 8 of 57 figures** in a real 19-page
catalog had one, so 28 of 36 descriptions were generated with effectively no
text signal. The model describes a crop in isolation, unaware it is reading a
Surface education catalog versus an orthopedic surgical technique guide.

Measured effect (cosine similarity, same corpus, same embedding model):

| Figure | Context available | Best query score |
|---|---|---|
| `Figure 3. Implant planning and balance graph…` | ADI caption present | **0.893** |
| `A group of students sitting on the floor…` | no caption | 0.78–0.83 vs. domain queries |

For reference, an unrelated control query ("Boeing 747 tire pressure") tops out
around 0.78 on this corpus — the noise floor. Captioned figures inherit domain
vocabulary and rank well clear of it; uncaptioned ones get generic descriptive
prose that sits close to noise against clinical or technical queries.

**Fix:** pass (a) document-level context — filename plus a page-1 summary — and
(b) the paragraphs nearest the figure's bounding box, into the step 4C prompt.
The proximity math already exists in `step4a_figures.py` for reference
detection, and the paragraph text is already available in `adi.json` with
coordinates — no extra API calls required, just a larger prompt.

**Cost:** requires a redeploy and re-ingesting existing documents, since it
changes every subsequently generated description.

This is the single highest-leverage improvement identified for this extension
and is not yet implemented.

---

## Relationship to the Existing Pipeline

The existing pipeline remains responsible for:

- ADI extraction
- table confidence and structural routing
- targeted OCR fallback
- table normalization
- paragraph role filtering
- table-row and paragraph chunks
- text embeddings
- hybrid retrieval
- source citations

This extension adds:

- PDF object-layer visual signals
- figure qualification
- visual-noise filtering
- grounded figure verbalization
- figure-to-text relationships
- figure chunks
- multimodal embedding options
- optional multi-vector and visual-page retrieval
- inline image citation metadata
- figure and visual-retrieval diagnostics

---

## References

- [Azure Document Intelligence layout model](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0)
- [Azure Document Intelligence figure-understanding sample](https://github.com/Azure-Samples/document-intelligence-code-samples/blob/main/Python%28v4.0%29/Retrieval_Augmented_Generation_%28RAG%29_samples/sample_figure_understanding.ipynb)
- [Vision-enabled models in Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/gpt-with-vision)
- [Azure AI Search vector search overview](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- [Azure AI Search integrated vectorization](https://learn.microsoft.com/en-us/azure/search/vector-search-integrated-vectorization)
- [Azure AI Search multi-vector field support](https://learn.microsoft.com/en-us/azure/search/vector-search-multi-vector-fields)
- [Azure AI Search hybrid search overview](https://learn.microsoft.com/en-us/azure/search/hybrid-search-overview)
- [ColPali visual document retrieval](https://github.com/illuin-tech/colpali)
- [Multivector document retrieval with ColPali and ColQwen](https://qdrant.tech/documentation/tutorials-search-engineering/pdf-retrieval-at-scale/)
