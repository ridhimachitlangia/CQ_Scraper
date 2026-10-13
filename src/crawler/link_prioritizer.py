"""URL Prioritization and Scoring Engine.

Ranks discovered hyperlinks to prioritize corporate leadership, team,
and student council pages while discarding low-intent boilerplate and traps.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from loguru import logger


class LinkPrioritizer:
    """Filters, normalizes, and ranks URLs based on intent keywords."""

    HIGH_PRIORITY_KEYWORDS = [
        "team", "about", "leadership", "people", "executive", "council",
        "board", "founders", "management", "cabinet", "office-bearers",
        "governing", "secretariat", "whoweare", "who-we-are"
    ]

    MEDIUM_PRIORITY_KEYWORDS = [
        "contact", "press", "partners", "sponsors", "csr", "media",
        "overview", "society", "club", "core", "faculty"
    ]

    BLACKLIST_PATTERNS = [
        r"/(privacy|terms|legal|disclaimer|copyright)",
        r"/(login|signin|signup|register|auth|password)",
        r"/(cart|checkout|shop|store|product|item|basket)",
        r"/(careers|jobs|vacancies|apply|internships)",
        r"/(wp-admin|wp-content|wp-includes|xmlrpc)",
        r"/(feed|rss|tag|category|archive|page/\d+)",
        r"\.(png|jpg|jpeg|gif|svg|webp|ico|css|js|woff|woff2|ttf|pdf|zip|tar|gz|exe)$",
        r"^(mailto:|tel:|javascript:|#)",
    ]

    @classmethod
    def normalize_url(cls, raw_url: str, base_url: str) -> str | None:
        """Resolves relative URLs, removes fragments and tracking parameters."""
        if not raw_url or not isinstance(raw_url, str):
            return None

        clean = raw_url.strip()
        for pattern in cls.BLACKLIST_PATTERNS:
            if re.search(pattern, clean, re.IGNORECASE):
                return None

        # Resolve relative URLs
        absolute = urljoin(base_url, clean)
        parsed = urlparse(absolute)

        if parsed.scheme not in ["http", "https"]:
            return None

        # Normalize host and path, drop query & fragment
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        if not path:
            path = "/"

        return f"{parsed.scheme}://{netloc}{path}"

    @classmethod
    def is_same_domain(cls, candidate_url: str, base_url: str) -> bool:
        """Checks if candidate URL belongs to the same parent domain."""
        try:
            cand_netloc = urlparse(candidate_url).netloc.lower()
            base_netloc = urlparse(base_url).netloc.lower()

            # Strip www prefix
            cand_domain = re.sub(r"^www\.", "", cand_netloc)
            base_domain = re.sub(r"^www\.", "", base_netloc)

            return cand_domain == base_domain or cand_domain.endswith(f".{base_domain}")
        except Exception:
            return False

    @classmethod
    def score_url(cls, url: str) -> int:
        """Assigns an integer score indicating probability of containing decision-makers."""
        path_lower = urlparse(url).path.lower()
        score = 0

        # Check blacklist
        for pattern in cls.BLACKLIST_PATTERNS:
            if re.search(pattern, path_lower, re.IGNORECASE):
                return -100

        # High priority matches
        for kw in cls.HIGH_PRIORITY_KEYWORDS:
            if kw in path_lower:
                score += 10

        # Medium priority matches
        for kw in cls.MEDIUM_PRIORITY_KEYWORDS:
            if kw in path_lower:
                score += 5

        # Penalize deep nesting
        segments = [s for s in path_lower.split("/") if s]
        if len(segments) > 4:
            score -= 2

        return score

    @classmethod
    def prioritize_links(
        cls,
        discovered_urls: list[str],
        base_url: str,
        max_links: int = 5,
    ) -> list[str]:
        """Filters, ranks, and returns the top high-intent internal URLs."""
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()

        for raw in discovered_urls:
            normalized = cls.normalize_url(raw, base_url)
            if not normalized or normalized in seen:
                continue

            # Restrict to internal links or official social profiles
            if not cls.is_same_domain(normalized, base_url):
                # Allow LinkedIn/Instagram if direct profile link
                if "linkedin.com/in/" in normalized or "instagram.com/" in normalized:
                    scored.append((15, normalized))
                    seen.add(normalized)
                continue

            score = cls.score_url(normalized)
            if score > -50:
                scored.append((score, normalized))
                seen.add(normalized)

        # Sort descending by score
        scored.sort(key=lambda x: x[0], reverse=True)
        return [url for _, url in scored[:max_links]]

