"""Scraping Resilience, Dead-Link Recovery, and HTTP Hardening.

Provides polite request timing, randomized desktop user-agent rotation,
exponential backoff, and robust dead-page failover handling.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional
import httpx
from loguru import logger

from src.models.schema import CategoryEnum
from src.search.query_generator import QueryGenerator


DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


class DeadLinkRecord:
    """Record of an encountered dead, missing, or blocked URL."""

    def __init__(self, url: str, status_code: Optional[int], reason: str):
        self.url = url
        self.status_code = status_code
        self.reason = reason

    def __repr__(self) -> str:
        return f"DeadLink(url='{self.url}', status={self.status_code}, reason='{self.reason}')"


class DeadLinkHandler:
    """Detects dead pages and generates autonomous pivot strategies."""

    DEAD_STATUS_CODES = {404, 410, 403, 500, 502, 503, 504}

    @classmethod
    def is_dead_response(cls, status_code: int) -> bool:
        """Identifies if an HTTP status code represents a dead or unreachable page."""
        return status_code in cls.DEAD_STATUS_CODES

    @classmethod
    def handle_dead_url(
        cls,
        url: str,
        status_code: Optional[int],
        reason: str,
        org_name: str,
        category: CategoryEnum,
    ) -> dict[str, str]:
        """Logs the dead link and generates a recovery search dork."""
        logger.warning(
            f"Autonomous Agent encountered dead page: {url} "
            f"[{status_code or 'NO_STATUS'}: {reason}]. Initiating failover pivot."
        )

        recovery_query = QueryGenerator.generate_dead_link_fallback_query(
            failed_url=url,
            org_name=org_name,
            category=category,
        )

        return {
            "dead_url": url,
            "reason": reason,
            "status_code": str(status_code) if status_code else "TIMEOUT",
            "recovery_query": recovery_query,
        }


class ResilientFetcher:
    """Async HTTP fetcher equipped with polite jitter, backoff, and header rotation."""

    def __init__(self, timeout_seconds: float = 12.0, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def get_random_headers(self) -> dict[str, str]:
        """Generates realistic browser headers."""
        return {
            "User-Agent": random.choice(DESKTOP_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }

    async def fetch(self, url: str) -> tuple[Optional[str], int, Optional[str]]:
        """Fetches page content with retry logic. Returns (html_content, status_code, error_reason)."""
        headers = self.get_random_headers()
        
        for attempt in range(self.max_retries + 1):
            try:
                # Polite jitter delay between requests (0.5s to 1.5s)
                await asyncio.sleep(random.uniform(0.3, 0.8))

                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    headers=headers,
                    verify=False,  # Tolerate legacy SSL certs on collegiate sites
                ) as client:
                    response = await client.get(url)
                    status_code = response.status_code

                    if DeadLinkHandler.is_dead_response(status_code):
                        return None, status_code, f"HTTP Error {status_code}"

                    return response.text, status_code, None

            except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                if attempt == self.max_retries:
                    return None, 408, f"Request Timeout: {e}"
                await asyncio.sleep(1.0 * (2 ** attempt))

            except (httpx.ConnectError, httpx.RequestError) as e:
                if attempt == self.max_retries:
                    return None, 502, f"Network Connection Error: {e}"
                await asyncio.sleep(1.0 * (2 ** attempt))

            except Exception as e:
                return None, 500, f"Unexpected Fetch Exception: {e}"

        return None, 500, "Max retries exceeded"

