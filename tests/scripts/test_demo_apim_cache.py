"""Unit tests for `scripts/demo_apim_cache.py` (task 6.3): the repeatable
demo driver for baseline and built-in-cache operations.

These mock `requests.Session.post` and `subprocess.run` — no network, no
Azure CLI, and no live gateway are required.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "demo_apim_cache.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("demo_apim_cache", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_apim_cache"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo_apim_cache():
    return _load_module()


def _fake_response(status_code: int, headers: dict, body: dict) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, headers=headers, json=lambda: body)


def test_run_sequence_calls_baseline_then_built_in_twice(demo_apim_cache):
    responses = [
        _fake_response(200, {"x-demo-cache": "BYPASS", "x-demo-backend-invocation-id": "b1"}, {"answer": "a", "citations": [], "execution": {}}),
        _fake_response(200, {"x-demo-cache": "BYPASS", "x-demo-backend-invocation-id": "b2"}, {"answer": "a", "citations": [], "execution": {}}),
        _fake_response(200, {"x-demo-cache": "MISS", "x-demo-backend-invocation-id": "b3"}, {"answer": "a", "citations": [], "execution": {}}),
        _fake_response(200, {"x-demo-cache": "HIT", "x-demo-cached-backend-invocation-id": "b3"}, {"answer": "a", "citations": [], "execution": {}}),
    ]

    with patch("requests.Session.post", side_effect=responses) as mock_post:
        results = demo_apim_cache.run_sequence(
            gateway_url="https://example.azure-api.net",
            question="what is x?",
            subscription_key="super-secret-key",
            baseline_repeats=2,
            timeout_seconds=5,
        )

    assert mock_post.call_count == 4
    called_paths = [call.args[0] for call in mock_post.call_args_list]
    assert called_paths[0].endswith("/rag/baseline")
    assert called_paths[1].endswith("/rag/baseline")
    assert called_paths[2].endswith("/rag/apim-built-in")
    assert called_paths[3].endswith("/rag/apim-built-in")

    assert [r.headers.get("x-demo-cache") for r in results] == ["BYPASS", "BYPASS", "MISS", "HIT"]


def test_run_sequence_sends_subscription_key_header_but_never_returns_it(demo_apim_cache):
    responses = [_fake_response(200, {"x-demo-cache": "BYPASS"}, {"answer": "a"})] * 4
    with patch("requests.Session.post", side_effect=responses) as mock_post:
        results = demo_apim_cache.run_sequence(
            gateway_url="https://example.azure-api.net",
            question="q",
            subscription_key="super-secret-key",
            baseline_repeats=2,
            timeout_seconds=5,
        )

    for call in mock_post.call_args_list:
        assert call.kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "super-secret-key"

    for result in results:
        assert "super-secret-key" not in str(result.headers)
        assert "Ocp-Apim-Subscription-Key" not in result.headers


def test_run_sequence_omits_subscription_header_when_none_given(demo_apim_cache):
    responses = [_fake_response(200, {}, {"answer": "a"})] * 4
    with patch("requests.Session.post", side_effect=responses) as mock_post:
        demo_apim_cache.run_sequence(
            gateway_url="https://example.azure-api.net",
            question="q",
            subscription_key=None,
            baseline_repeats=2,
            timeout_seconds=5,
        )
    for call in mock_post.call_args_list:
        assert "Ocp-Apim-Subscription-Key" not in call.kwargs["headers"]


def test_print_result_never_prints_subscription_key(demo_apim_cache, capsys):
    result = demo_apim_cache.CallResult(
        label="baseline #1",
        url="https://example.azure-api.net/rag/baseline",
        status_code=200,
        elapsed_ms=12.3,
        headers={"x-demo-cache": "BYPASS", "x-demo-backend-invocation-id": "abc123"},
        body={"answer": "The warranty covers X.", "citations": [{"sourceFile": "doc.pdf", "page": 1, "type": "paragraph"}], "execution": {"backendInvocationId": "abc123"}},
    )
    demo_apim_cache._print_result(result)
    captured = capsys.readouterr()
    assert "super-secret" not in captured.out
    assert "Ocp-Apim-Subscription-Key" not in captured.out
    assert "doc.pdf" in captured.out
    assert "abc123" in captured.out


def test_resolve_subscription_key_uses_az_cli_and_returns_value(demo_apim_cache):
    account_result = SimpleNamespace(stdout="sub-id\n", returncode=0)
    key_result = SimpleNamespace(stdout="the-key-value\n", returncode=0)
    with patch("subprocess.run", side_effect=[account_result, key_result]) as mock_run:
        key = demo_apim_cache._resolve_subscription_key("rg", "apim", "rag-demo")
    assert key == "the-key-value"
    args = mock_run.call_args_list[1].args[0]
    assert args[:2] == ["az", "rest"]
    assert "--method" in args and "post" in args
    assert any("subscriptions/rag-demo/listSecrets" in value for value in args)


def test_resolve_subscription_key_fails_closed_on_empty_key(demo_apim_cache):
    account_result = SimpleNamespace(stdout="sub-id\n", returncode=0)
    key_result = SimpleNamespace(stdout="\n", returncode=0)
    with patch("subprocess.run", side_effect=[account_result, key_result]):
        with pytest.raises(SystemExit):
            demo_apim_cache._resolve_subscription_key("rg", "apim", "rag-demo")


def test_main_requires_a_key_source_or_explicit_opt_out(demo_apim_cache, capsys):
    exit_code = demo_apim_cache.main(["--gateway-url", "https://example.azure-api.net", "question"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "no-subscription-key" in captured.err
