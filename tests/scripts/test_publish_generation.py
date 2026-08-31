"""Static contract tests for `scripts/publish_generation.sh` (task 6.2).

These read the checked-in script text and run `bash -n` for a syntax check —
no Azure resources or credentials are needed. They exist to keep the script's
guard behavior (explicit required inputs, ingestion-completion check before
queryability check before publish, fail-closed on any failure, and never
printing the subscription key) from silently regressing.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "publish_generation.sh")


def read_script() -> str:
    with open(SCRIPT_PATH, encoding="utf-8") as handle:
        return handle.read()


def test_script_exists_and_is_executable():
    assert os.path.isfile(SCRIPT_PATH)
    assert os.access(SCRIPT_PATH, os.X_OK), "publish_generation.sh must be executable (chmod +x)"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", SCRIPT_PATH], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_script_fails_closed_on_missing_arguments():
    """Every input the guard depends on has no default — omitting it must be
    a hard error, not a silent fallback."""
    script = read_script()
    for required in (
        "RESOURCE_GROUP",
        "APIM_NAME",
        "STORAGE_ACCOUNT",
        "DOC_ID",
        "RUN_ID",
        "PROBE_QUESTION",
        "PROBE_EXPECT",
        "GATEWAY_URL",
        "NEW_GENERATION",
    ):
        assert f'[[ -z "${{{required}}}" ]]' in script, f"{required} must be validated as required"
    assert "missing required argument(s)" in script
    assert 'exit 1' in script


def test_script_verifies_ingestion_completion_before_publish():
    script = read_script()
    ingestion_index = script.index("Verifying ingestion completion")
    publish_index = script.index("az apim nv update")
    assert ingestion_index < publish_index, "ingestion completion must be checked before publication"
    assert "step7-result.json" in script
    assert "docpipelineInstances" not in script  # task hub is parameterized, not hardcoded
    assert 'INSTANCES_TABLE="${TASK_HUB}Instances"' in script
    assert 'RuntimeStatus' in script


def test_script_verifies_queryability_before_publish():
    script = read_script()
    queryability_index = script.index("Verifying the new corpus is queryable")
    publish_index = script.index("az apim nv update")
    assert queryability_index < publish_index, "queryability must be checked before publication"
    assert "/rag/baseline" in script, "the queryability probe must use the uncached baseline operation"
    assert "/rag/apim-built-in" not in script, "the probe must not use the cached operation (would pollute the cache)"


def test_script_publishes_only_after_both_checks_pass():
    script = read_script()
    # The publish step is reached only by falling through from the checks
    # above (each of which `exit 1`s on failure) — confirm no bypass flag.
    assert "--force" not in script
    assert "--skip-checks" not in script
    assert "--skip-ingestion-check" not in script
    assert "--skip-probe" not in script


def test_script_supports_dry_run_without_publishing():
    script = read_script()
    assert "--dry-run" in script
    assert "DRY_RUN" in script
    dry_run_index = script.index('if [[ "${DRY_RUN}" -eq 1 ]]')
    publish_index = script.index("az apim nv update")
    assert dry_run_index < publish_index


def test_script_never_prints_the_subscription_key():
    script = read_script()
    assert "SUBSCRIPTION_KEY" in script
    # No echo/printf statement may reference the variable.
    for line in script.splitlines():
        if "SUBSCRIPTION_KEY" in line and ("echo" in line or "printf" in line):
            raise AssertionError(f"a line references SUBSCRIPTION_KEY alongside echo/printf: {line!r}")
    assert "unset SUBSCRIPTION_KEY" in script


def test_script_uses_apim_list_secrets_arm_action():
    script = read_script()
    assert "az rest" in script
    assert "/subscriptions/${SUBSCRIPTION_NAME}/listSecrets" in script
    assert "az apim subscription show" not in script


def test_script_requires_authenticated_az_session():
    script = read_script()
    assert "az account show" in script
    assert "az login" in script
