"""Unit tests for the Reddit sentiment client (asyncpraw fully stubbed)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest

from ingestion.sources.http_utils import ConfigurationError
from ingestion.sources.reddit_client import RedditClient


@dataclass
class FakeSubmission:
    """Duck-typed asyncpraw submission."""

    id: str
    title: str
    selftext: str = ""
    score: int = 10
    num_comments: int = 3
    created_utc: float = 1_780_000_000.0
    url: str = "https://reddit.com/post"


@dataclass
class FakeSubreddit:
    """Duck-typed asyncpraw subreddit with a hot/new/top listing."""

    submissions: list[FakeSubmission] = field(default_factory=list)

    def hot(self, limit: int | None = None) -> AsyncIterator[FakeSubmission]:
        return self._iterate(limit)

    def new(self, limit: int | None = None) -> AsyncIterator[FakeSubmission]:
        return self._iterate(limit)

    def top(self, limit: int | None = None) -> AsyncIterator[FakeSubmission]:
        return self._iterate(limit)

    async def _iterate(self, limit: int | None) -> AsyncIterator[FakeSubmission]:
        for submission in self.submissions[:limit]:
            yield submission


class FakeReddit:
    """Duck-typed asyncpraw.Reddit returning canned subreddits."""

    def __init__(self, subreddits: dict[str, FakeSubreddit]) -> None:
        self._subreddits = subreddits
        self.closed = False

    async def subreddit(self, name: str) -> FakeSubreddit:
        return self._subreddits[name]

    async def close(self) -> None:
        self.closed = True


class TestExtractTickers:
    """Cashtag and bare-token extraction."""

    def test_extracts_cashtags(self) -> None:
        assert RedditClient.extract_tickers("Loaded up on $TSLA and $NVDA calls") == [
            "TSLA",
            "NVDA",
        ]

    def test_extracts_bare_uppercase_tokens(self) -> None:
        assert "AAPL" in RedditClient.extract_tickers("AAPL earnings tomorrow")

    def test_blocklist_filters_common_acronyms(self) -> None:
        tickers = RedditClient.extract_tickers("YOLO DD on the CEO of GME, IMO")
        assert tickers == ["GME"]

    def test_cashtag_bypasses_blocklist(self) -> None:
        # $DD is the cashtag for DuPont even though bare DD is blocked.
        assert RedditClient.extract_tickers("buying $DD today") == ["DD"]

    def test_deduplicates_preserving_order(self) -> None:
        assert RedditClient.extract_tickers("$GME GME $AMC GME") == ["GME", "AMC"]

    def test_ignores_lowercase_words(self) -> None:
        assert RedditClient.extract_tickers("buy low sell high") == []


class TestFetchPosts:
    """Fetching and normalising posts via the injected fake."""

    @pytest.fixture()
    def fake_reddit(self) -> FakeReddit:
        wsb = FakeSubreddit(
            submissions=[
                FakeSubmission(id="p1", title="$GME to the moon", selftext="YOLO calls"),
                FakeSubmission(id="p2", title="Thoughts on AAPL?", selftext="long term hold"),
            ]
        )
        return FakeReddit(
            {
                "wallstreetbets": wsb,
                "investing": FakeSubreddit(submissions=[FakeSubmission(id="p3", title="Bonds")]),
                "stocks": FakeSubreddit(),
            }
        )

    async def test_fetch_posts_normalises_submissions(self, fake_reddit: FakeReddit) -> None:
        client = RedditClient(reddit=fake_reddit)  # type: ignore[arg-type]
        posts = await client.fetch_posts("wallstreetbets")
        assert len(posts) == 2
        assert posts[0].post_id == "p1"
        assert posts[0].subreddit == "wallstreetbets"
        assert posts[0].tickers == ("GME",)
        assert posts[0].created_at.tzinfo is not None

    async def test_fetch_posts_respects_limit(self, fake_reddit: FakeReddit) -> None:
        client = RedditClient(reddit=fake_reddit)  # type: ignore[arg-type]
        posts = await client.fetch_posts("wallstreetbets", limit=1)
        assert len(posts) == 1

    async def test_fetch_all_subreddits_combines(self, fake_reddit: FakeReddit) -> None:
        client = RedditClient(reddit=fake_reddit)  # type: ignore[arg-type]
        posts = await client.fetch_all_subreddits()
        assert {p.subreddit for p in posts} == {"wallstreetbets", "investing"}
        assert len(posts) == 3

    async def test_kafka_payload_shape(self, fake_reddit: FakeReddit) -> None:
        client = RedditClient(reddit=fake_reddit)  # type: ignore[arg-type]
        posts = await client.fetch_posts("wallstreetbets")
        payload = posts[0].to_kafka_payload()
        assert payload["post_id"] == "p1"
        assert payload["tickers"] == ["GME"]
        assert payload["ingested_at"].tzinfo is not None

    async def test_injected_session_not_closed(self, fake_reddit: FakeReddit) -> None:
        async with RedditClient(reddit=fake_reddit) as client:  # type: ignore[arg-type]
            await client.fetch_posts("stocks")
        assert fake_reddit.closed is False

    async def test_missing_credentials_raises(self) -> None:
        client = RedditClient()
        with pytest.raises(ConfigurationError):
            await client.fetch_posts("stocks")
