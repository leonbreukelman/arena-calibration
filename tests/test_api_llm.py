from __future__ import annotations

import io
import json
import urllib.error

import pytest


VALID_DIFF = "--- a/tokenizer.py\n+++ b/tokenizer.py\n@@ -1 +1 @@\n-a\n+b\n"


def _fake_key(*parts: str) -> str:
    return "".join(parts)


class _Response:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _chat_response(content):
    return {"choices": [{"message": {"content": content}}]}


def test_xai_worker_sends_openai_chat_payload_with_prompt_parity_and_timeout(monkeypatch):
    import arena.api_llm as api_llm
    from arena.llm import _REGEN_SYSTEM, build_regen_prompt

    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response(_chat_response(VALID_DIFF))

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    xai_key = _fake_key("xai-", "test-", "key")
    worker = api_llm.XAIWorker(api_key=xai_key, timeout_seconds=12)
    result = worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py")

    assert result == VALID_DIFF
    assert captured["url"] == "https://api.x.ai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {xai_key}"
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"]["model"] == "grok-4.3"
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["max_tokens"] == 1024
    assert captured["body"]["messages"][0] == {"role": "system", "content": _REGEN_SYSTEM}
    user = captured["body"]["messages"][1]
    assert user["role"] == "user"
    assert user["content"] == build_regen_prompt(
        target_path="tokenizer.py",
        file_contents="SOURCE",
        reasoning="REASON",
    )
    assert captured["timeout"] == 12


def test_xai_judge_uses_terse_summary_contract_and_512_max_tokens(monkeypatch):
    import arena.api_llm as api_llm
    from arena.llm import _JUDGE_SYSTEM, build_judge_prompt

    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(_chat_response("one sentence."))

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    judge = api_llm.XAIJudge(api_key=_fake_key("xai-", "test-", "key"))
    result = judge.summarize("F1", "c0: load_bearing=True")

    assert result == "one sentence."
    assert captured["body"]["model"] == "grok-4.3"
    assert captured["body"]["max_tokens"] == 512
    assert captured["body"]["temperature"] == 0.0
    assert captured["body"]["messages"][0] == {"role": "system", "content": _JUDGE_SYSTEM}
    assert captured["body"]["messages"][1]["content"] == build_judge_prompt(
        "F1",
        "c0: load_bearing=True",
    )


def test_api_adapter_uses_shared_prompt_and_generation_defaults():
    import arena.api_llm as api_llm
    import arena.llm as llm

    assert api_llm.build_regen_prompt is llm.build_regen_prompt
    assert api_llm.build_judge_prompt is llm.build_judge_prompt
    assert api_llm.WORKER_MAX_TOKENS == llm.WORKER_MAX_TOKENS
    assert api_llm.JUDGE_MAX_TOKENS == llm.JUDGE_MAX_TOKENS
    assert api_llm.WORKER_TEMPERATURE == llm.WORKER_TEMPERATURE
    assert api_llm.JUDGE_TEMPERATURE == llm.JUDGE_TEMPERATURE
    assert api_llm.XAIWorker().max_tokens == llm.WORKER_MAX_TOKENS
    assert api_llm.XAIJudge().max_tokens == llm.JUDGE_MAX_TOKENS


def test_openai_content_parts_are_joined_and_reasoning_fields_are_ignored(monkeypatch):
    import arena.api_llm as api_llm

    def fake_urlopen(request, *, timeout):
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "reasoning_content": "do not return this",
                            "content": [
                                {"type": "text", "text": "part 1"},
                                {"type": "text", "text": " part 2"},
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=_fake_key("xai-", "test-", "key"))

    assert worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py") == "part 1 part 2"


def test_build_api_models_maps_defaults_overrides_and_rejects_unknown_provider():
    import arena.api_llm as api_llm

    worker, judge = api_llm.build_api_models("xai", api_key=_fake_key("xai-", "key"))
    assert isinstance(worker, api_llm.XAIWorker)
    assert isinstance(judge, api_llm.XAIJudge)
    assert worker.model == "grok-4.3"
    assert judge.model == "grok-4.3"

    worker, judge = api_llm.build_api_models(
        "gemini",
        api_key=_fake_key("gemini-", "key"),
    )
    assert isinstance(worker, api_llm.OpenAICompatibleWorker)
    assert isinstance(judge, api_llm.OpenAICompatibleJudge)
    assert worker.provider == "gemini"
    assert worker.model == "gemini-2.5-flash-lite"
    assert worker.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    worker, judge = api_llm.build_api_models(
        "openrouter",
        worker_model="custom-worker",
        judge_model="custom-judge",
        api_key=_fake_key("openrouter-", "key"),
        timeout_seconds=7,
    )
    assert worker.provider == "openrouter"
    assert worker.model == "custom-worker"
    assert judge.model == "custom-judge"
    assert worker.timeout_seconds == 7
    assert judge.timeout_seconds == 7

    with pytest.raises(ValueError):
        api_llm.build_api_models("nope", api_key="key")


def test_missing_key_error_names_provider_without_prompt_or_secret_leakage(monkeypatch):
    import arena.api_llm as api_llm

    monkeypatch.delenv("XAI_API_KEY", raising=False)

    with pytest.raises(api_llm.ApiModelError) as exc:
        api_llm.XAIWorker().regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "xai" in msg
    assert "XAI_API_KEY" in msg
    assert "SECRET_SOURCE" not in msg
    assert "SECRET_REASON" not in msg


def test_http_error_redacts_prompt_and_api_key(monkeypatch):
    import arena.api_llm as api_llm

    xai_key = _fake_key("xai-", "secret-", "key")

    def fake_urlopen(request, *, timeout):
        body = f"upstream echoed SECRET_SOURCE SECRET_REASON {xai_key}".encode()
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(body),
        )

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=xai_key)
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "xai" in msg
    assert "HTTP 429" in msg
    assert "SECRET_SOURCE" not in msg
    assert "SECRET_REASON" not in msg
    assert xai_key not in msg
    assert "upstream echoed" not in msg


def test_url_error_redacts_prompt_and_key(monkeypatch):
    import arena.api_llm as api_llm

    xai_key = _fake_key("xai-", "secret-", "key")

    def fake_urlopen(request, *, timeout):
        raise urllib.error.URLError(f"timeout SECRET_SOURCE SECRET_REASON {xai_key}")

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=xai_key)
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "request failed" in msg
    assert "SECRET_SOURCE" not in msg
    assert "SECRET_REASON" not in msg
    assert xai_key not in msg


def test_malformed_response_raises_typed_error_without_prompt_leakage(monkeypatch):
    import arena.api_llm as api_llm

    def fake_urlopen(request, *, timeout):
        return _Response({"choices": [{"message": {"reasoning_content": "not visible"}}]})

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=_fake_key("xai-", "test-", "key"))
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    msg = str(exc.value)
    assert "response did not contain visible message content" in msg
    assert "SECRET_SOURCE" not in msg
    assert "SECRET_REASON" not in msg


def test_empty_visible_content_raises_typed_error(monkeypatch):
    import arena.api_llm as api_llm

    def fake_urlopen(request, *, timeout):
        return _Response({"choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=_fake_key("xai-", "test-", "key"))
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    assert "response did not contain visible message content" in str(exc.value)


def test_finish_reason_length_raises_before_using_truncated_content(monkeypatch):
    import arena.api_llm as api_llm

    def fake_urlopen(request, *, timeout):
        return _Response(
            {"choices": [{"finish_reason": "length", "message": {"content": VALID_DIFF}}]}
        )

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=_fake_key("xai-", "test-", "key"))
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    assert "response truncated at max_tokens" in str(exc.value)


def test_non_dict_message_raises_typed_malformed_response(monkeypatch):
    import arena.api_llm as api_llm

    def fake_urlopen(request, *, timeout):
        return _Response({"choices": [{"message": "not-a-dict"}]})

    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker = api_llm.XAIWorker(api_key=_fake_key("xai-", "test-", "key"))
    with pytest.raises(api_llm.ApiModelError) as exc:
        worker.regenerate_patch("SECRET_SOURCE", "SECRET_REASON", "tokenizer.py")

    assert "malformed chat-completions response" in str(exc.value)


def test_gemini_accepts_google_api_key_fallback(monkeypatch):
    import arena.api_llm as api_llm

    captured = {}
    google_key = _fake_key("google-", "fallback-", "key")

    def fake_urlopen(request, *, timeout):
        captured["authorization"] = dict(request.header_items())["Authorization"]
        return _Response(_chat_response(VALID_DIFF))

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", google_key)
    monkeypatch.setattr(api_llm.urllib.request, "urlopen", fake_urlopen)

    worker, _judge = api_llm.build_api_models("gemini")
    assert worker.regenerate_patch("SOURCE", "REASON", "tokenizer.py") == VALID_DIFF
    assert captured["authorization"] == f"Bearer {google_key}"
