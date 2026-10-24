"""Source collection through other Apify Store actors, called from inside this actor.

  news search   apify/google-search-scraper    Google News results for the spec query
  article text  apify/website-content-crawler  bodies of those result URLs (depth 0)
  reddit        trudax/reddit-scraper-lite     posts found by searching the fire name

Public pages only: no cookies or logins are passed, login-walled social sites are dropped, and the
crawler respects robots.txt. Reddit usernames and article bylines are never read into the output.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode, urlparse

log = logging.getLogger(__name__)

GOOGLE_ACTOR = os.environ.get("EMBER_GOOGLE_ACTOR", "apify/google-search-scraper")
CRAWLER_ACTOR = os.environ.get("EMBER_CRAWLER_ACTOR", "apify/website-content-crawler")
# The spec names "apify/reddit-scraper-lite"; that id does not exist in the Apify Store (checked
# 2026-10-23). The Store's Reddit Scraper Lite is trudax/reddit-scraper-lite.
REDDIT_ACTOR = os.environ.get("EMBER_REDDIT_ACTOR", "trudax/reddit-scraper-lite")

# Login-walled or non-article hosts: not public pages, or not crawlable without an account.
BLOCKED_HOSTS = (
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com", "nextdoor.com",
    "tiktok.com", "youtube.com", "google.com", "reddit.com",  # reddit comes from its own actor
)

# (actor_id, run_input) -> dataset items. Injected so tests can run with no network.
CallActor = Callable[[str, dict[str, Any]], Awaitable[list[dict[str, Any]]]]


def build_query(fire_name: str) -> str:
    """Exact spec query: "<fire_name>" survived OR sheltered OR "took refuge"."""
    return f'"{fire_name.strip()}" survived OR sheltered OR "took refuge"'


def google_news_url(query: str) -> str:
    return "https://www.google.com/search?" + urlencode({"q": query, "tbm": "nws", "hl": "en"})


def split_budget(max_pages: int) -> tuple[int, int]:
    """max_pages caps pages sent to extraction: 3/4 news articles, 1/4 Reddit posts (min 1 each)."""
    max_pages = max(2, int(max_pages))
    reddit = max(1, max_pages // 4)
    return max_pages - reddit, reddit


def outlet_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_public_article(url: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    return not any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def google_input(fire_name: str, news_limit: int) -> dict[str, Any]:
    return {
        "queries": google_news_url(build_query(fire_name)),
        # ~10 results per page; one spare page because some results are filtered out.
        "maxPagesPerQuery": min(10, math.ceil(news_limit / 10) + 1),
        "countryCode": "us",
        "languageCode": "en",
        "mobileResults": False,
        "saveHtml": False,
        "saveHtmlToKeyValueStore": False,
        "includeUnfilteredResults": False,
    }


def parse_google_items(items: list[dict[str, Any]], news_limit: int) -> list[dict[str, Any]]:
    """Google SERP pages -> [{url, title, outlet, date}] (deduped, public, capped)."""
    out, seen = [], set()
    for page in items:
        for key in ("newsResults", "organicResults"):
            for r in page.get(key) or []:
                url = r.get("url") or r.get("link")
                if not url or url in seen or not is_public_article(url):
                    continue
                seen.add(url)
                out.append({
                    "url": url,
                    "title": r.get("title"),
                    "outlet": r.get("source") or outlet_of(url),
                    "date": r.get("date") or r.get("publishedAt"),
                })
    return out[:news_limit]


def crawler_input(urls: list[str]) -> dict[str, Any]:
    return {
        "startUrls": [{"url": u} for u in urls],
        "maxCrawlDepth": 0,
        "maxCrawlPages": len(urls),
        "maxResults": len(urls),
        "crawlerType": "playwright:adaptive",
        "respectRobotsTxtFile": True,
        "removeCookieWarnings": True,
        "saveMarkdown": False,
        "useSitemaps": False,
        "proxyConfiguration": {"useApifyProxy": True},
    }


def reddit_input(fire_name: str, reddit_limit: int) -> dict[str, Any]:
    return {
        "searches": [fire_name],
        "searchPosts": True,
        "searchComments": False,
        "searchCommunities": False,
        "searchUsers": False,
        "sort": "relevance",
        "time": "all",
        "includeNSFW": False,
        "skipComments": True,
        "skipUserPosts": True,
        "skipCommunity": True,
        "maxItems": reddit_limit,
        "maxPostCount": reddit_limit,
        "maxComments": 0,
        "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
    }


def parse_reddit_items(items: list[dict[str, Any]], reddit_limit: int) -> list[dict[str, Any]]:
    """Reddit posts -> documents. Only title + body text are kept; never the username."""
    docs = []
    for it in items:
        if it.get("dataType") not in (None, "post"):
            continue
        body = "\n\n".join(x for x in (it.get("title"), it.get("body")) if x)
        url = it.get("url")
        if not body.strip() or not url:
            continue
        community = it.get("communityName") or it.get("parsedCommunityName")
        docs.append({
            "url": url,
            "title": it.get("title"),
            "body": body,
            "outlet": f"reddit.com/{community}" if community else "reddit.com",
            "date": it.get("createdAt"),
            "source": "reddit",
        })
    return docs[:reddit_limit]


async def collect_documents(call_actor: CallActor, fire_name: str, max_pages: int) -> tuple[list[dict], dict]:
    """Run the three source actors. Each failure is logged and recorded; it never stops the run."""
    news_limit, reddit_limit = split_budget(max_pages)
    stats: dict[str, Any] = {"news_results": 0, "articles": 0, "reddit_posts": 0, "errors": []}
    docs: list[dict[str, Any]] = []

    results: list[dict[str, Any]] = []
    try:
        items = await call_actor(GOOGLE_ACTOR, google_input(fire_name, news_limit))
        results = parse_google_items(items, news_limit)
        stats["news_results"] = len(results)
    except Exception as exc:
        log.exception("Google search step failed")
        stats["errors"].append(f"{GOOGLE_ACTOR}: {exc}")

    if results:
        by_url = {r["url"]: r for r in results}
        try:
            pages = await call_actor(CRAWLER_ACTOR, crawler_input(list(by_url)))
            for page in pages:
                url = page.get("url") or (page.get("crawl") or {}).get("loadedUrl")
                text = page.get("text") or page.get("markdown") or ""
                meta = by_url.get(url) or by_url.get((page.get("crawl") or {}).get("loadedUrl") or "") or {}
                if not text.strip() or not url:
                    continue
                docs.append({
                    "url": meta.get("url", url),
                    "title": meta.get("title") or (page.get("metadata") or {}).get("title"),
                    "body": text,
                    "outlet": meta.get("outlet") or outlet_of(url),
                    "date": meta.get("date") or (page.get("metadata") or {}).get("publishedAt"),
                    "source": "news",
                })
            stats["articles"] = len(docs)
        except Exception as exc:
            log.exception("Article crawl step failed")
            stats["errors"].append(f"{CRAWLER_ACTOR}: {exc}")

    try:
        posts = parse_reddit_items(await call_actor(REDDIT_ACTOR, reddit_input(fire_name, reddit_limit)), reddit_limit)
        stats["reddit_posts"] = len(posts)
        docs.extend(posts)
    except Exception as exc:
        log.exception("Reddit step failed")
        stats["errors"].append(f"{REDDIT_ACTOR}: {exc}")

    return docs[:max_pages], stats
