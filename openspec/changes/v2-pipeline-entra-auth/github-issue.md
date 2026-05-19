# GitHub Issue: Entra auth — replace Foundry key with Managed Identity once supported

**Title:** `feat(auth): replace Foundry/Mistral OCR key with Managed Identity once supported`

**Labels:** `enhancement`, `security`, `entra-auth`

---

## Summary

All Azure SDK calls in the v2 pipeline authenticate via `DefaultAzureCredential`
(Managed Identity in Azure, `az login` locally) — **except** the Mistral OCR call via
Azure AI Foundry.

Azure AI Foundry **Classic** deployments (which host Mistral) do not currently support
Managed Identity or RBAC-based authentication. The endpoint key must be retrieved from
Key Vault at cold start using:

```python
# src/shared/auth.py
def get_foundry_key() -> str:
    client = SecretClient(vault_url=KEY_VAULT_URL, credential=DefaultAzureCredential())
    return client.get_secret("foundry-key").value
```

This is still credential-free at rest (no keys in code or settings), but it requires a
secret in Key Vault that must be rotated manually.

## Acceptance Criteria

When Azure AI Foundry adds Managed Identity / RBAC support for Mistral deployments:

1. Remove `get_foundry_key()` from `src/shared/auth.py`
2. Replace the `Authorization: Bearer <key>` header in `step4_ocr.py` with a token from
   `DefaultAzureCredential().get_token("https://cognitiveservices.azure.com/.default").token`
3. Remove the `foundry-key` secret from Key Vault
4. Remove the `FOUNDRY_KEY_SECRET_NAME` app setting from `functions.bicep`
5. Add `Cognitive Services User` RBAC assignment for the Function App MI on the Foundry resource
   in `functions.bicep` or a new `foundry.bicep` module

## References

- Azure AI Foundry managed identity roadmap: https://aka.ms/foundry-managed-identity
- Current workaround: `src/shared/auth.py::get_foundry_key()`
- Affected file: `src/activities/step4_ocr.py`

---

_To create this issue:_
```bash
cd az-document-intelligence-v2
gh auth login
gh repo create az-document-intelligence-v2 --public --source=. --push
gh issue create \
  --title "feat(auth): replace Foundry/Mistral OCR key with Managed Identity once supported" \
  --body-file openspec/changes/v2-pipeline-entra-auth/github-issue.md \
  --label "enhancement,security"
```
