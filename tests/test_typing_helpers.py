"""크롤러 typing_helpers 단위 테스트."""

from app.services.crawlers.typing_helpers import ensure_str_attr, first_element_str


def test_first_element_str_none_and_empty() -> None:
    assert first_element_str(None) == ""
    assert first_element_str(None, default="x") == "x"
    assert first_element_str([]) == ""


def test_first_element_str_plain_str_and_sequence() -> None:
    assert first_element_str("hello") == "hello"
    assert first_element_str(["a", "b"]) == "a"
    assert first_element_str((42,)) == "42"


def test_ensure_str_attr_unchanged_behavior() -> None:
    assert ensure_str_attr(None) == ""
    assert ensure_str_attr("x") == "x"
    assert ensure_str_attr(["y", "z"]) == "y"
