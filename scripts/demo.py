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
  .venv/bin/python scripts/demo.py ask "question"       # grounded Q&A over the index
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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CORPUS = os.path.join(REPO_ROOT, "demo-assets", "docs")
DEFAULT_OUTPUT = os.path.join(REPO_ROOT, "demo-assets", "output")

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


def _is_wsl() -> bool:
    return "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False


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
    if len(sys.argv) < 2 or (len(sys.argv) < 3 and sys.argv[1] != "ls"):
        print(__doc__)
        sys.exit(1)
    cmd, args = sys.argv[1], sys.argv[2:]
    {
        "upload": cmd_upload, "watch": cmd_watch, "show": cmd_show,
        "crop": cmd_crop, "ask": cmd_ask, "figures": cmd_figures,
        "ls": cmd_ls, "pull": cmd_pull,
    }[cmd](*args)


if __name__ == "__main__":
    main()
