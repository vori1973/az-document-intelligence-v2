# KQL Reference — Azure AI Search Diagnostics

This directory contains Log Analytics (KQL) queries for monitoring Azure AI Search
throttling and latency in production. They complement the load test results by showing
the same patterns from the service's own diagnostic logs.

---

## Step 1 — Enable Search Diagnostics

Azure AI Search does not send diagnostics by default. You must enable them once per service.

### Option A — Azure Portal

1. Open your Azure AI Search resource in the [Azure Portal](https://portal.azure.com)
2. Navigate to **Monitoring** > **Diagnostic settings**
3. Click **+ Add diagnostic setting**
4. Name it (e.g., `search-diagnostics`)
5. Under **Logs**, check:
   - `OperationLogs`
6. Under **Destination**, choose **Send to Log Analytics workspace** and select your workspace
7. Click **Save**

### Option B — Azure CLI

```bash
az monitor diagnostic-settings create \
  --name search-diagnostics \
  --resource $(az search service show \
    --name <search-service-name> \
    --resource-group <rg> \
    --query id -o tsv) \
  --workspace $(az monitor log-analytics workspace show \
    --resource-group <rg> \
    --workspace-name <workspace-name> \
    --query id -o tsv) \
  --logs '[{"category":"OperationLogs","enabled":true}]'
```

---

## Step 2 — Wait for Logs to Arrive

After enabling diagnostics, allow **5–10 minutes** for the first log entries to appear
in Log Analytics. The `AzureDiagnostics` table will contain rows with
`ResourceProvider == "MICROSOFT.SEARCH"`.

---

## Step 3 — Run the KQL Queries

Open Log Analytics in the Azure Portal (**Monitor** > **Log Analytics workspaces** >
select your workspace > **Logs**), then paste and run the queries from this directory:

| File                   | Purpose                                                    |
|------------------------|------------------------------------------------------------|
| `throttling.kql`       | 429 throttle rate grouped by 5-minute window               |
| `latency.kql`          | p50/p95/p99 latency trend by 5-minute window               |
| `semantic-impact.kql`  | Before/after latency comparison when semantic ranker is enabled |

Set the **Time range** to cover your load test window.

---

## Observing Semantic Ranker Impact in Logs

Azure Search diagnostic logs do **not** include a field that identifies whether a query
used semantic ranking — `OperationName` is `Query.Search` for all query types.

The ranker's effect is observable indirectly by comparing latency distributions
**before and after** enabling the semantic ranker on the service:

1. Run your load test with `--profile hybrid`, note the time window
2. Enable semantic ranker: `az search service update --semantic-search free`
3. Run load test with `--profile semantic`, note the new time window
4. Run `semantic-impact.kql` — it compares p95 across two time windows you specify

Set `let before_end` and `let after_start` in the query to match your test times.

Under **high concurrency with semantic profile**, you may see latency climb
without 429s — this reflects the semantic ranker's own quota being exhausted
(separate from replica QPS limits). The advisor flags this as `[SEMANTIC_QUOTA]`.

---

## What the Logs Show

Azure Search diagnostic logs record every search operation including:
- `DurationMs` — server-side processing time (excludes network)
- `HttpStatusCode` — 200 (success), 429 (throttled), 503 (overload)
- `OperationName` — `Query.Search`, `Query.Suggest`, etc.

**Important caveat:** Azure Search diagnostics do not expose replica-level saturation
as a direct metric. The signal is inferred from the pattern:
- Latency climbing over time under sustained load
- HTTP 429s appearing as replica capacity is exhausted
- QPS plateauing even as concurrency increases

The KQL queries surface this pattern — they do not report a single "replica full" number.

---

## More Resources

- [Azure AI Search monitoring reference](https://learn.microsoft.com/azure/search/monitor-azure-cognitive-search)
- [Enable diagnostic logging for Azure AI Search](https://learn.microsoft.com/azure/search/search-monitor-logs)
- [Log Analytics KQL reference](https://learn.microsoft.com/azure/data-explorer/kql-quick-reference)
