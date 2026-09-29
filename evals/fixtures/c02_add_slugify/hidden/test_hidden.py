import pytest
from textutils import slugify, title_case


@pytest.mark.parametrize("text,expected", [
    ("Hello, World!", "hello-world"),
    ("  Multiple   spaces  ", "multiple-spaces"),
    ("Already-slug", "already-slug"),
    ("C++ & Rust 2026", "c-rust-2026"),
    ("---", ""),
    ("", ""),
])
def test_slugify(text, expected):
    assert slugify(text) == expected


def test_existing_function_kept():
    assert title_case("hello world") == "Hello World"
