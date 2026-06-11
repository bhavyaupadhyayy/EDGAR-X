"""Async Reddit client for retail-sentiment ingestion.

Wraps ``asyncpraw`` (the async port of PRAW) to pull posts from the tracked
finance subreddits and extract ticker mentions. The asyncpraw instance is
injectable so unit tests never touch the network.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.config import get_settings
from core.logging import get_logger
from ingestion.sources.http_utils import ConfigurationError

if TYPE_CHECKING:  # pragma: no cover - import is heavy; only needed for typing
    import asyncpraw

logger = get_logger(__name__)

#: $-prefixed cashtags ($TSLA) or bare 2-5 letter uppercase tokens.
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})\b")
_BARE_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")

#: Common all-caps tokens that are not tickers. Cashtags bypass this list.
_TICKER_BLOCKLIST: frozenset[str] = frozenset(
    {
        "AI", "ALL", "ARE", "ATH", "ATM", "BUY", "CALL", "CEO", "CFO", "CPI",
        "DD", "EOD", "EPS", "ETF", "EV", "FAQ", "FD", "FED", "FOMO", "FOR",
        "FYI", "GDP", "HODL", "HOLD", "IMO", "IPO", "IRA", "ITM", "LLC",
        "LOL", "MOON", "NOT", "NOW", "NYSE", "OTM", "PE", "PUT", "SEC",
        "SELL", "THE", "TLDR", "USA", "USD", "WSB", "YOLO", "YTD",
    }
)

ListingKind = Literal["hot", "new", "top"]


class RedditPost(BaseModel):
    """A normalised Reddit post with extracted ticker mentions."""

    model_config = ConfigDict(frozen=True)

    post_id: str
    subreddit: str
    title: str
    body: str = ""
    score: int = 0
    num_comments: int = 0
    created_at: datetime
    url: str
    tickers: tuple[str, ...] = Field(default_factory=tuple)

    def to_kafka_payload(self) -> dict[str, Any]:
        """Render this post as a dict conforming to ``sentiment.avsc``."""
        return {
            "post_id": self.post_id,
            "subreddit": self.subreddit,
            "title": self.title,
            "body": self.body,
            "score": self.score,
            "num_comments": self.num_comments,
            "tickers": list(self.tickers),
            "created_at": self.created_at,
            "ingested_at": datetime.now(UTC),
        }


class RedditClient:
    """Async client for the tracked finance subreddits.

    Usage::

        async with RedditClient() as client:
            posts = await client.fetch_all_subreddits(limit=50)
    """

    SUBREDDITS: ClassVar[tuple[str, ...]] = ("wallstreetbets", "investing", "stocks")

    def __init__(self, reddit: asyncpraw.Reddit | None = None) -> None:
        """Initialise the client.

        Args:
            reddit: Optional pre-built ``asyncpraw.Reddit`` instance (owned by
                the caller when provided). When omitted, one is built lazily
                from ``REDDIT_CLIENT_ID`` / ``REDDIT_CLIENT_SECRET``.
        """
        self._reddit = reddit
        self._owns_reddit = reddit is None

    async def __aenter__(self) -> RedditClient:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the asyncpraw session if this instance owns it."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the asyncpraw session if this instance owns it."""
        if self._owns_reddit and self._reddit is not None:
            await self._reddit.close()

    async def _get_reddit(self) -> asyncpraw.Reddit:
        """Return the asyncpraw instance, building it on first use.

        Raises:
            ConfigurationError: If Reddit API credentials are not configured.
        """
        if self._reddit is None:
            settings = get_settings()
            if not settings.reddit_client_id or not settings.reddit_client_secret:
                raise ConfigurationError(
                    "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not configured"
                )
            import asyncpraw  # noqa: PLC0415 - deferred: heavy optional import

            self._reddit = asyncpraw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
            )
        return self._reddit

    async def fetch_posts(
        self,
        subreddit_name: str,
        *,
        listing: ListingKind = "hot",
        limit: int = 100,
    ) -> list[RedditPost]:
        """Fetch posts from one subreddit.

        Args:
            subreddit_name: Subreddit name without the ``r/`` prefix.
            listing: Which listing to read (``hot``, ``new``, or ``top``).
            limit: Maximum number of posts to fetch.

        Returns:
            Normalised posts with extracted ticker mentions.
        """
        reddit = await self._get_reddit()
        subreddit = await reddit.subreddit(subreddit_name)
        listing_method = getattr(subreddit, listing)
        posts: list[RedditPost] = []
        async for submission in listing_method(limit=limit):
            posts.append(self._to_post(submission, subreddit_name))
        logger.info(
            "reddit_posts_fetched", subreddit=subreddit_name, listing=listing, count=len(posts)
        )
        return posts

    async def fetch_all_subreddits(
        self, *, listing: ListingKind = "hot", limit: int = 100
    ) -> list[RedditPost]:
        """Fetch posts from every tracked subreddit.

        Args:
            listing: Which listing to read.
            limit: Maximum posts per subreddit.

        Returns:
            Combined posts across all tracked subreddits.
        """
        posts: list[RedditPost] = []
        for name in self.SUBREDDITS:
            posts.extend(await self.fetch_posts(name, listing=listing, limit=limit))
        return posts

    @classmethod
    def _to_post(cls, submission: Any, subreddit_name: str) -> RedditPost:
        """Convert an asyncpraw submission to a :class:`RedditPost`."""
        title = submission.title or ""
        body = getattr(submission, "selftext", "") or ""
        return RedditPost(
            post_id=submission.id,
            subreddit=subreddit_name,
            title=title,
            body=body,
            score=int(getattr(submission, "score", 0) or 0),
            num_comments=int(getattr(submission, "num_comments", 0) or 0),
            created_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
            url=getattr(submission, "url", "") or "",
            tickers=tuple(cls.extract_tickers(f"{title}\n{body}")),
        )

    @staticmethod
    def extract_tickers(text: str) -> list[str]:
        """Extract probable ticker symbols from free text.

        ``$``-prefixed cashtags are always accepted. Bare all-caps tokens of
        2-5 letters are accepted unless they appear in the blocklist of
        common non-ticker acronyms.

        Args:
            text: Free text to scan (title + body).

        Returns:
            Unique tickers in order of first appearance.
        """
        seen: dict[str, None] = {}
        for match in _CASHTAG_RE.finditer(text):
            seen.setdefault(match.group(1), None)
        for match in _BARE_TICKER_RE.finditer(text):
            token = match.group(1)
            if token not in _TICKER_BLOCKLIST:
                seen.setdefault(token, None)
        return list(seen)
