"""Unit tests for Autonomous Web Search & Resilient Deep Crawling Engine (Phase 3)."""

import pytest
from unittest.mock import AsyncMock, patch

from src.crawler.deep_crawler import CrawlResult, DeepCrawler
from src.crawler.link_prioritizer import LinkPrioritizer
from src.crawler.resilience import DeadLinkHandler, ResilientFetcher
from src.models.schema import CategoryEnum
from src.search.query_generator import QueryGenerator
from src.search.search_client import SearchResult, UnifiedSearchClient


class TestQueryGenerator:
    def test_sponsor_discovery_queries(self):
        """Test sponsor query generation targeting marketing heads and CSR."""
        queries = QueryGenerator.generate_discovery_queries(
            target_name="Zomato",
            category=CategoryEnum.SPONSOR,
            city="Gurugram",
        )
        assert len(queries) >= 3
        assert any("official website" in q for q in queries)
        assert any("VP Marketing" in q or "leadership" in q for q in queries)

    def test_delegation_discovery_queries(self):
        """Test college delegation queries targeting presidents and student councils."""
        queries = QueryGenerator.generate_discovery_queries(
            target_name="Robotics Society IIT Delhi",
            category=CategoryEnum.COLLEGE_DELEGATION,
            city="Delhi",
        )
        assert len(queries) >= 3
        assert any("President" in q or "Convenor" in q for q in queries)
        assert any("instagram.com" in q for q in queries)

    def test_dead_link_recovery_query(self):
        """Test generating an alternate pivot query when a page is dead."""
        pivot = QueryGenerator.generate_dead_link_fallback_query(
            failed_url="https://acme.com/team-404",
            org_name="Acme Corp",
            category=CategoryEnum.SPONSOR,
        )
        assert "Acme Corp" in pivot
        assert "linkedin" in pivot or "marketing" in pivot


class TestUnifiedSearchClient:
    @pytest.mark.asyncio
    async def test_fallback_search_returns_candidates(self):
        """Test search returns structured SearchResult instances even offline."""
        client = UnifiedSearchClient()
        results = await client.search('Find "Fintech Corp" marketing lead', max_results=3)

        assert len(results) <= 3
        for res in results:
            assert isinstance(res, SearchResult)
            assert res.url.startswith("http")
            assert len(res.title) > 0


class TestLinkPrioritizer:
    def test_url_normalization(self):
        """Test URL normalization resolves relative paths and drops query parameters."""
        base = "https://example.com/home"
        normalized = LinkPrioritizer.normalize_url("/about-us?utm_source=test#contact", base)
        assert normalized == "https://example.com/about-us"

    def test_blacklist_filtering(self):
        """Blacklisted paths (privacy, terms, login, assets) must return None."""
        base = "https://example.com"
        assert LinkPrioritizer.normalize_url("/privacy-policy", base) is None
        assert LinkPrioritizer.normalize_url("/login", base) is None
        assert LinkPrioritizer.normalize_url("/wp-admin/post.php", base) is None
        assert LinkPrioritizer.normalize_url("/brochure.pdf", base) is None

    def test_scoring_hierarchy(self):
        """Team/leadership paths must score significantly higher than standard pages."""
        team_score = LinkPrioritizer.score_url("https://example.com/leadership-team")
        contact_score = LinkPrioritizer.score_url("https://example.com/contact")
        privacy_score = LinkPrioritizer.score_url("https://example.com/privacy-policy")

        assert team_score >= 10
        assert contact_score >= 5
        assert privacy_score <= -50

    def test_prioritize_links_sorting(self):
        """Prioritizer must return high-intent leadership links first."""
        base = "https://example.com"
        links = [
            "/products",
            "/team",
            "/careers",
            "/executive-board",
            "/contact",
        ]
        ranked = LinkPrioritizer.prioritize_links(links, base, max_links=3)
        assert len(ranked) <= 3
        assert any("/team" in r or "/executive-board" in r for r in ranked)


class TestResilienceAndDeadLinks:
    def test_dead_status_codes_detection(self):
        """Detects 404, 403, 500 as dead pages."""
        assert DeadLinkHandler.is_dead_response(404) is True
        assert DeadLinkHandler.is_dead_response(500) is True
        assert DeadLinkHandler.is_dead_response(403) is True
        assert DeadLinkHandler.is_dead_response(200) is False

    def test_handle_dead_url_generates_pivot(self):
        """Dead link handler records failure and yields pivot query."""
        recovery = DeadLinkHandler.handle_dead_url(
            url="https://acme.org/broken",
            status_code=404,
            reason="Not Found",
            org_name="Acme Org",
            category=CategoryEnum.COLLEGE_DELEGATION,
        )
        assert recovery["dead_url"] == "https://acme.org/broken"
        assert recovery["status_code"] == "404"
        assert "recovery_query" in recovery


class TestDeepCrawler:
    @pytest.mark.asyncio
    async def test_crawler_handles_dead_page_gracefully(self):
        """Crawler encountering a dead link records it in dead_urls without throwing."""
        crawler = DeepCrawler()

        # Mock fetcher to simulate 404
        with patch.object(
            crawler.fetcher,
            "fetch",
            new=AsyncMock(return_value=(None, 404, "HTTP Error 404")),
        ):
            result = await crawler.crawl_organization(
                org_name="Ghost Company",
                base_url="https://ghostcompany.com/dead",
                category=CategoryEnum.SPONSOR,
                page_limit=2,
            )

            assert isinstance(result, CrawlResult)
            assert len(result.dead_urls_encountered) == 1
            assert "https://ghostcompany.com/dead" in result.dead_urls_encountered
            assert result.pages[0].is_dead is True

    @pytest.mark.asyncio
    async def test_crawler_extracts_content_and_links(self):
        """Crawler extracts clean HTML, emails, and leadership sub-links."""
        crawler = DeepCrawler()

        mock_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Acme Innovate | Leadership</title></head>
        <body>
            <h1>Welcome to Acme Innovate</h1>
            <p>Our core executive team drives innovation in developer platforms.</p>
            <p>Contact our marketing director: <a href="mailto:sarah.connor@acmeinnovate.com">sarah.connor@acmeinnovate.com</a></p>
            <a href="/team">Meet The Executive Team</a>
            <a href="https://linkedin.com/in/sarah-connor">LinkedIn Profile</a>
        </body>
        </html>
        """

        with patch.object(
            crawler.fetcher,
            "fetch",
            new=AsyncMock(return_value=(mock_html, 200, None)),
        ):
            result = await crawler.crawl_organization(
                org_name="Acme Innovate",
                base_url="https://acmeinnovate.com",
                category=CategoryEnum.SPONSOR,
                page_limit=1,
            )

            assert isinstance(result, CrawlResult)
            assert len(result.pages) == 1
            page = result.pages[0]
            assert page.is_dead is False
            assert "sarah.connor@acmeinnovate.com" in page.discovered_emails
            assert any("linkedin.com/in/sarah-connor" in s for s in page.discovered_social_links)
            assert "Acme Innovate" in (page.title or "")

