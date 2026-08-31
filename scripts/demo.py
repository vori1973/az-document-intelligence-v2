#!/usr/bin/env python
"""demo.py — drive the figure-understanding demo without live CLI typing.

Every command takes either a local file path or the name of a blob already in
the `documents` container, so portal uploads work too.

Usage:
  .venv/bin/python scripts/demo.py ls                   # what's in documents/
  .venv/bin/python scripts/demo.py upload <file.pdf>    # fast upload, then follow the run
  .venv/bin/python scripts/demo.py watch <file|blob>    # follow a run (waits for it to appear)
  .venv/bin/python scripts/demo.py show  <file|blob>    # figures.json / understanding / chunks
  .venv/bin/python scripts/demo.py crop  <file|blob> <page> <fig>
  .venv/bin/python scripts/demo.py annotate doc.pdf     # draw kept/rejected boxes on the PDF
  .venv/bin/python scripts/demo.py chat                 # interactive chat with citations
  .venv/bin/python scripts/demo.py ask "question"       # one-shot grounded Q&A
  .venv/bin/python scripts/demo.py figures "query"      # visual retrieval only
  .venv/bin/python scripts/demo.py pull  <file|blob>    # download all artifacts locally

PDFs live in demo-assets/docs/ ; pulled artifacts land in demo-assets/output/.

Uploading via the Azure portal? Start this first — it waits for the blob:
  .venv/bin/python scripts/demo.py watch myfile.pdf
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI

STORAGE = os.environ.get("DEMO_STORAGE", "docintv2devst")
SEARCH = os.environ.get("DEMO_SEARCH", "https://docintv2-dev-search.search.windows.net")
INDEX = os.environ.get("DEMO_INDEX", "document-chunks")
AOAI = os.environ.get("DEMO_AOAI", "https://docintv2-dev-oai-e8436.openai.azure.com/")
CHAT_MODEL = os.environ.get("DEMO_CHAT_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.environ.get("DEMO_EMBED_MODEL", "text-embedding-ada-002")
API_VERSION = "2024-10-21"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORPUS = os.path.join(REPO_ROOT, "demo-assets", "docs")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "demo-assets", "output")

# The embedding/retrieval/answer implementation lives in query/rag so the
# online query Function App (openspec/changes/add-apim-exact-cache-demo) and
# this demo script share one implementation instead of two competing copies.
sys.path.insert(0, os.path.join(REPO_ROOT, "query"))
from rag.answer import SYSTEM_PROMPT as _rag_system_prompt, generate_answer as _rag_generate_answer  # noqa: E402
from rag.retrieval import embed_text as _rag_embed_text, hybrid_search as _rag_hybrid_search  # noqa: E402

CRED = DefaultAzureCredential()

BOLD, DIM, GREEN, CYAN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[32m", "\033[36m", "\033[33m", "\033[0m",
)


def _blobs() -> BlobServiceClient:
    return BlobServiceClient(f"https://{STORAGE}.blob.core.windows.net", credential=CRED)


def _search_headers() -> dict:
    token = CRED.get_token("https://search.azure.com/.default").token
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _aoai() -> AzureOpenAI:
    def _token() -> str:
        return CRED.get_token("https://cognitiveservices.azure.com/.default").token

    return AzureOpenAI(
        azure_endpoint=AOAI, azure_ad_token_provider=_token, api_version=API_VERSION
    )


def _doc_id(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def _run_prefix(doc_id: str) -> str | None:
    """Find the newest run folder for a doc_id."""
    client = _blobs().get_container_client("processing")
    runs = {
        name.split("/")[1]
        for name in client.list_blob_names(name_starts_with=f"{doc_id}/")
        if name.count("/") >= 2 and not name.startswith(f"{doc_id}/_meta")
    }
    if not runs:
        return None
    newest, newest_ts = None, None
    for run in runs:
        try:
            props = client.get_blob_client(f"{doc_id}/{run}/step1-result.json").get_blob_properties()
        except Exception:
            continue
        if newest_ts is None or props.last_modified > newest_ts:
            newest, newest_ts = run, props.last_modified
    return f"{doc_id}/{newest}" if newest else f"{doc_id}/{sorted(runs)[0]}"


def _read_json(path: str):
    client = _blobs().get_container_client("processing")
    try:
        return json.loads(client.get_blob_client(path).download_blob().readall())
    except Exception:
        return None


def _resolve(target: str) -> str:
    """Accept a local path OR the name of a blob already in `documents`.

    Returns the doc_id. Portal uploads have no local file, so fall back to the
    same reverse name-index the delete trigger uses.
    """
    if os.path.isfile(target):
        return _doc_id(target)

    name = os.path.basename(target)
    key = hashlib.sha256(name.encode()).hexdigest()[:32]
    container = _blobs().get_container_client("processing")
    try:
        return container.get_blob_client(f"_name-index/{key}.txt").download_blob().readall().decode().strip()
    except Exception:
        pass

    # Not indexed yet (pipeline still starting) — hash the uploaded blob itself.
    try:
        data = _blobs().get_blob_client("documents", name).download_blob().readall()
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        raise SystemExit(
            f"Could not resolve '{target}'.\n"
            f"  Not a local file, and no blob named '{name}' in the documents container.\n"
            f"  Run: demo.py ls"
        )


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_ls(*_: str) -> None:
    """List what is currently in the documents container."""
    container = _blobs().get_container_client("documents")
    blobs = sorted(container.list_blobs(), key=lambda b: b.name)
    if not blobs:
        print(f"{YELLOW}documents container is empty.{RESET}")
        return
    print(f"\n{BOLD}documents container{RESET}")
    for b in blobs:
        mb = (b.size or 0) / 1_048_576
        print(f"  {b.name:<52} {DIM}{mb:>7.1f} MB  {b.last_modified:%Y-%m-%d %H:%M}{RESET}")
    print()


def cmd_upload(path: str) -> None:
    if not os.path.isfile(path):
        # Bare filename? Look in the demo assets folder.
        candidate = os.path.join(DEFAULT_CORPUS, os.path.basename(path))
        if os.path.isfile(candidate):
            path = candidate
        else:
            raise SystemExit(f"No such file: {path}\n  (also checked {DEFAULT_CORPUS}/)")
    name = os.path.basename(path)
    size = os.path.getsize(path)
    doc_id = _doc_id(path)
    print(f"{BOLD}Uploading{RESET} {name} ({size/1_048_576:.1f} MB)  →  doc_id {CYAN}{doc_id}{RESET}")

    started = time.time()
    with open(path, "rb") as fh:
        _blobs().get_blob_client("documents", name).upload_blob(
            fh,
            overwrite=True,
            max_concurrency=8,        # parallel block upload — the actual speedup
            timeout=600,
        )
    elapsed = time.time() - started
    rate = (size / 1_048_576) / elapsed if elapsed else 0
    print(f"{GREEN}Uploaded in {elapsed:.1f}s{RESET} ({rate:.1f} MB/s). "
          f"Event Grid will trigger the pipeline.\n")
    cmd_watch(path)


STEPS = [
    ("step1-result.json", "step1  pre-analysis"),
    ("step2-result.json", "step2  Document Intelligence"),
    ("step3-result.json", "step3  routing"),
    ("step4a-result.json", "step4a figure crop + qualify"),
    ("step4c-result.json", "step4c vision understanding"),
    ("step5-result.json", "step5  chunk composition"),
    ("step6-result.json", "step6  embeddings"),
    ("step7-result.json", "step7  index upsert"),
]


def cmd_watch(path: str, timeout: int = 1800) -> None:
    started = time.time()

    # Portal upload may not have landed yet — poll for the blob before resolving.
    if not os.path.isfile(path):
        name = os.path.basename(path)
        waited = False
        while time.time() - started < timeout:
            try:
                _blobs().get_blob_client("documents", name).get_blob_properties()
                break
            except Exception:
                if not waited:
                    print(f"{YELLOW}Waiting for '{name}' to appear in documents/ …{RESET} "
                          f"{DIM}(upload it now){RESET}")
                    waited = True
                time.sleep(3)
        else:
            raise SystemExit(f"Timed out waiting for '{name}'.")
        if waited:
            print(f"{GREEN}Blob detected.{RESET}\n")

    doc_id = _resolve(path)
    seen: set[str] = set()
    print(f"{DIM}Watching processing/{doc_id}/ …{RESET}\n")
    while time.time() - started < timeout:
        prefix = _run_prefix(doc_id)
        if prefix:
            for fname, label in STEPS:
                if fname in seen:
                    continue
                data = _read_json(f"{prefix}/{fname}")
                if data is None:
                    break
                seen.add(fname)
                summary = ", ".join(
                    f"{k}={v}" for k, v in data.items()
                    if isinstance(v, (int, str, bool)) and k != "duration_ms"
                )[:110]
                print(f"  {GREEN}✓{RESET} {label:<32} {DIM}{summary}{RESET}")
            if "step7-result.json" in seen:
                print(f"\n{GREEN}{BOLD}Pipeline complete.{RESET}")
                return
        time.sleep(5)
    print(f"{YELLOW}Timed out waiting for the run to finish.{RESET}")


def cmd_show(path: str) -> None:
    doc_id = _resolve(path)
    prefix = _run_prefix(doc_id)
    if not prefix:
        print("No run found. Upload it first.")
        return

    foura = _read_json(f"{prefix}/step4a-result.json") or {}
    print(f"\n{BOLD}── Step 4A/4B — qualification ──{RESET}")
    print(f"  {foura.get('figures_total')} figures found by ADI")
    print(f"  {GREEN}{foura.get('qualified')} qualified{RESET}   "
          f"{YELLOW}{foura.get('rejected')} rejected{RESET}")
    for reason, n in (foura.get("rejected_by_reason") or {}).items():
        print(f"      {DIM}{n:>4}  {reason}{RESET}")

    fourc = _read_json(f"{prefix}/step4c-result.json") or {}
    print(f"\n{BOLD}── Step 4C — vision understanding ──{RESET}")
    print(f"  model {CYAN}{fourc.get('model')}{RESET}   "
          f"{fourc.get('understood')} described in {fourc.get('duration_ms')} ms")
    print(f"  outcomes: {fourc.get('outcomes')}")

    und = _read_json(f"{prefix}/figure-understanding.json") or {}
    records = und if isinstance(und, list) else (und.get("figures") or und.get("records") or [])
    if records:
        rec = records[0]
        print(f"\n{BOLD}── figure-understanding.json (first record) ──{RESET}")
        print(json.dumps(rec, indent=2)[:1200])

    chunks = _read_json(f"{prefix}/chunks.json") or []
    items = chunks if isinstance(chunks, list) else (chunks.get("chunks") or [])
    figs = [c for c in items if (c.get("type") == "figure")]
    print(f"\n{BOLD}── chunks.json ──{RESET}")
    print(f"  {len(items)} chunks total, {CYAN}{len(figs)} figure chunks{RESET}")
    if figs:
        f = figs[0]
        cite = f.get("citation") or {}
        print(f"\n  {DIM}page {cite.get('page')} · {f.get('image_blob')}{RESET}")
        print(f"  {f.get('text_for_embedding','')[:600]}")


def cmd_crop(path: str, page: str, fig: str) -> None:
    doc_id = _resolve(path)
    prefix = _run_prefix(doc_id)
    blob = f"{prefix}/figures/p{page}-fig{fig}.png"
    out = f"/tmp/p{page}-fig{fig}.png"
    data = _blobs().get_container_client("processing").get_blob_client(blob).download_blob().readall()
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"{GREEN}Saved{RESET} {out}  ({len(data):,} bytes)\n  from {DIM}{blob}{RESET}")


def cmd_pull(target: str, dest: str | None = None) -> None:
    """Download every processing artifact for a document to a local folder."""
    doc_id = _resolve(target)
    prefix = _run_prefix(doc_id)
    if not prefix:
        raise SystemExit(f"No run found for {target}. Has it finished ingesting?")

    label = os.path.splitext(os.path.basename(target))[0] or doc_id
    out = os.path.abspath(dest or os.path.join(DEFAULT_OUTPUT, label))
    container = _blobs().get_container_client("processing")

    names = list(container.list_blob_names(name_starts_with=f"{prefix}/"))
    if not names:
        raise SystemExit(f"No artifacts under processing/{prefix}/")

    print(f"{BOLD}Pulling{RESET} {len(names)} artifacts  {DIM}processing/{prefix}/{RESET}")
    total = 0
    for name in names:
        rel = name[len(prefix) + 1:]
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = container.get_blob_client(name).download_blob().readall()
        with open(path, "wb") as fh:
            fh.write(data)
        total += len(data)

    print(f"{GREEN}Saved{RESET} {out}  ({total/1_048_576:.1f} MB)\n")

    figs = sorted(f for f in os.listdir(os.path.join(out, "figures"))) \
        if os.path.isdir(os.path.join(out, "figures")) else []
    jsons = sorted(f for f in os.listdir(out) if f.endswith((".json", ".md")))

    print(f"{BOLD}Artifacts{RESET}")
    for f in jsons:
        size = os.path.getsize(os.path.join(out, f))
        note = ARTIFACT_NOTES.get(f, "")
        print(f"  {f:<28} {DIM}{size/1024:>8.1f} KB  {note}{RESET}")
    if figs:
        print(f"  {'figures/':<28} {DIM}{len(figs):>8} crops{RESET}")

    print(f"\n{BOLD}Browse{RESET}")
    print(f"  cd {out}")
    print(f"  {DIM}# pretty-print any artifact{RESET}")
    print(f"  python -m json.tool figure-understanding.json | less")
    print(f"  {DIM}# every figure description, one per line{RESET}")
    print(f"""  python -c "import json;d=json.load(open('figure-understanding.json'));"""
          f"""[print(r['page'],'|',(r.get('understanding') or {{}}).get('short_description')) for r in d]" """)
    if figs:
        print(f"  {DIM}# open the crops{RESET}")
        print(f"  explorer.exe \"$(wslpath -w figures)\"" if _is_wsl() else f"  open figures/")


ARTIFACT_NOTES = {
    "adi-raw.json": "raw Document Intelligence output (large)",
    "adi-content.md": "extracted markdown",
    "figures.json": "4A/4B — every figure, qualified and rejected, with reasons",
    "figure-understanding.json": "4C — vision descriptions and routing",
    "chunks.json": "composed chunks before embedding",
    "chunks-embedded.json": "chunks with vectors (large)",
    "routing.json": "step3 page routing decisions",
    "step4a-result.json": "qualification summary",
    "step4c-result.json": "vision summary",
    "step7-result.json": "index upsert summary",
}


STAGE_COLORS = {
    "retain": (0.05, 0.65, 0.15),
    "retain_low_confidence": (0.90, 0.65, 0.05),
    "retain_unverified": (0.20, 0.45, 0.85),
    "rejected_geometry": (0.85, 0.10, 0.10),
    "rejected_vision": (0.65, 0.10, 0.55),
    "recovered_retain": (0.00, 0.55, 0.75),
    "recovered_rejected_geometry": (0.55, 0.30, 0.05),
    "recovered_rejected_vision": (0.45, 0.10, 0.65),
}
STAGE_LABELS = {
    "retain": "INDEXED",
    "retain_low_confidence": "INDEXED (low conf)",
    "retain_unverified": "INDEXED (no vision)",
    "rejected_geometry": "REJECTED",
    "rejected_vision": "REJECTED (vision)",
    "recovered_retain": "INDEXED (recovered)",
    "recovered_rejected_geometry": "REJECTED (recovered)",
    "recovered_rejected_vision": "REJECTED (recovered, vision)",
}
# Order used for the annotated legend and the terminal summary.
STAGE_ORDER = (
    "retain", "retain_low_confidence", "retain_unverified",
    "recovered_retain",
    "rejected_geometry", "rejected_vision",
    "recovered_rejected_geometry", "recovered_rejected_vision",
)
UNKNOWN_STAGE_COLOR = (0.35, 0.35, 0.35)


def _load_local_json(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def _verdicts(run_dir: str) -> list[dict]:
    """Join qualification (figures.json) with vision routing (figure-understanding.json)."""
    figures = _load_local_json(os.path.join(run_dir, "figures.json")) or []
    understanding = _load_local_json(os.path.join(run_dir, "figure-understanding.json")) or []
    by_key = {(u["page"], u["figure_index"]): u for u in understanding}

    out = []
    for f in figures:
        u = by_key.get((f["page"], f["figure_index"]))
        if f.get("status") == "rejected":
            stage, why = "rejected_geometry", f.get("rejection_reason") or "rejected"
        elif u is None:
            stage, why = "rejected_geometry", "not analyzed (cap reached)"
        else:
            outcome = u.get("routing_outcome", "retain")
            desc = (u.get("understanding") or {}).get("short_description") or ""
            if outcome == "reject":
                stage, why = "rejected_vision", "vision: not meaningful"
            elif outcome == "retain_unverified":
                stage, why = outcome, "indexed from caption — vision call failed"
            else:
                stage, why = outcome, desc
        # Recovered figures never existed in ADI's own reader output — they
        # were found by cross-checking PDF placement geometry against pages
        # ADI's reader missed. Give them their own stages, but keep the
        # geometry-vs-vision split intact (same as the ADI verdicts) so it
        # stays clear which recovered rejections were cost-controlled before
        # ever reaching the vision model, versus rejected by it.
        if f.get("provenance") == "recovered":
            if stage.startswith("retain"):
                stage = "recovered_retain"
            elif stage == "rejected_vision":
                stage = "recovered_rejected_vision"
            else:
                stage = "recovered_rejected_geometry"
            why = f"recovered from PDF placement — {why}"
        out.append({**f, "stage": stage, "why": why})
    return out


def _save_pdf(pdf, out: str) -> str:
    """Save, falling back to a timestamped name if the target is locked.

    On Windows/WSL an open PDF viewer holds a lock on the file, so overwriting
    raises PermissionError. Failing mid-demo is not acceptable — write a new
    file and say so instead.

    MuPDF raises its own `FzErrorSystem` rather than `PermissionError`, and it
    truncates the message at a fixed length — with a long path the trailing
    "Permission denied" is cut mid-word, so an exact substring test misses the
    very case it exists to catch. Match a prefix of it instead.
    """
    try:
        pdf.save(out, garbage=3, deflate=True)
        return out
    except Exception as exc:
        locked = isinstance(exc, PermissionError) or "Permission de" in str(exc)
        if not locked:
            raise
        stamped = f"{os.path.splitext(out)[0]}-{time.strftime('%H%M%S')}.pdf"
        pdf.save(stamped, garbage=3, deflate=True)
        print(f"{YELLOW}{os.path.basename(out)} is open in another program "
              f"(close it to reuse the name).{RESET}")
        return stamped


def cmd_annotate(target: str, dest: str | None = None) -> None:
    """Draw qualification verdicts onto the source PDF: green kept, red rejected."""
    try:
        import fitz
    except ImportError:
        raise SystemExit("PyMuPDF required:  .venv/bin/pip install --no-compile pymupdf")

    # Scanned pages in this corpus carry a synthetic invisible-OCR font that
    # FreeType cannot parse. MuPDF recovers by substituting a font, but prints
    # one FT_New_Memory_Face line per page to stderr, which buries the actual
    # command output. The glyphs are invisible either way, so the warning is
    # noise, not a signal.
    fitz.TOOLS.mupdf_display_errors(False)

    label = os.path.splitext(os.path.basename(target))[0]
    run_dir = dest or os.path.join(DEFAULT_OUTPUT, label)
    if not os.path.isdir(run_dir):
        raise SystemExit(
            f"No pulled run at {run_dir}\n"
            f"  Run:  .venv/bin/python scripts/demo.py pull {target}"
        )

    src = target if os.path.exists(target) else os.path.join(DEFAULT_CORPUS, os.path.basename(target))
    if not os.path.exists(src):
        raise SystemExit(f"Need the source PDF. Not found: {src}")

    figs = _verdicts(run_dir)
    if not figs:
        raise SystemExit(f"No figures.json in {run_dir}")

    pdf = fitz.open(src)
    counts: dict[str, int] = {}

    for f in figs:
        stage = f["stage"]
        counts[stage] = counts.get(stage, 0) + 1
        page = pdf[f["page"] - 1]

        # ADI polygons are in inches; PDF user space is points, origin top-left.
        poly = f["bounding_polygon"]
        xs, ys = poly[0::2], poly[1::2]
        scale = page.rect.width / f["page_width"]
        rect = fitz.Rect(
            min(xs) * scale, min(ys) * scale, max(xs) * scale, max(ys) * scale
        )

        # An outcome the demo does not know about must not abort the run —
        # draw it in grey and name it, so a new pipeline stage shows up as
        # something to look at rather than as a crash.
        color = STAGE_COLORS.get(stage, UNKNOWN_STAGE_COLOR)
        label_text = STAGE_LABELS.get(stage, stage.upper())
        page.draw_rect(rect, color=color, width=1.6)

        tag = f"{label_text} · {f['figure_id']}"
        if "rejected" in stage:
            tag += f" · {f['why'][:38]}"
        tw = fitz.get_text_length(tag, fontname="helv", fontsize=7) + 6
        band = fitz.Rect(rect.x0, max(0, rect.y0 - 11), min(rect.x0 + tw, page.rect.width), rect.y0)
        page.draw_rect(band, color=color, fill=color)
        page.insert_textbox(band, tag, fontsize=7, fontname="helv",
                            color=(1, 1, 1), align=fitz.TEXT_ALIGN_CENTER)

        note = page.add_rect_annot(rect)
        note.set_colors(stroke=color)
        note.set_info(title=label_text, content=f["why"])
        note.set_opacity(0.85)
        note.update()

    _annotate_legend(pdf, fitz, counts, os.path.basename(src))

    out = _save_pdf(pdf, os.path.join(run_dir, f"{label}-annotated.pdf"))
    pdf.close()

    print(f"\n{BOLD}Annotated{RESET} {os.path.basename(src)} → {GREEN}{out}{RESET}\n")
    total = sum(counts.values())
    # Known stages in reading order, then anything unrecognised, so a stage the
    # demo has not been taught about is still counted in the summary.
    for stage in (*STAGE_ORDER, *sorted(set(counts) - set(STAGE_ORDER))):
        n = counts.get(stage, 0)
        if n:
            pct = 100 * n / total
            print(f"  {STAGE_LABELS.get(stage, stage):<20} {n:>3}  ({pct:4.1f}%)")
    print(f"  {'total detected':<20} {total:>3}")
    recovered_n = (
        counts.get("recovered_retain", 0)
        + counts.get("recovered_rejected_geometry", 0)
        + counts.get("recovered_rejected_vision", 0)
    )
    if recovered_n:
        print(f"  {DIM}({total - recovered_n} by Document Intelligence's reader, "
              f"{recovered_n} recovered from PDF placement){RESET}")
    print(f"\n{DIM}Hover any box in a PDF viewer to read the reason.{RESET}")
    _try_open(out)


def _annotate_legend(pdf, fitz, counts: dict, name: str) -> None:
    """Append a legend page so the colours explain themselves on screen.

    Appended last, never inserted first: a cover page at index 0 shifts every
    source page by one, so the annotated PDF stops agreeing with the page
    numbers printed in the boxes and quoted in the citations.

    The layout scales with page width. The corpus includes 4in-wide pages,
    where the original fixed 50pt margins and 240pt count column ran off the
    edge and the footer lines were clipped mid-sentence.
    """
    w, h = pdf[0].rect.width, pdf[0].rect.height
    page = pdf.new_page(-1, width=w, height=h)

    # Scale down on narrow pages, but never blow the layout up on wide ones.
    scale = min(1.0, w / 612.0)
    margin = max(18.0, 50.0 * scale)
    avail = w - 2 * margin
    bottom = h - margin

    f_title = max(13.0, 20.0 * scale)
    f_name = max(7.5, 10.0 * scale)
    f_row = max(8.0, 11.0 * scale)
    f_note = max(7.5, 10.0 * scale)

    def _block(text, top, size, font, color=None, x0=None, x1=None, align=None) -> float:
        """Draw wrapped text at `top`; return the height it actually used.

        The box always runs to the bottom margin. insert_textbox silently
        draws nothing when the box is too short for even one line, so sizing
        it generously and reading back the unused space is the only reliable
        way to both fit the text and know how far to advance.
        """
        box = fitz.Rect(x0 if x0 is not None else margin, top,
                        x1 if x1 is not None else margin + avail, bottom)
        if box.height <= 0 or box.width <= 0:
            return 0.0
        kwargs = {"fontsize": size, "fontname": font}
        if color is not None:
            kwargs["color"] = color
        if align is not None:
            kwargs["align"] = align
        # The base-14 fonts are Latin-1 only; anything outside it renders as
        # "?", and `name` is a filename we do not control.
        safe = text.encode("latin-1", "replace").decode("latin-1")
        unused = page.insert_textbox(box, safe, **kwargs)
        return box.height - unused if unused >= 0 else box.height

    y = max(30.0, 60.0 * scale)
    y += _block("Figure qualification", y, f_title, "hebo") + f_title * 0.15
    y += _block(name, y, f_name, "helv", color=(0.4, 0.4, 0.4))

    y += max(16.0, 32.0 * scale)
    total = sum(counts.values())
    swatch_w = max(14.0, 24.0 * scale)
    gap = max(6.0, 10.0 * scale)

    for stage in (*STAGE_ORDER, *sorted(set(counts) - set(STAGE_ORDER))):
        n = counts.get(stage, 0)
        if not n or y >= bottom:
            continue
        color = STAGE_COLORS.get(stage, UNKNOWN_STAGE_COLOR)

        # Count is right-aligned to the margin rather than parked at a fixed
        # x, so it cannot collide with the label on a narrow page.
        count_text = f"{n} ({100 * n / total:.0f}%)"
        count_w = fitz.get_text_length(count_text, fontname="helv", fontsize=f_row) + 4
        label_x = margin + swatch_w + gap
        label_w = max(0.0, avail - swatch_w - gap - count_w - 4)

        page.draw_rect(
            fitz.Rect(margin, y + f_row * 0.15, margin + swatch_w, y + f_row * 0.95),
            color=color, fill=color,
        )
        used = _block(STAGE_LABELS.get(stage, stage), y, f_row, "hebo",
                      x0=label_x, x1=label_x + label_w)
        _block(count_text, y, f_row, "helv",
               x0=margin + avail - count_w, x1=margin + avail,
               align=fitz.TEXT_ALIGN_RIGHT)
        y += max(used, f_row) + max(4.0, 7.0 * scale)

    y += max(6.0, 10.0 * scale)
    recovered_n = (
        counts.get("recovered_retain", 0)
        + counts.get("recovered_rejected_geometry", 0)
        + counts.get("recovered_rejected_vision", 0)
    )
    adi_n = total - recovered_n
    geometry_rejected_n = counts.get("rejected_geometry", 0) + counts.get("recovered_rejected_geometry", 0)
    vision_rejected_n = counts.get("rejected_vision", 0) + counts.get("recovered_rejected_vision", 0)
    if recovered_n:
        notes = [
            f"{total} figures total - {adi_n} detected by Document Intelligence's own "
            f"reader, {recovered_n} recovered by cross-checking PDF placement geometry.",
            f"{geometry_rejected_n} boxes (red / brown) never reached the vision model "
            "- that is the cost control.",
            f"{vision_rejected_n} boxes (purple / violet) reached the vision model, "
            "which judged them not meaningful.",
            "Teal boxes were missed by Document Intelligence's reader and only found "
            "by the recovery pass.",
        ]
    else:
        notes = [
            f"{total} figures detected by Document Intelligence.",
            f"{geometry_rejected_n} boxes (red) never reached the vision model - that "
            "is the cost control.",
        ]
        if vision_rejected_n:
            notes.append(
                f"{vision_rejected_n} boxes (purple) reached the vision model, which "
                "judged them not meaningful."
            )
    notes.append("This legend is the last page, so page numbers still match the citations.")
    for note in notes:
        if y >= bottom:
            break
        y += _block(note, y, f_note, "helv", color=(0.3, 0.3, 0.3)) + f_note * 0.4


def _is_wsl() -> bool:
    return "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False


def _embed(text: str) -> list[float]:
    return _rag_embed_text(_aoai(), EMBED_MODEL, text)


def _retrieve(query: str, k: int = 8, only_figures: bool = False) -> list[dict]:
    """Hybrid retrieval. The index has no server-side vectorizer, so the query
    vector is computed here and passed explicitly."""
    return _rag_hybrid_search(
        SEARCH, INDEX, _search_headers(), _embed(query),
        search_text=query, k=k, only_figures=only_figures,
    )


def _vector_scores(query: str, k: int = 5, only_figures: bool = True) -> list[dict]:
    """Pure vector search — the score is cosine similarity, so it is comparable
    across queries. Hybrid/RRF scores are not, which makes them useless for
    deciding whether anything actually matched."""
    return _rag_hybrid_search(
        SEARCH, INDEX, _search_headers(), _embed(query),
        search_text=None, k=k, only_figures=only_figures,
    )


# Measured on this corpus: unrelated queries ("Boeing 747 tire pressure") top out
# around 0.78, genuine matches land at 0.87+. Between the two is "the nearest
# thing we have, but nothing depicts this".
STRONG_MATCH = 0.86
WEAK_MATCH = 0.82


def cmd_figures(query: str) -> None:
    print(f"\n{BOLD}Visual retrieval:{RESET} {CYAN}{query}{RESET}\n")
    hits = _vector_scores(query, k=5, only_figures=True)
    if not hits:
        print(f"{YELLOW}No figures indexed.{RESET}")
        return

    best = hits[0].get("@search.score", 0)
    if best < WEAK_MATCH:
        print(f"{YELLOW}No figure in the corpus depicts this.{RESET} "
              f"{DIM}(best similarity {best:.3f}; unrelated queries score ~0.78){RESET}")
        print(f"{DIM}Showing nearest neighbours anyway — they are not answers.{RESET}\n")
    elif best < STRONG_MATCH:
        print(f"{YELLOW}Weak match.{RESET} {DIM}(best similarity {best:.3f}) "
              f"Nothing clearly depicts this; treat the results as approximate.{RESET}\n")

    for d in hits:
        score = d.get("@search.score", 0)
        mark = (f"{GREEN}●{RESET}" if score >= STRONG_MATCH
                else f"{YELLOW}●{RESET}" if score >= WEAK_MATCH else f"{DIM}○{RESET}")
        print(f"  {mark} {score:.3f}  {GREEN}p{d['page']:<4}{RESET} {d.get('image_blob','')}")
        print(f"        {DIM}{d['source_file'][:46]}{RESET}")
        print(f"        {(d.get('text_for_embedding') or '')[:220]}\n")


# Kept for backward-compat reference; the shared prompt lives in
# query/rag/answer.py (SYSTEM_PROMPT) so this and the Function App answer
# generator never drift.
SYSTEM = _rag_system_prompt


def _answer(question: str, hits: list[dict], history: list[dict] | None = None) -> str:
    return _rag_generate_answer(_aoai(), CHAT_MODEL, question, hits, history).text


TYPE_TAGS = {
    "figure": (CYAN, "Figure"),
    "table_row": (YELLOW, "Table"),
    "paragraph": (DIM, "Text"),
}
_TAG_WIDTH = max(len(label) for _, label in TYPE_TAGS.values())


def _print_sources(hits: list[dict]) -> None:
    """Label every source, not just figures.

    A bare gap next to a text hit reads as "the tool found nothing there",
    which is the opposite of the point: the answer is grounded in a mix of
    prose, table rows, and figures, and the mix is what is worth seeing.
    """
    print(f"{DIM}── sources ──{RESET}")
    for i, d in enumerate(hits):
        color, label = TYPE_TAGS.get(d["type"], (DIM, d["type"]))
        tag = f"{color}[{label:^{_TAG_WIDTH}}]{RESET}"
        # Truncate the middle, not the tail: these filenames differ at the end,
        # so cutting the tail makes distinct documents look identical.
        name = os.path.basename(d["source_file"])
        if len(name) > 40:
            name = f"{name[:22]}…{name[-17:]}"
        row = f"  [{i+1}] {tag} p{d['page']:<3} "
        row += f"{name:<40}  {DIM}{d['image_blob']}{RESET}" if d.get("image_blob") else name
        print(row)


def cmd_ask(question: str) -> None:
    hits = _retrieve(question, k=8)
    print(f"\n{BOLD}Q:{RESET} {question}\n{DIM}retrieved {len(hits)} chunks{RESET}\n")
    print(f"{BOLD}A:{RESET} {_answer(question, hits)}\n")
    _print_sources(hits)


def _standalone(question: str, history: list[dict]) -> str:
    """Rewrite a follow-up into a self-contained query.

    'What about the Pro?' retrieves nothing on its own — it has to carry the
    context of the previous turns before it hits the index.
    """
    if not history:
        return question
    turns = "\n".join(
        f"{m['role']}: {m['content'][:300]}" for m in history[-4:]
    )
    resp = _aoai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content":
                "Rewrite the user's latest question as a standalone search query that "
                "makes sense without the conversation. Resolve pronouns and implied "
                "subjects. Output only the query, nothing else."},
            {"role": "user", "content": f"Conversation:\n{turns}\n\nLatest question: {question}"},
        ],
        temperature=0,
    )
    return resp.choices[0].message.content.strip() or question


CHAT_HELP = f"""{BOLD}Commands{RESET}
  {CYAN}/figure N{RESET}    open the crop behind source [N]
  {CYAN}/sources{RESET}     re-print the last sources
  {CYAN}/docs{RESET}        what's in the index
  {CYAN}/reset{RESET}       clear conversation history
  {CYAN}/help{RESET}        this
  {CYAN}/quit{RESET}        exit  (or Ctrl-D)
"""


def cmd_chat(*_: str) -> None:
    """Interactive grounded chat with citations and inline figure display."""
    print(f"\n{BOLD}Document chat{RESET}  {DIM}{CHAT_MODEL} · grounded in the search index{RESET}")
    print(f"{DIM}Ask a question. /help for commands, /quit to exit.{RESET}\n")

    history: list[dict] = []
    last_hits: list[dict] = []

    while True:
        try:
            q = input(f"{BOLD}{GREEN}you ▸{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not q:
            continue

        if q.startswith("/"):
            cmd, *rest = q[1:].split(maxsplit=1)
            if cmd in ("quit", "exit", "q"):
                return
            if cmd == "help":
                print(CHAT_HELP)
            elif cmd == "reset":
                history, last_hits = [], []
                print(f"{DIM}history cleared{RESET}\n")
            elif cmd == "sources":
                _print_sources(last_hits) if last_hits else print(f"{DIM}nothing yet{RESET}")
                print()
            elif cmd == "docs":
                cmd_ls()
            elif cmd == "figure":
                _open_source_figure(last_hits, rest[0] if rest else "")
            else:
                print(f"{YELLOW}unknown command{RESET} — /help\n")
            continue

        try:
            search_q = _standalone(q, history)
            if search_q.lower() != q.lower():
                print(f"{DIM}   ↳ searching: {search_q}{RESET}")

            hits = _retrieve(search_q, k=8)
            if not hits:
                print(f"{YELLOW}No matching chunks — is anything indexed?{RESET}\n")
                continue

            answer = _answer(q, hits, history)
        except KeyboardInterrupt:
            print(f"\n{DIM}cancelled{RESET}\n")
            continue
        except Exception as exc:
            # A transient search or model failure must not end the session.
            print(f"\n{YELLOW}Request failed:{RESET} {type(exc).__name__}: {exc}\n")
            continue

        last_hits = hits

        print(f"\n{BOLD}{CYAN}bot ▸{RESET} {answer}\n")
        _print_sources(hits)
        figs = [i + 1 for i, d in enumerate(hits) if d["type"] == "figure"]
        if figs:
            print(f"{DIM}  /figure {figs[0]} to view a cited image{RESET}")
        print()

        history += [
            {"role": "user", "content": q},
            {"role": "assistant", "content": answer},
        ]
        history = history[-8:]


def _open_source_figure(hits: list[dict], arg: str) -> None:
    if not hits:
        print(f"{YELLOW}Ask something first.{RESET}\n")
        return
    try:
        idx = int(arg.strip()) - 1
        if idx < 0:
            raise IndexError
        hit = hits[idx]
    except (ValueError, IndexError):
        print(f"{YELLOW}Usage: /figure N  (1–{len(hits)}){RESET}\n")
        return
    if not hit.get("image_blob"):
        print(f"{YELLOW}Source [{idx+1}] is text, not a figure.{RESET}\n")
        return

    # Prefer a pulled copy. It is faster, and it keeps the demo alive when the
    # storage account is unreachable from here — the crops are already on disk
    # for any document that has been through `demo.py pull`.
    local = os.path.join(
        "demo-assets", "output",
        os.path.splitext(hit.get("source_file", ""))[0], hit["image_blob"],
    )
    if os.path.exists(local):
        print(f"{GREEN}Opening{RESET} {local}  {DIM}(page {hit['page']}, local){RESET}")
        _try_open(local)
        print()
        return

    out = os.path.join("/tmp", os.path.basename(hit["image_blob"]))
    try:
        prefix = _run_prefix(hit["document_id"])
        if not prefix:
            raise RuntimeError(f"no run folder for {hit['document_id']}")
        blob = f"{prefix}/{hit['image_blob']}"
        data = _blobs().get_container_client("processing").get_blob_client(blob).download_blob().readall()
    except Exception as exc:
        # Never let a storage problem end the session mid-demo.
        print(f"{YELLOW}Could not fetch the crop from storage:{RESET} {type(exc).__name__}: {exc}")
        if "AuthorizationFailure" in str(exc) or "not authorized" in str(exc):
            print(f"{DIM}  The storage account may have public network access disabled,{RESET}")
            print(f"{DIM}  or your sign-in lacks a data-plane role.{RESET}")
        print(f"{DIM}  Local fallback would be: {local}{RESET}")
        print(f"{DIM}  Populate it with: demo.py pull {hit.get('source_file','<doc>')}{RESET}\n")
        return
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"{GREEN}Saved{RESET} {out}  {DIM}(page {hit['page']}){RESET}")
    _try_open(out)
    print()


def _try_open(path: str) -> None:
    """Best-effort: show the image in the host's default viewer."""
    import shutil
    import subprocess
    for cmd in (["wslview"], ["xdg-open"], ["open"]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    if _is_wsl() and shutil.which("explorer.exe"):
        win = subprocess.run(["wslpath", "-w", path], capture_output=True, text=True).stdout.strip()
        subprocess.Popen(["explorer.exe", win], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    if len(sys.argv) < 2 or (len(sys.argv) < 3 and sys.argv[1] not in ("ls", "chat")):
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    {
        "upload": cmd_upload, "watch": cmd_watch, "show": cmd_show,
        "crop": cmd_crop, "ask": cmd_ask, "figures": cmd_figures,
        "ls": cmd_ls, "pull": cmd_pull, "chat": cmd_chat, "annotate": cmd_annotate,
    }[cmd](*args)


if __name__ == "__main__":
    main()
