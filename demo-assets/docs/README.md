# Demo documents

Put PDFs you want to ingest here. The folder is tracked; **its contents are
git-ignored** — these are often customer materials and must not be committed.

```bash
export CORPUS=demo-assets/docs
.venv/bin/python scripts/demo.py upload $CORPUS/your-doc.pdf
```

## What makes a good demo document

| Want | Why |
|---|---|
| 5–10 pages, figure-rich | Full pipeline in ~1–2 min, 100% figure coverage |
| A figure containing **values or labels absent from the body text** | The load-bearing beat — see [DEMO.md](../../docs/DEMO.md) Act 3 |
| Real tables | Exercises table-row chunking alongside figures |
| One large doc (100+ pages) | Shows qualification filtering at scale |
| A 1-page extract | Guaranteed-fast live upload |

Under ~60 figures gets 100% vision coverage (`FIGURE_MAX_PER_DOC`).

## Naming

Filenames appear verbatim as `source_file` in every citation the demo prints.
For a customer demo their real filenames are usually the stronger choice; for
recordings or screenshots, rename to something neutral first.

## Downloading results

After ingest, pull every artifact locally rather than clicking through the
portal:

```bash
.venv/bin/python scripts/demo.py pull your-doc.pdf
# → demo-assets/output/your-doc/   (JSON + figures/*.png)
```
