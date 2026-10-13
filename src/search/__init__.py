"""Search package exports for CQ Scraper."""

from src.search.query_generator import QueryGenerator
from src.search.search_client import SearchResult, UnifiedSearchClient

__all__ = [
    "QueryGenerator",
    "UnifiedSearchClient",
    "SearchResult",
]
