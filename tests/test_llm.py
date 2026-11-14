import pytest

from app.services import llm


def fake(results):
    """모델 이름 → 돌려줄 값(또는 던질 오류)"""
    calls = []

    def _chat_json(model, system, user, max_tokens, reasoning=True):
        calls.append(model)
        result = results[model]
        if isinstance(result, Exception):
            raise result
        return result

    return calls, _chat_json


def test_backup_model_is_used_when_rate_limited(monkeypatch):
    calls, f = fake({"big": llm.LLMError("rate_limit"), "spare": {"ok": 1}})
    monkeypatch.setattr(llm, "_chat_json", f)
    assert llm.chat_json("big", "s", "u", backup="spare") == {"ok": 1}
    assert calls == ["big", "spare"]


def test_backup_is_not_used_for_other_failures(monkeypatch):
    calls, f = fake({"big": llm.LLMError("APITimeoutError"), "spare": {"ok": 1}})
    monkeypatch.setattr(llm, "_chat_json", f)
    with pytest.raises(llm.LLMError):
        llm.chat_json("big", "s", "u", backup="spare")
    assert calls == ["big"]


def test_no_backup_means_error(monkeypatch):
    calls, f = fake({"big": llm.LLMError("rate_limit")})
    monkeypatch.setattr(llm, "_chat_json", f)
    with pytest.raises(llm.LLMError):
        llm.chat_json("big", "s", "u")
    with pytest.raises(llm.LLMError):
        llm.chat_json("big", "s", "u", backup="")
    assert calls == ["big", "big"]


def test_error_when_backup_is_also_limited(monkeypatch):
    calls, f = fake({"big": llm.LLMError("rate_limit"), "spare": llm.LLMError("rate_limit")})
    monkeypatch.setattr(llm, "_chat_json", f)
    with pytest.raises(llm.LLMError):
        llm.chat_json("big", "s", "u", backup="spare")
    assert calls == ["big", "spare"]


def test_no_key_is_an_llm_error(monkeypatch):
    monkeypatch.setattr(llm.config, "GROQ_API_KEY", "")
    with pytest.raises(llm.LLMError):
        llm.chat_json("big", "s", "u")
