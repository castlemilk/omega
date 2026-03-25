"""
Twitter feed monitor via SN13/Gravity API.

Polls a curated list of accounts for interesting tweets and logs them to
docs/ideas/feed.jsonl for the Omega research pipeline.

Usage:
    python -m omega.integrations.twitter_feed
    python -m omega.integrations.twitter_feed --dry-run

Environment variables (set in .env):
    SN13_API_KEY      - Macrocosmos/Gravity API key (optional, falls back to HTTP)
    SN13_ENDPOINT     - Override the Gravity HTTP endpoint (optional)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MONITORED_ACCOUNTS: list[str] = [
    "browomo",
    "zostaff",
    "adiix_official",
    "hanakoxbt",
    "0xricker",
    "data_sn13",
]

FILTER_KEYWORDS: list[str] = [
    "trading",
    "strategy",
    "alpha",
    "profit",
    "pnl",
    "p&l",
    "polymarket",
    "weather",
    "signal",
    "bot",
    "edge",
    "backtest",
    "regime",
    "volatility",
    "vrp",
]

HIGH_PRIORITY_KEYWORDS: list[str] = [
    "alpha",
    "edge",
    "polymarket",
    "strategy",
    "signal",
]

LOOKBACK_HOURS: int = 24  # daily poll window

# Default Gravity/SN13 HTTP endpoint
DEFAULT_SN13_ENDPOINT = "https://sn13.api.macrocosmos.ai/v1/query"

# Output log
FEED_LOG_PATH = Path(__file__).parents[2] / "docs" / "ideas" / "feed.jsonl"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class Tweet:
    author: str
    text: str
    links: list[str]
    timestamp: datetime
    tweet_id: str | None = None
    is_high_priority: bool = False
    matched_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SN13 / Gravity client
# ---------------------------------------------------------------------------


def _fetch_via_macrocosmos_sdk(
    accounts: list[str],
    since: datetime,
) -> list[Tweet]:
    """Try macrocosmos-py SDK first."""
    try:
        import macrocosmos

        client = macrocosmos.Client()
        results: list[Tweet] = []
        for account in accounts:
            try:
                response = client.sn13.query(
                    query=f"from:{account}",
                    since=since.isoformat(),
                    limit=50,
                )
                for item in response.get("data", []):
                    tweet = _parse_macrocosmos_item(item, account)
                    if tweet:
                        results.append(tweet)
            except Exception as exc:
                logger.warning("macrocosmos query failed for %s: %s", account, exc)
        return results
    except ImportError:
        logger.debug("macrocosmos-py not installed, falling back to HTTP")
        return []


def _fetch_via_http(
    accounts: list[str],
    since: datetime,
    endpoint: str,
    api_key: str | None,
) -> list[Tweet]:
    """Direct HTTP call to SN13 Gravity endpoint."""
    import urllib.error
    import urllib.request

    results: list[Tweet] = []
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for account in accounts:
        payload = json.dumps(
            {
                "query": f"from:{account}",
                "since": since.isoformat(),
                "limit": 50,
                "source": "twitter",
            }
        ).encode()

        req = urllib.request.Request(endpoint, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                for item in data.get("data", []):
                    tweet = _parse_http_item(item, account)
                    if tweet:
                        results.append(tweet)
        except urllib.error.HTTPError as exc:
            logger.warning("HTTP %s for account %s: %s", exc.code, account, exc.reason)
        except Exception as exc:
            logger.warning("Request failed for %s: %s", account, exc)

    return results


def _parse_macrocosmos_item(item: dict, account: str) -> Tweet | None:
    text = item.get("text", "")
    if not text:
        return None
    ts_raw = item.get("created_at") or item.get("timestamp")
    ts = _parse_timestamp(ts_raw)
    links = _extract_links(item)
    return Tweet(
        author=account,
        text=text,
        links=links,
        timestamp=ts,
        tweet_id=str(item.get("id", "")),
    )


def _parse_http_item(item: dict, account: str) -> Tweet | None:
    text = item.get("text", "") or item.get("content", "")
    if not text:
        return None
    ts_raw = item.get("created_at") or item.get("timestamp") or item.get("date")
    ts = _parse_timestamp(ts_raw)
    links = _extract_links(item)
    return Tweet(
        author=account,
        text=text,
        links=links,
        timestamp=ts,
        tweet_id=str(item.get("id", "")),
    )


def _parse_timestamp(raw: object) -> datetime:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return datetime.now(tz=UTC)


def _extract_links(item: dict) -> list[str]:
    links: list[str] = []
    # Explicit urls field
    for url_obj in item.get("urls", []):
        if isinstance(url_obj, dict):
            links.append(url_obj.get("expanded_url") or url_obj.get("url", ""))
        elif isinstance(url_obj, str):
            links.append(url_obj)
    # Fallback: scan text for http
    text = item.get("text", "")
    for word in text.split():
        if word.startswith("http") and word not in links:
            links.append(word)
    return [url for url in links if url]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _is_interesting(tweet: Tweet) -> bool:
    """Return True if tweet matches at least one keyword or contains a link."""
    lower = tweet.text.lower()
    matched = [kw for kw in FILTER_KEYWORDS if kw in lower]
    tweet.matched_keywords = matched
    tweet.is_high_priority = any(kw in lower for kw in HIGH_PRIORITY_KEYWORDS)
    return bool(matched) or bool(tweet.links)


def filter_tweets(tweets: list[Tweet]) -> list[Tweet]:
    return [t for t in tweets if _is_interesting(t)]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log_tweets(tweets: list[Tweet], dry_run: bool = False) -> None:
    FEED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for tweet in tweets:
        entry = {
            "timestamp": tweet.timestamp.isoformat(),
            "type": "tweet",
            "author": tweet.author,
            "text": tweet.text[:500],
            "links": tweet.links,
            "tweet_id": tweet.tweet_id,
            "matched_keywords": tweet.matched_keywords,
            "high_priority": tweet.is_high_priority,
        }
        entries.append(entry)
        if tweet.is_high_priority:
            print(f"[PRIORITY] @{tweet.author}: {tweet.text[:120]}")

    if dry_run:
        print(f"[dry-run] Would append {len(entries)} entries to {FEED_LOG_PATH}")
        for e in entries:
            print(json.dumps(e))
        return

    with FEED_LOG_PATH.open("a") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")

    logger.info("Logged %d tweets to %s", len(entries), FEED_LOG_PATH)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def fetch_tweets(
    accounts: list[str] | None = None,
    lookback_hours: int = LOOKBACK_HOURS,
) -> list[Tweet]:
    """Fetch and filter tweets from monitored accounts."""
    accounts = accounts or MONITORED_ACCOUNTS
    since = datetime.now(tz=UTC) - timedelta(hours=lookback_hours)

    api_key = os.environ.get("SN13_API_KEY")
    endpoint = os.environ.get("SN13_ENDPOINT", DEFAULT_SN13_ENDPOINT)

    # Try SDK first
    raw = _fetch_via_macrocosmos_sdk(accounts, since)
    if not raw:
        raw = _fetch_via_http(accounts, since, endpoint, api_key)

    interesting = filter_tweets(raw)
    logger.info(
        "Fetched %d tweets, %d matched filters (lookback=%dh)",
        len(raw),
        len(interesting),
        lookback_hours,
    )
    return interesting


def main(dry_run: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    tweets = fetch_tweets()
    log_tweets(tweets, dry_run=dry_run)
    high_pri = [t for t in tweets if t.is_high_priority]
    print(f"Done. {len(tweets)} interesting tweets logged ({len(high_pri)} high-priority).")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
