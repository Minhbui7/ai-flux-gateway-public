import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "adapter_verifier", Path(__file__).resolve().parents[2] / "gateway/tools/verify_adapter.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_empty_success_is_not_a_completion():
    for payload in (None, {}, {"choices": []}, {"choices": [{}]}):
        assert not module.is_completion(payload)


def test_completion_acceptance_checks_the_requested_large_output_ceiling():
        payload = {
            "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 100000, "total_tokens": 100009},
        }
        assert module.is_completion(payload, max_completion_tokens=100000)
        payload["usage"] = {"prompt_tokens": 9, "completion_tokens": 100001, "total_tokens": 100010}
        assert not module.is_completion(payload, max_completion_tokens=100000)


def test_completion_requires_text_finish_reason_and_bounded_consistent_usage():
    payload = {
        "choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
    }
    assert module.is_completion(payload)
    payload["usage"]["total_tokens"] = 14
    assert not module.is_completion(payload)
    payload["usage"] = {"prompt_tokens": 9, "completion_tokens": 65, "total_tokens": 74}
    assert not module.is_completion(payload)
