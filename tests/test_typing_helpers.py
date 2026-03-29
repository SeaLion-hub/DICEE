"""크롤러 typing_helpers 단위 테스트."""

from app.services.crawlers.typing_helpers import class_list_from_tag, ensure_str_attr, first_element_str
from bs4 import BeautifulSoup


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


def test_class_list_from_tag_none_and_string() -> None:
    soup = BeautifulSoup("<div id='x'>x</div>", "html.parser")
    tag = soup.find("div")
    assert tag is not None
    assert class_list_from_tag(tag) == []

    soup2 = BeautifulSoup('<div class="a b">x</div>', "html.parser")
    div = soup2.find("div")
    assert div is not None
    out = class_list_from_tag(div)
    assert set(out) == {"a", "b"}


def test_class_list_from_tag_single_string_attr() -> None:
    from bs4 import Tag

    t = Tag(name="tr")
    t["class"] = "single-class"
    assert class_list_from_tag(t) == ["single-class"]


def test_class_list_from_tag_tuple_coerced() -> None:
    from bs4 import Tag

    t = Tag(name="td")
    t["class"] = ("x", 1)
    assert class_list_from_tag(t) == ["x", "1"]
