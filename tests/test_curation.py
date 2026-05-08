"""Tests for curation scoring logic — no API calls, all Claude responses mocked."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from pipeline.config import BriefingConfig
from pipeline.curator import curate, _thought_leaders_str, CuratedItem
from pipeline.fetcher.base import FetchedItem


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def config() -> BriefingConfig:
    return BriefingConfig.from_yaml("configs/racquel.yaml")


def _make_item(title: str, source: str = "Test Source", section: str = "biotech_news") -> FetchedItem:
    return FetchedItem(
        title=title,
        url=f"https://example.com/{title.lower().replace(' ', '-')}",
        source_name=source,
        section=section,
        published=datetime.now(timezone.utc),
        summary=f"Summary of {title}",
        author="Test Author",
    )


def _mock_response(items: list[FetchedItem], scores: list[float]) -> MagicMock:
    """Build a mock Anthropic response with given relevance scores."""
    scored = [
        {
            "id": i,
            "title": item.title,
            "source": item.source_name,
            "section": item.section,
            "relevance_score": score,
            "theme": "test theme",
            "summary": f"Scored summary for {item.title}",
            "thought_leader_match": None,
        }
        for i, (item, score) in enumerate(zip(items, scores))
    ]
    msg = MagicMock()
    msg.content = [MagicMock(text=json.dumps(scored))]
    return msg


# ── Tests ──────────────────────────────────────────────────────────────────

def test_items_below_threshold_are_dropped(config):
    items = [
        _make_item("FDA approves GLP-1 drug"),    # should score high
        _make_item("Local sports clinic opens"),   # should score low / be dropped
    ]
    mock_resp = _mock_response(items, scores=[8.0, 2.0])

    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = curate(items, config, api_key="test-key")

    assert len(result) == 1
    assert result[0].title == "FDA approves GLP-1 drug"


def test_results_sorted_by_score_descending(config):
    items = [_make_item(f"Story {i}") for i in range(4)]
    scores = [7.0, 9.0, 6.0, 8.0]
    mock_resp = _mock_response(items, scores)

    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = curate(items, config, api_key="test-key")

    result_scores = [r.relevance_score for r in result]
    assert result_scores == sorted(result_scores, reverse=True)


def test_all_items_below_threshold_returns_empty(config):
    items = [_make_item("Irrelevant story 1"), _make_item("Irrelevant story 2")]
    mock_resp = _mock_response(items, scores=[1.0, 2.0])

    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = curate(items, config, api_key="test-key")

    assert result == []


def test_empty_input_returns_empty_without_api_call(config):
    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        result = curate([], config, api_key="test-key")
    MockClient.assert_not_called()
    assert result == []


def test_thought_leader_bonus_reflected_in_curated_item(config):
    items = [_make_item("Adam Feuerstein: FDA rejects drug X")]
    scored = [
        {
            "id": 0,
            "title": items[0].title,
            "source": "STAT News",
            "section": "biotech_news",
            "relevance_score": 9.0,
            "theme": "FDA decision",
            "summary": "A summary mentioning Adam Feuerstein.",
            "thought_leader_match": "Adam Feuerstein",
        }
    ]
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps(scored))]

    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        result = curate(items, config, api_key="test-key")

    assert len(result) == 1
    assert result[0].thought_leader_match == "Adam Feuerstein"


def test_thought_leaders_str_includes_handles_and_aliases(config):
    s = _thought_leaders_str(config)
    assert "Adam Feuerstein" in s
    assert "@adamfeuerstein" in s
    assert "Warren Buffett" in s
    assert "Berkshire Hathaway" in s


def test_invalid_json_from_curator_raises(config):
    items = [_make_item("Some story")]
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text="not valid json {{{}")]

    with patch("pipeline.curator.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.create.return_value = mock_resp
        with pytest.raises(json.JSONDecodeError):
            curate(items, config, api_key="test-key")
