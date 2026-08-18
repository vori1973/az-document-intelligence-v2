# demo-assets/output

Landing folder for `demo.py pull`. Downloaded runs appear here as
`demo-assets/output/<doc-name>/`.

**The folder is tracked; its contents are git-ignored.** Pulled artifacts are
derived from source PDFs that may be customer material, and they are
regenerable at any time by re-running `pull` — so they never belong in the
repo. Only `.gitkeep` and this file are committed.

Between customers:

```bash
rm -rf demo-assets/output/*/
```

Usage and what each artifact contains: [docs/DEMO.md](../../docs/DEMO.md) Act 2.
