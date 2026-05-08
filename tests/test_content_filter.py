"""Tests for the Outlook content safety filter — no real API calls."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipeline.fetcher.base import FetchedItem
from pipeline.fetcher.content_filter import filter_emails


# ── Helpers ────────────────────────────────────────────────────────────────

def _item(title: str, author: str = "newsletters@statnews.com", summary: str = "") -> FetchedItem:
    return FetchedItem(
        title=title,
        url="",
        source_name="Test Source",
        section="biotech_news",
        published=datetime.now(timezone.utc),
        summary=summary or f"Body preview of: {title}",
        author=author,
    )


def _mock_response(verdicts: list[dict]) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(verdicts))]
    return msg


def _verdicts(items: list[FetchedItem], safe_flags: list[bool], reasons: list[str] | None = None) -> list[dict]:
    reasons = reasons or (["newsletter" if s else "test reason" for s in safe_flags])
    return [{"id": i, "safe": s, "reason": r} for i, (s, r) in enumerate(zip(safe_flags, reasons))]


# ── Tests ──────────────────────────────────────────────────────────────────

def test_all_safe_items_passed_through():
    items = [_item("STAT News: FDA approves GLP-1"), _item("BioPharma Dive: Novo raises $2B")]
    mock_resp = _mock_response(_verdicts(items, [True, True]))

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "STAT News")

    assert len(result) == 2


def test_unsafe_item_is_skipped():
    items = [
        _item("STAT News: FDA approves drug"),
        _item("Re: Quick question about the deal", author="john.smith@gmail.com"),
    ]
    mock_resp = _mock_response(_verdicts(items, [True, False], ["newsletter", "personal reply thread"]))

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "Test Source")

    assert len(result) == 1
    assert result[0].title == "STAT News: FDA approves drug"


def test_all_unsafe_returns_empty():
    items = [_item("Hi Racquel — FYI on the portfolio co", author="partner@venrock.com")]
    mock_resp = _mock_response(_verdicts(items, [False], ["personal salutation + internal sender"]))

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "Test Source")

    assert result == []


def test_empty_input_returns_empty_without_api_call():
    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        result = filter_emails([], "test-key", "Test Source")

    MockClient.assert_not_called()
    assert result == []


def test_api_error_skips_all_items_conservatively():
    items = [_item("STAT News: Drug trial results"), _item("FierceBiotech: M&A roundup")]

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = Exception("API timeout")
        result = filter_emails(items, "test-key", "STAT News")

    # Conservative: errors cause all items to be dropped
    assert result == []


def test_invalid_json_from_filter_skips_all_items():
    items = [_item("Some newsletter headline")]
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="not valid json")]

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "Test Source")

    assert result == []


def test_missing_verdict_for_item_is_skipped():
    items = [_item("Story A"), _item("Story B"), _item("Story C")]
    # Claude only returns verdicts for ids 0 and 2 — id 1 is missing
    partial_verdicts = [
        {"id": 0, "safe": True, "reason": "newsletter"},
        {"id": 2, "safe": True, "reason": "newsletter"},
    ]
    mock_resp = _mock_response(partial_verdicts)

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "Test Source")

    # Item 1 (no verdict) should be conservatively skipped
    assert len(result) == 2
    titles = {r.title for r in result}
    assert "Story B" not in titles


def test_confidential_content_flagged():
    items = [
        _item(
            "Fwd: Term sheet — Series B for PortfolioCo",
            author="colleague@venrock.com",
            summary="Hi — forwarding this term sheet. Pre-money val is $40M. LP update attached.",
        )
    ]
    mock_resp = _mock_response(
        _verdicts(items, [False], ["forwarded chain with deal terms and fund economics"])
    )

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = filter_emails(items, "test-key", "Internal")

    assert result == []


def test_correct_fields_sent_to_api():
    """Verify the payload sent to Claude contains sender, subject, and preview."""
    items = [_item("Weekly Digest", author="news@endpoints.news", summary="Top biotech stories this week.")]
    mock_resp = _mock_response(_verdicts(items, [True]))

    captured_prompt: list[str] = []

    def capture_create(**kwargs):
        captured_prompt.append(kwargs["messages"][0]["content"])
        return mock_resp

    with patch("pipeline.fetcher.content_filter.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.side_effect = capture_create
        filter_emails(items, "test-key", "Endpoints News")

    payload_text = captured_prompt[0]
    assert "news@endpoints.news" in payload_text
    assert "Weekly Digest" in payload_text
    assert "Top biotech stories" in payload_text
