"""Crawler package exports for CQ Scraper."""

from src.crawler.deep_crawler import CrawlResult, DeepCrawler
from src.crawler.link_prioritizer import LinkPrioritizer
from src.crawler.resilience import DeadLinkHandler, DeadLinkRecord, ResilientFetcher

__all__ = [
    "DeepCrawler",
    "CrawlResult",
    "LinkPrioritizer",
    "ResilientFetcher",
    "DeadLinkHandler",
    "DeadLinkRecord",
]
