"""Client construction, receipt parsing, run-id/department tests
(points 7, 8, 9, 10, 11, 31)."""
from evaluation.ragas_eval.clients import (
    BaselineClient, TokenWiseClient, safe_parse_receipt, RECEIPT_FIELDS,
)
from evaluation.ragas_eval.config import EvalConfig, new_run_id, eval_department


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_baseline_request_construction(monkeypatch):
    cfg = EvalConfig(baseline_model="llama3.1:latest")
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"model": "llama3.1:latest",
                          "message": {"content": "Paris."},
                          "prompt_eval_count": 10, "eval_count": 5})

    monkeypatch.setattr("evaluation.ragas_eval.clients.requests.post", fake_post)
    out = BaselineClient(cfg).generate("What is the capital of France?")
    assert captured["url"].endswith("/api/chat")
    assert captured["json"]["model"] == "llama3.1:latest"
    assert captured["json"]["stream"] is False
    assert out.answer == "Paris."
    assert out.total_tokens == 15
    assert out.actual_cost == 0.0
    assert out.variant == "baseline"


def test_tokenwise_request_construction_and_receipt(monkeypatch):
    cfg = EvalConfig()
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"answer": "Because caching saves cost.",
                          "receipt": {"provider": "ollama", "model": "llama3.1:latest",
                                      "cache_status": "miss", "selected_tier": "local",
                                      "actual_total_tokens": 42,
                                      "estimated_baseline_cost": 0.01,
                                      "estimated_optimized_cost": 0.004}})

    monkeypatch.setattr("evaluation.ragas_eval.clients.requests.post", fake_post)
    out = TokenWiseClient(cfg).run("why cache?", "ragas-eval-x", "balanced")
    assert captured["url"] == cfg.webhook_url
    assert captured["json"] == {"prompt": "why cache?", "policy_mode": "balanced",
                                "dept_id": "ragas-eval-x"}
    assert out.provider == "ollama"
    assert out.total_tokens == 42
    assert out.modeled_optimized_cost == 0.004
    assert out.receipt["cache_status"] == "miss"


def test_safe_receipt_parsing_fills_missing_fields():
    parsed = safe_parse_receipt({"provider": "ollama"})
    assert parsed["provider"] == "ollama"
    # every known field is present, missing ones default to None
    for field in RECEIPT_FIELDS:
        assert field in parsed
    assert parsed["latency_ms"] is None


def test_unique_run_id_and_department():
    a = new_run_id("smoke")
    b = new_run_id("smoke")
    assert a != b
    assert a.endswith(a.split("-")[-1])
    dep = eval_department(a)
    assert dep == f"ragas-eval-{a}"
    assert eval_department(a) != eval_department(b)


def test_baseline_error_is_captured_not_raised(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise ConnectionError("connection refused to 127.0.0.1:11434")

    monkeypatch.setattr("evaluation.ragas_eval.clients.requests.post", boom)
    out = BaselineClient(EvalConfig()).generate("hi")
    assert out.error and "ConnectionError" in out.error
    assert out.answer is None
