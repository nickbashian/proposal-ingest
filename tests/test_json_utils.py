"""Tests for shared Bedrock JSON-response parsing helpers."""

from __future__ import annotations

import pytest

from proposal_ingest.json_utils import parse_json_object_response


def test_parses_plain_json_object() -> None:
    assert parse_json_object_response('{"a": 1}') == {"a": 1}


def test_parses_json_wrapped_in_markdown_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert parse_json_object_response(raw) == {"a": 1}


def test_parses_json_with_trailing_commentary() -> None:
    raw = 'Here is the JSON:\n{"a": 1}\nThanks.'
    assert parse_json_object_response(raw) == {"a": 1}


def test_skips_stray_brace_in_leading_commentary_before_real_json() -> None:
    # A stray "{" in prose (not valid JSON on its own) must not stop the
    # parser from finding the real JSON object that follows.
    raw = 'Note: see the {previous} section.\n{"a": 1}'
    assert parse_json_object_response(raw) == {"a": 1}


def test_raises_when_no_json_object_present() -> None:
    with pytest.raises(ValueError):
        parse_json_object_response("no json here at all")
