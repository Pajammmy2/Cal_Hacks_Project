import asyncio
from urllib.parse import parse_qs, urlparse

from conftest import FakeApify, load

from src import sources
from src.sources import build_query, collect_documents, google_input, parse_google_items, split_budget


def test_query_is_exact_spec_text():
    assert build_query("Camp Fire") == '"Camp Fire" survived OR sheltered OR "took refuge"'


def test_google_input_web_search_and_pages():
    inp = google_input("Tubbs Fire", 45)
    q = parse_qs(urlparse(inp["queries"]).query)
    assert q["q"] == ['"Tubbs Fire" survived OR sheltered OR "took refuge"'] and "tbm" not in q
    assert inp["maxPagesPerQuery"] == 6


def test_split_budget_respects_max_pages():
    assert split_budget(60) == (45, 15)
    assert sum(split_budget(7)) == 7
    assert split_budget(1) == (1, 1)


def test_parse_google_filters_and_dedupes():
    out = parse_google_items(load("google_serp.json"), 10)
    assert [r["url"] for r in out] == [
        "https://www.example-news.com/2018/11/12/camp-fire-kmart-lot",
        "https://www.chico-daily.example.org/camp-fire-walgreens",
    ]  # facebook dropped (login wall), duplicate dropped
    assert out[0]["outlet"] == "Example News" and out[1]["outlet"] == "chico-daily.example.org"
    assert out[0]["date"] == "Nov 12, 2018"


def test_collect_documents_calls_three_actors():
    fake = FakeApify()
    docs, stats = asyncio.run(collect_documents(fake, "Camp Fire", 60))
    ids = [c[0] for c in fake.calls]
    assert ids == [sources.GOOGLE_ACTOR, sources.CRAWLER_ACTOR, sources.REDDIT_ACTOR]
    assert ids[0] == "apify/google-search-scraper" and ids[1] == "apify/website-content-crawler"
    crawl_input = fake.calls[1][1]
    assert crawl_input["maxCrawlDepth"] == 0 and crawl_input["respectRobotsTxtFile"] is True
    assert len(crawl_input["startUrls"]) == 2
    assert fake.calls[2][1]["searches"] == ["Camp Fire"]
    assert stats == {"news_results": 2, "articles": 2, "reddit_posts": 1, "errors": []}
    reddit = [d for d in docs if d["source"] == "reddit"][0]
    assert "throwaway_user_123" not in str(reddit)  # usernames never kept
    assert reddit["outlet"] == "reddit.com/r/chico"


def test_collect_documents_respects_max_pages():
    docs, _ = asyncio.run(collect_documents(FakeApify(), "Camp Fire", 2))
    assert len(docs) <= 2


def test_failed_source_is_isolated():
    docs, stats = asyncio.run(collect_documents(FakeApify(fail={"google-search-scraper"}), "Camp Fire", 60))
    assert [d["source"] for d in docs] == ["reddit"]
    assert len(stats["errors"]) == 1 and "google-search-scraper" in stats["errors"][0]
