"""Autonomous Deep Web Crawler with Dead-Page Handling and JS Fallbacks.

Traverses corporate domains and collegiate society websites, prioritizes leadership
pages, extracts clean markdown via Trafilatura, detects SPAs, and manages dead-link failovers.
"""

from __future__ import annotations

import re
from typing import Optional
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
import trafilatura

from src.crawler.link_prioritizer import LinkPrioritizer
from src.crawler.resilience import DeadLinkHandler, ResilientFetcher
from src.models.schema import CategoryEnum, ScrapedPageSnapshot


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
SOCIAL_PATTERNS = [
    r"https?://(?:www\.)?linkedin\.com/(?:in|company)/[a-zA-Z0-9_.-]+",
    r"https?://(?:www\.)?instagram\.com/[a-zA-Z0-9_.-]+",
    r"https?://(?:www\.)?facebook\.com/[a-zA-Z0-9_.-]+",
    r"https?://(?:www\.)?twitter\.com/[a-zA-Z0-9_.-]+",
    r"https?://(?:www\.)?x\.com/[a-zA-Z0-9_.-]+",
]


class CrawlResult(BaseModel):
    """Aggregate result of crawling an organization's digital footprint."""
    model_config = ConfigDict(extra="ignore")

    organization_name: str
    pages: list[ScrapedPageSnapshot] = Field(default_factory=list)
    dead_urls_encountered: list[str] = Field(default_factory=list)
    total_pages_crawled: int = 0


class DeepCrawler:
    """Asynchronous multi-page crawler with SPA fallback and dead link failover."""

    def __init__(self, timeout_seconds: float = 12.0, max_depth: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_depth = max_depth
        self.fetcher = ResilientFetcher(timeout_seconds=timeout_seconds)

    async def crawl_organization(
        self,
        org_name: str,
        base_url: str,
        category: CategoryEnum = CategoryEnum.SPONSOR,
        page_limit: int = 4,
    ) -> CrawlResult:
        """Crawls root domain and high-intent leadership subpages autonomously."""
        visited: set[str] = set()
        to_visit: list[str] = [base_url]
        scraped_pages: list[ScrapedPageSnapshot] = []
        dead_urls: list[str] = []

        logger.info(f"Starting autonomous crawl for '{org_name}' at: {base_url}")

        while to_visit and len(visited) < page_limit:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)

            # 1. Fetch raw HTML with resilient retry
            html, status_code, err_msg = await self.fetcher.fetch(current_url)

            # 2. Check for dead/blocked page
            if html is None or DeadLinkHandler.is_dead_response(status_code):
                dead_urls.append(current_url)
                DeadLinkHandler.handle_dead_url(
                    url=current_url,
                    status_code=status_code,
                    reason=err_msg or f"HTTP {status_code}",
                    org_name=org_name,
                    category=category,
                )
                scraped_pages.append(
                    ScrapedPageSnapshot(
                        url=current_url,
                        status_code=status_code,
                        markdown_content="",
                        is_dead=True,
                    )
                )
                continue

            # 3. Extract text content via Trafilatura
            markdown = trafilatura.extract(
                html,
                include_links=True,
                include_comments=False,
                output_format="txt",
            ) or ""

            # 4. Check for SPA / dynamic React/Next.js site needing JS execution
            is_empty_spa = len(markdown.split()) < 40 and any(
                tag in html for tag in ['id="root"', 'id="__next"', 'id="app"', 'class="react-root"']
            )
            if is_empty_spa:
                logger.info(f"Detected client-side SPA on {current_url}. Triggering headless JS crawler...")
                js_markdown = await self._crawl_dynamic_spa(current_url)
                if js_markdown:
                    markdown = js_markdown

            # 5. Extract links, emails, and social profiles from DOM
            sub_links, emails, socials, title = self._extract_dom_entities(html, current_url)

            # 6. Prioritize discovered internal links and enqueue
            prioritized = LinkPrioritizer.prioritize_links(
                discovered_urls=sub_links,
                base_url=base_url,
                max_links=page_limit - len(visited),
            )
            for link in prioritized:
                if link not in visited and link not in to_visit:
                    to_visit.append(link)

            # 7. Record successfully scraped page
            scraped_pages.append(
                ScrapedPageSnapshot(
                    url=current_url,
                    status_code=status_code,
                    title=title,
                    markdown_content=markdown,
                    discovered_internal_links=prioritized,
                    discovered_emails=emails,
                    discovered_social_links=socials,
                    is_dead=False,
                )
            )

        logger.info(
            f"Finished crawl for '{org_name}': {len(scraped_pages)} pages scraped, "
            f"{len(dead_urls)} dead URLs encountered."
        )

        return CrawlResult(
            organization_name=org_name,
            pages=scraped_pages,
            dead_urls_encountered=dead_urls,
            total_pages_crawled=len(scraped_pages),
        )

    def _extract_dom_entities(
        self, html: str, base_url: str
    ) -> tuple[list[str], list[str], list[str], Optional[str]]:
        """Parses raw HTML to harvest anchor links, emails, social URLs, and page title."""
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else None

        # Extract all hrefs
        raw_links: list[str] = []
        for a in soup.find_all("a", href=True):
            raw_links.append(a["href"])

        # Extract emails from text & mailto: tags
        emails: set[str] = set()
        for mailto in soup.select('a[href^="mailto:"]'):
            href = mailto.get("href", "")
            clean_email = href.replace("mailto:", "").split("?")[0].strip()
            if EMAIL_REGEX.match(clean_email):
                emails.add(clean_email)

        text_emails = EMAIL_REGEX.findall(html)
        for e in text_emails:
            # Filter file extensions accidentally captured as email
            if not any(e.endswith(ext) for ext in [".png", ".jpg", ".webp", ".js"]):
                emails.add(e)

        # Extract social profile links
        socials: set[str] = set()
        for link in raw_links:
            for pattern in SOCIAL_PATTERNS:
                if re.match(pattern, link):
                    socials.add(link)

        return raw_links, list(emails), list(socials), title

    async def _crawl_dynamic_spa(self, url: str) -> Optional[str]:
        """Fall back to Crawl4AI headless browser when static requests yield empty JS shells."""
        try:
            from crawl4ai import AsyncWebCrawler

            async with AsyncWebCrawler(verbose=False) as crawler:
                result = await crawler.arun(url=url)
                if result and result.markdown:
                    return result.markdown
        except Exception as e:
            logger.warning(f"Headless SPA extraction failed on {url}: {e}")
        return None

