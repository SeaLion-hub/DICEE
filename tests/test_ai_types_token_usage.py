"""app.services.ai.types.TokenUsage·add_token_usage."""

from app.services.ai.types import TokenUsage, add_token_usage


def test_add_token_usage_sums_fields() -> None:
    a = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    b = TokenUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3)
    out = add_token_usage(a, b)
    assert out.prompt_tokens == 11
    assert out.completion_tokens == 22
    assert out.total_tokens == 33


def test_add_token_usage_derives_total_when_zero_but_parts_present() -> None:
    a = TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=0)
    b = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    out = add_token_usage(a, b)
    assert out.total_tokens == 10
