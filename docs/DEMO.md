# Demo Guide — Figure Understanding & Visual Retrieval

**What you're proving:** the pipeline extracts figures from PDFs, decides which
ones are worth understanding, has a vision model read them, and makes their
*visual* content retrievable — so a question can be answered from a number that
appears only inside an image.

**Runtime:** ~10 minutes. Every command below was run against the live `dev`
deployment and produced the output shown.

---

## Before you start

### Choosing the corpus

Two different rules, don't conflate them:

- **In this repo** — never commit customer or product names. Code, docs, tests,
  and commit messages stay generic. That's why this guide says `doc1`/`doc2`.
- **In the live demo** — use whatever PDFs fit the audience, real names and all.
  Showing a customer *their own* documents is usually the stronger demo.

Because `source_file` appears in every citation on screen, the corpus is also
your tenant boundary. Wiping it between customers takes about a minute:

```bash
# remove everything from the previous demo (index cleanup cascades automatically)
az storage blob delete-batch --account-name docintv2devst -s documents --auth-mode login

# load this customer's documents
az storage blob upload-batch --account-name docintv2devst -d documents \
  -s /path/to/their/pdfs --pattern "*.pdf" --auth-mode login
```

Deleting a blob fires the delete trigger, which removes that document's chunks
from the index and its artifacts from `processing/` — so no trace of the
previous customer survives into the next demo. Verify with:

```bash
.venv/bin/python scripts/demo.py figures "surgical device"   # should return nothing
```

Then re-run *Act 2* against one of the new docs to confirm figure coverage
before you present — the numbers in this guide are from the sample corpus and
will differ for theirs.

**What to look for when picking documents:**

| Want | Why |
|---|---|
| One 5–10 page doc, figure-rich | Fast full-pipeline run, 100% figure coverage for Q&A |
| A figure containing **numbers or labels not in the body text** | This is the whole demo — see Act 3 |
| One large doc (100+ pages) | Shows qualification filtering at scale |
| A 1-page extract | Guaranteed-fast live upload if you're short on time |

### Smoke test

Point `$CORPUS` at wherever this demo's PDFs live — every command below uses it,
so you set the path once:

```bash
cd /path/to/az-document-intelligence-v2
az login                            # DefaultAzureCredential needs this
export CORPUS=/path/to/demo/pdfs    # doc1.pdf, doc2.pdf, ... (name them as you like)

.venv/bin/python scripts/demo.py show $CORPUS/doc1.pdf
```

If that prints a qualification summary, you're ready.

**Pre-flight checklist:**

- [ ] `az login` done, correct subscription selected
- [ ] Previous customer's documents cleared, if relevant
- [ ] At least two docs ingested — **never demo on an empty index**
- [ ] You know which figure answers your Act 3 question, and have seen the crop
- [ ] Terminal font large enough to read; window wide (output is ~110 cols)
- [ ] An image viewer ready for `/tmp/*.png`

**Reference corpus used for the outputs in this guide:**

| Doc | Pages | Figures | Described | Coverage |
|---|---|---|---|---|
| `doc1` — surgical technique paper | 6 | 12 | 11 | **100%** — use this for Q&A |
| `doc2` — product catalog | 159 | 330 | 60 of 195 | capped by `FIGURE_MAX_PER_DOC` |

> Ask figure questions against **doc1**. The catalog is for showing *scale*
> (330 figures, 135 auto-rejected), not deep-page recall.

---

## Act 1 — Ingest (~2 min)

Upload a third document live so the audience sees the pipeline run, while the
two already-indexed docs guarantee the later acts work regardless.

> Filenames become the `source_file` shown in every citation, so the demo corpus
> uses neutral names (`doc1`…`doc4`). Regenerate it from your own PDFs with the
> *Preparing the corpus* step below.

```bash
.venv/bin/python scripts/demo.py upload $CORPUS/doc4.pdf
```

**Short on time or want a guaranteed-fast run?** Use the 1-page extract instead
(~60–90 s, still exercises 4A/4C):

```bash
.venv/bin/python scripts/demo.py upload $CORPUS/doc3.pdf
```

Drop the PDF in a blob container — that's the entire integration surface.
Event Grid fires, a Durable Functions orchestration takes over, and each step
appears as it completes:

```
  ✓ step1  pre-analysis              page_count=72, ...
  ✓ step2  Document Intelligence     ...
  ✓ step3  routing                   ...
  ✓ step4a figure crop + qualify     figures_total=..., qualified=..., rejected=...
  ✓ step4c vision understanding      understood=..., model=gpt-4o-mini
  ✓ step5  chunk composition         ...
  ✓ step6  embeddings                ...
  ✓ step7  index upsert              indexed=...
```

**Say:** *"No API to call, no SDK to embed. Drop a file in blob storage. Every
step writes its own result artifact, so any run is auditable after the fact."*

While it runs, move to Act 2 in a second terminal.

---

## Act 2 — What the pipeline decided (~2 min)

```bash
.venv/bin/python scripts/demo.py show $CORPUS/doc1.pdf
```

### Beat 1 — figures are triaged before spending money

```
── Step 4A/4B — qualification ──
  12 figures found by ADI
  11 qualified   1 rejected
        1  low_value_graphic
```

**Say:** *"Document Intelligence found 12 figures. Not all are worth a vision
call — logos, rule lines, separators. A deterministic geometry pass rejects
those before any model runs."*

Show the scale version on the catalog:

```bash
.venv/bin/python scripts/demo.py show $CORPUS/doc2.pdf
```

```
  330 figures found by ADI
  195 qualified   135 rejected
       105  low_value_graphic       <- the repeated 0.33in corner logo
        16  decorative_geometry     <- thin banner rules
        14  structural_noise
```

**Say:** *"41% filtered out on geometry alone — that's 135 vision calls not made,
per ingest, forever. And it's deterministic: same input, same decision, no model
variance to explain to an auditor."*

### Beat 2 — the structured output

The `figure-understanding.json` record is schema-enforced, not free text:

```json
{
  "routing_outcome": "retain",
  "understanding": {
    "is_meaningful": true,
    "category": "device_photo",
    "model_confidence_label": "high",
    "short_description": "The image shows the robotic-assisted surgical system with multiple components including monitors and robotic arms.",
    "visible_labels": ["<device name>"],
    "device_or_component_terms": ["robotic-assisted solution", "monitor", "robotic arm"],
    "warnings_or_constraints": [],
    "search_keywords": ["robotic-assisted surgery", "surgical robot", "medical device"],
    "uncertainty": [],
    "needs_larger_context_crop": false
  }
}
```

**Say:** *"Strict JSON schema, fixed category taxonomy. The model is instructed
not to invent identities, measurements, or warnings, and to declare what it
can't read — that's the `uncertainty` field. Those fields become searchable
text, so a figure is findable by what's in it, not just its caption."*

---

## Act 3 — Ask a question only the image can answer (~3 min)

**This is the whole demo. Do not rush it.**

> **Prepare this beforehand.** Find a figure in *your* corpus containing a value
> or label that isn't in the surrounding text, and build the question around it.
> `demo.py figures "<what the image shows>"` is the fastest way to find one, then
> `demo.py crop` to confirm what's visible. Rehearse it once — this beat carries
> the demo, and improvising it in front of an audience is how it falls flat.

```bash
.venv/bin/python scripts/demo.py ask \
  "What does the balance graph show about mechanical alignment in extension?"
```

Example from the reference corpus:

```
A: The balance graph for mechanical alignment shows that the total knee
   arthroplasty (TKA) will be too tight medially in extension, with a measured
   value of 9mm compared to a target value of 12mm [1].

── sources ──
  [1] [Figure] p3 doc1.pdf  figures/p3-fig3.png
  [2] [Figure] p4 doc1.pdf  figures/p4-fig7.png
  [3]          p3 doc1.pdf
```

Pause on the numbers. **Then reveal the evidence:**

```bash
.venv/bin/python scripts/demo.py crop $CORPUS/doc1.pdf 3 3
# opens /tmp/p3-fig3.png
```

Here the crop is a planning screenshot with **9.0 mm outlined in red** and
**12.0 mm** directly beside it — the answer, visible on screen.

**Say:** *"Those numbers appear nowhere in the document's text. They're pixels
in a screenshot. Before this extension, that question was unanswerable — the
chunk would have been the caption and nothing more."*

### Beat 2 — find images by description

```bash
.venv/bin/python scripts/demo.py figures "gloved hand holding a surgical instrument"
```

```
  p32   figures/p32-fig83.png   A medical device being held by a gloved hand...
  p28   figures/p28-fig73.png   A surgical device with a blue and silver colour scheme...
```

**Say:** *"None of those words are in the caption. We're searching what the
image depicts."*

### Beat 3 — the trust test (don't skip)

```bash
.venv/bin/python scripts/demo.py ask "What is the recommended tire pressure for a Boeing 747?"
```

```
A: The provided sources do not contain any information regarding the
   recommended tire pressure for a Boeing 747.
```

**Say:** *"It retrieves the nearest chunks and still declines. In a regulated
domain, refusing is the feature."*

---

## Act 4 — Close (~1 min)

Point at the citation trail: every answer carries document, **page**, bounding
polygon, and the exact crop it came from.

Worth mentioning: *"Until this week every citation in this system said page 1.
Document Intelligence returns camelCase JSON, the code read snake_case, every
lookup silently fell back to a default. 81 unit tests now pin that."* — it's a
credible, concrete war story if the audience is technical.

---

## Why the demo doesn't use Foundry's chat UI

Short answer: **the index has no vectorizer**, so Foundry can't run vector
search against it.

### The mechanics

Two different jobs get confused here:

| | Who embeds | When |
|---|---|---|
| **Indexing** | our `step6_embed` activity | at ingest |
| **Querying** | *someone* must embed the question | at query time |

We solved indexing. But a search index can also store a **vectorizer** — a
saved pointer to an embedding deployment (endpoint + model + auth) that lets
AI Search embed *query text on the service side*.

Ours is empty:

```
vectorizers: []
profiles: ['default-profile']
```

Foundry's "add your data" assumes the service can do that. It sends a **text**
vector query — "here's the question, you embed it":

```json
{"vectorQueries": [{"kind": "text", "text": "...", "fields": "embedding"}]}
```

Against this index that is a hard failure:

```
HTTP 400 InvalidRequestParameter
Field 'embedding' does not have a vectorizer defined in it's vector profile.
```

`demo.py` sends **`kind: "vector"`** instead — it calls the embedding
deployment itself and passes the raw 1536-float array, so the service never
needs to know how to embed:

```json
{"vectorQueries": [{"kind": "vector", "vector": [0.021, -0.017, ...], "fields": "embedding"}]}
```

### "Silently degrade" — the part that actually bites

The 400 above is the *good* case: it's loud. The dangerous case is a client
configured for hybrid search that catches the vector failure and falls back to
keyword-only, or one that only ever sends the `search` text field. You still
get results and no error — but you've quietly lost semantic matching.

That is exactly what this demo depends on. `"gloved hand holding a surgical
instrument"` works **because** of vector similarity. Keyword-only, the phrase
barely overlaps the stored description and the right figure drops down the
ranking. **The demo would look weaker without announcing it broke.**

### Fixing it (after the demo)

Add a vectorizer to the index and give the search service's managed identity
`Cognitive Services OpenAI User` on the AOAI resource:

```jsonc
"vectorSearch": {
  "vectorizers": [{
    "name": "aoai-vectorizer",
    "kind": "azureOpenAI",
    "azureOpenAIParameters": {
      "resourceUri": "https://docintv2-dev-oai-e8436.openai.azure.com/",
      "deploymentId": "text-embedding-ada-002",
      "modelName": "text-embedding-ada-002"
    }
  }],
  "profiles": [{ "name": "default-profile", "vectorizer": "aoai-vectorizer", ... }]
}
```

~20 minutes including the role assignment and a re-verify. **Not worth doing the
night before a demo** — it touches a working index, and `demo.py` already gives
you better narrative control than a chat box anyway.

---

## If something breaks

| Symptom | Cause | Do this |
|---|---|---|
| `upload` hangs past ~3 min | Cold start, or a large PDF | Keep talking; run Act 2 on the pre-indexed doc |
| Q&A returns no figure sources | Question doesn't need the image | Use the balance-graph question verbatim |
| `AuthenticationFailed` | Token expired | `az login` |
| Catalog figure question is vague | Beyond the 60-figure cap | Switch to doc1 |
| Index looks empty | Wrong index/endpoint | `demo.py figures "surgical device"` to confirm |

**Full reset** (rebuilds in ~10 min, don't do this near showtime):

```bash
az storage blob delete-batch --account-name docintv2devst -s documents --auth-mode login
# deletes cascade to the index via the delete trigger
az storage blob upload-batch --account-name docintv2devst -d documents -s "$CORPUS" --auth-mode login
```

---

## Reference

```bash
demo.py upload <pdf>          # ingest + stream step results
demo.py watch  <pdf>          # follow an in-flight run
demo.py show   <pdf>          # qualification, understanding record, chunks
demo.py crop   <pdf> <pg> <n> # save a crop to /tmp
demo.py ask    "question"     # grounded Q&A with cited figure sources
demo.py figures "query"       # visual retrieval only
```

Overridable: `DEMO_STORAGE`, `DEMO_SEARCH`, `DEMO_INDEX`, `DEMO_AOAI`,
`DEMO_CHAT_MODEL`, `DEMO_EMBED_MODEL`.

Operational settings: [DEPLOYMENT.md](../DEPLOYMENT.md#figure-understanding-settings) ·
Design: [figure-understanding-extension.md](figure-understanding-extension.md) ·
Spec: [`openspec/changes/add-figure-understanding/`](../openspec/changes/add-figure-understanding/)
