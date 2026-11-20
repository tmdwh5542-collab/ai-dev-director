"""Portable work ledgers and explicit POSIX document references."""
import os

import pytest

from core.builder_context import referenced_documents
from core.usage import provider_of
from schemas.order import OrderSchema


@pytest.mark.parametrize("executable,provider", [
    (r"C:\Program Files\Claude\claude.exe", "ANTHROPIC"),
    ("/opt/bin/claude", "ANTHROPIC"),
    (r"D:\tools\CODEX.CMD", "OPENAI"),
    ("/opt/homebrew/bin/agy", "GOOGLE"),
    (r"C:\tools\director-stub-cli.cmd", None),
])
def test_portable_provider_names(executable, provider):
    assert provider_of(executable) == provider


@pytest.mark.skipif(os.name == "nt", reason="POSIX filesystem references")
def test_posix_plain_and_quoted_paths_ignore_urls_and_relative_docs(tmp_path):
    simple = tmp_path / "spec.md"; simple.write_text("SPEC", encoding="utf-8")
    spaced = tmp_path / "요구 사항.txt"; spaced.write_text("기준", encoding="utf-8")
    order = OrderSchema(goal=f'Read {simple} and "{spaced}". Also use https://example.invalid/spec.md and '
                            'http://127.0.0.1:1234/v1/spec.md; update docs/SPEC.md.', allowed_paths=["src/**"])
    assert referenced_documents(order) == {str(simple): "SPEC", str(spaced): "기준"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX filesystem references")
def test_missing_posix_reference_is_an_error_but_urls_are_not(tmp_path):
    assert referenced_documents(OrderSchema(goal="Use https://example.invalid/spec.md and docs/spec.md; "
        "http://[::1]/missing.md https://example.invalid./missing.md "
        "https://example.invalid/?path=/missing.md file:///missing.md", allowed_paths=["src/**"])) == {}
    with pytest.raises(ValueError, match="REFERENCE_INPUT_UNAVAILABLE"):
        referenced_documents(OrderSchema(goal=f"Read {tmp_path / 'missing.md'} please", allowed_paths=["src/**"]))
