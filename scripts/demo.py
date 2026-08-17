#!/usr/bin/env python
"""demo.py — drive the figure-understanding demo without live CLI typing.

Usage:
  .venv/bin/python scripts/demo.py upload <file.pdf>   # ingest and follow the run
  .venv/bin/python scripts/demo.py watch <file.pdf>    # follow an in-flight run
  .venv/bin/python scripts/demo.py show <file.pdf>     # figures.json / understanding / chunks
  .venv/bin/python scripts/demo.py crop <file.pdf> <page> <fig>   # save a crop locally
  .venv/bin/python scripts/demo.py ask "question"      # grounded Q&A over the index
  .venv/bin/python scripts/demo.py figures "query"     # visual retrieval only
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import requests
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


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_upload(path: str) -> None:
    name = os.path.basename(path)
    doc_id = _doc_id(path)
    print(f"{BOLD}Uploading{RESET} {name}  →  doc_id {CYAN}{doc_id}{RESET}")
    with open(path, "rb") as fh:
        _blobs().get_blob_client("documents", name).upload_blob(fh, overwrite=True)
    print(f"{GREEN}Uploaded.{RESET} Event Grid will trigger the pipeline.\n")
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
    doc_id = _doc_id(path)
    seen: set[str] = set()
    started = time.time()
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
    doc_id = _doc_id(path)
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
    doc_id = _doc_id(path)
    prefix = _run_prefix(doc_id)
    blob = f"{prefix}/figures/p{page}-fig{fig}.png"
    out = f"/tmp/p{page}-fig{fig}.png"
    data = _blobs().get_container_client("processing").get_blob_client(blob).download_blob().readall()
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"{GREEN}Saved{RESET} {out}  ({len(data):,} bytes)\n  from {DIM}{blob}{RESET}")


def _embed(text: str) -> list[float]:
    return _aoai().embeddings.create(model=EMBED_MODEL, input=[text]).data[0].embedding


def _retrieve(query: str, k: int = 8, only_figures: bool = False) -> list[dict]:
    """Hybrid retrieval. The index has no server-side vectorizer, so the query
    vector is computed here and passed explicitly."""
    body = {
        "search": query,
        "top": k,
        "select": "id,type,page,source_file,image_blob,text_for_embedding",
        "vectorQueries": [
            {"kind": "vector", "vector": _embed(query), "fields": "embedding", "k": k}
        ],
    }
    if only_figures:
        body["filter"] = "type eq 'figure'"
    r = requests.post(
        f"{SEARCH}/indexes/{INDEX}/docs/search?api-version=2024-07-01",
        headers=_search_headers(), json=body, timeout=60,
    )
    r.raise_for_status()
    return r.json().get("value", [])


def cmd_figures(query: str) -> None:
    print(f"\n{BOLD}Visual retrieval:{RESET} {CYAN}{query}{RESET}\n")
    for d in _retrieve(query, k=5, only_figures=True):
        print(f"  {GREEN}p{d['page']:<4}{RESET} {d.get('image_blob','')}")
        print(f"        {DIM}{d['source_file'][:46]}{RESET}")
        print(f"        {(d.get('text_for_embedding') or '')[:220]}\n")


SYSTEM = (
    "You answer questions about technical/medical documents using ONLY the numbered "
    "sources provided. Cite every claim as [n]. Sources marked [Figure] came from a "
    "vision model reading the image — when you use one, say which page's figure it was. "
    "If the sources do not contain the answer, say so plainly rather than guessing."
)


def cmd_ask(question: str) -> None:
    hits = _retrieve(question, k=8)
    print(f"\n{BOLD}Q:{RESET} {question}\n{DIM}retrieved {len(hits)} chunks{RESET}\n")
    context = "\n\n".join(
        f"[{i+1}] ({d['type']}, page {d['page']}, {os.path.basename(d['source_file'])})"
        f"\n{d.get('text_for_embedding','')}"
        for i, d in enumerate(hits)
    )
    resp = _aoai().chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0,
    )
    print(f"{BOLD}A:{RESET} {resp.choices[0].message.content}\n")
    print(f"{DIM}── sources ──{RESET}")
    for i, d in enumerate(hits):
        tag = f"{CYAN}[Figure]{RESET} " if d["type"] == "figure" else ""
        img = f"  {DIM}{d.get('image_blob')}{RESET}" if d.get("image_blob") else ""
        print(f"  [{i+1}] {tag}p{d['page']} {os.path.basename(d['source_file'])[:40]}{img}")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    {
        "upload": cmd_upload, "watch": cmd_watch, "show": cmd_show,
        "crop": cmd_crop, "ask": cmd_ask, "figures": cmd_figures,
    }[cmd](*args)


if __name__ == "__main__":
    main()
