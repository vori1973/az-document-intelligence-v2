# demo-assets/output

Landing folder for `demo.py pull` — the downloaded processing artifacts for a
document run.

```bash
.venv/bin/python scripts/demo.py pull MyDoc.pdf
```

That creates `demo-assets/output/MyDoc/` containing the run prefix as it exists
in the `processing` container:

| Artifact | What it is |
|---|---|
| `adi.json` | raw Document Intelligence layout output |
| `figure-understanding.json` | vision-model description per qualified figure |
| `chunks.json` | the text/table/figure chunks that were indexed |
| `figures/pN-figM.png` | the cropped figure images |

Reading these locally is far easier than clicking through the portal, which is
the whole reason `pull` exists.

## Contents are git-ignored

**The folder is tracked; everything you download into it is not.** Pulled runs
are derived from source PDFs that may be customer material, so they must never
land in the repo — and they are regenerable at any time by re-running `pull`.

Only `.gitkeep` and this README are committed. See `.gitignore`.

Between customers, delete the subfolders you no longer want on disk:

```bash
rm -rf demo-assets/output/*/
```
