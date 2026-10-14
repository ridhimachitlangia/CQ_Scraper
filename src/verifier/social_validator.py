"""Social Profile Liveness & Personal Identity Validator (Task 5.4).

Performs asynchronous HTTP requests (HEAD / GET) to candidate social profile URLs
(LinkedIn, Instagram, X/Twitter, University Faculty Pages) to verify liveness (HTTP 200),
ensure the profile is active, and exclude generic company/directory pages.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse
import httpx
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field


# Phrases indicating that a profile does not exist or is suspended/private/deleted
PROFILE_NOT_FOUND_PATTERNS = [
    re.compile(r"profile\s+not\s+found", re.IGNORECASE),
    re.compile(r"page\s+not\s+found", re.IGNORECASE),
    re.compile(r"account\s+suspended", re.IGNORECASE),
    re.compile(r"this\s+account\s+doesn't\s+exist", re.IGNORECASE),
    re.compile(r"user\s+not\s+found", re.IGNORECASE),
    re.compile(r"this\s+page\s+isn't\s+available", re.IGNORECASE),
    re.compile(r"sorry,\s+this\s+page\s+isn't\s+available", re.IGNORECASE),
]

# Patterns strictly identifying personal profile URLs vs company/service paths
LINKEDIN_PERSONAL_PATTERN = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_\-%]+/?$", re.IGNORECASE)
LINKEDIN_COMPANY_PATTERN = re.compile(r"^https?://([a-z]{2,3}\.)?linkedin\.com/(company|school|groups|showcase|feed|jobs|learning|pulse)(/|$|\?)", re.IGNORECASE)

INSTAGRAM_PROFILE_PATTERN = re.compile(r"^https?://(www\.)?instagram\.com/[a-zA-Z0-9_\.]+[/?]?$", re.IGNORECASE)
INSTAGRAM_NON_PROFILE = re.compile(r"^https?://(www\.)?instagram\.com/(p|reel|tv|explore|stories|accounts|direct)(/|$|\?)", re.IGNORECASE)

TWITTER_PROFILE_PATTERN = re.compile(r"^https?://(www\.)?(twitter|x)\.com/[a-zA-Z0-9_]{1,30}[/?]?$", re.IGNORECASE)
TWITTER_NON_PROFILE = re.compile(r"^https?://(www\.)?(twitter|x)\.com/(home|explore|search|i|settings|intent|notifications|messages)(/|$|\?)", re.IGNORECASE)


class SocialValidationResult(BaseModel):
    """Result of social profile URL verification."""
    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., description="Target profile URL checked")
    normalized_url: str = Field(..., description="Normalized canonical profile URL")
    platform: str = Field(
        default="web", description="Detected platform (linkedin, instagram, twitter, faculty, web)"
    )
    is_personal_profile: bool = Field(
        default=False, description="True if URL format matches an individual person or society account"
    )
    is_live: bool = Field(
        default=False, description="True if HTTP endpoint returns active 200/reachable state"
    )
    status_code: Optional[int] = Field(
        default=None, description="HTTP response status code"
    )
    error_message: Optional[str] = Field(
        default=None, description="Reason if profile verification failed"
    )


class SocialProfileValidator:
    """Validates personal profile URL structure and live reachability."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout

    @classmethod
    def classify_url(cls, url: str) -> tuple[str, bool]:
        """Classifies the URL platform and verifies if it is a personal profile.

        Returns:
            Tuple of (platform_name, is_personal_profile).
        """
        clean_url = url.strip()
        parsed = urlparse(clean_url)
        domain = parsed.netloc.lower()

        # LinkedIn
        if "linkedin.com" in domain:
            if LINKEDIN_COMPANY_PATTERN.search(clean_url):
                return "linkedin", False
            if LINKEDIN_PERSONAL_PATTERN.match(clean_url):
                return "linkedin", True
            return "linkedin", False

        # Instagram
        if "instagram.com" in domain:
            if INSTAGRAM_NON_PROFILE.search(clean_url):
                return "instagram", False
            if INSTAGRAM_PROFILE_PATTERN.match(clean_url):
                return "instagram", True
            return "instagram", False

        # Twitter / X
        if "twitter.com" in domain or "x.com" in domain:
            if TWITTER_NON_PROFILE.search(clean_url):
                return "twitter", False
            if TWITTER_PROFILE_PATTERN.match(clean_url):
                return "twitter", True
            return "twitter", False

        # University / Institutional Faculty or Society directory
        if any(edu in domain for edu in (".ac.in", ".edu", ".ernet.in", ".org")):
            return "faculty", True

        # General web URL
        return "web", True

    async def validate_profile_url(
        self,
        url: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> SocialValidationResult:
        """Asynchronously verifies profile URL format and live status.

        Args:
            url: Profile URL candidate.
            client: Optional httpx.AsyncClient instance.

        Returns:
            SocialValidationResult with liveness status and classification.
        """
        clean_url = url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            return SocialValidationResult(
                url=clean_url,
                normalized_url=clean_url,
                is_personal_profile=False,
                is_live=False,
                error_message="URL must begin with http:// or https://",
            )

        platform, is_personal = self.classify_url(clean_url)

        # Immediate filter: reject generic company pages
        if not is_personal:
            logger.debug(
                f"URL rejected: Not a personal or collegiate delegation profile ({clean_url})"
            )
            return SocialValidationResult(
                url=clean_url,
                normalized_url=clean_url,
                platform=platform,
                is_personal_profile=False,
                is_live=False,
                error_message="URL is a corporate page, directory listing, or non-profile endpoint",
            )

        # Normalize URL (clean trailing slash where appropriate)
        normalized = clean_url.rstrip("/")

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        should_close = False
        if client is None:
            client = httpx.AsyncClient(
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
                verify=False,
            )
            should_close = True

        try:
            # First attempt lightweight HEAD request
            response = None
            try:
                response = await client.head(normalized)
                # Some servers disallow HEAD (405 Method Not Allowed)
                if response.status_code == 405:
                    response = await client.get(normalized)
            except Exception:
                # Fallback to GET
                response = await client.get(normalized)

            status_code = response.status_code

            # Major platforms (LinkedIn, Instagram) often return 999 or 302/redirect to login
            # for unauthenticated web requests, but 200 or 999 indicates the slug is recognized
            # and routed rather than returning 404 (Not Found) or 410 (Gone).
            if status_code in (200, 301, 302, 307, 308):
                # Verify body doesn't contain explicit 'Not Found' strings
                body_sample = ""
                try:
                    body_sample = response.text[:2000]
                except Exception:
                    pass

                for pattern in PROFILE_NOT_FOUND_PATTERNS:
                    if pattern.search(body_sample):
                        return SocialValidationResult(
                            url=clean_url,
                            normalized_url=normalized,
                            platform=platform,
                            is_personal_profile=True,
                            is_live=False,
                            status_code=status_code,
                            error_message="Profile not found page returned by platform",
                        )

                return SocialValidationResult(
                    url=clean_url,
                    normalized_url=normalized,
                    platform=platform,
                    is_personal_profile=True,
                    is_live=True,
                    status_code=status_code,
                )

            # LinkedIn anti-scraping 999 HTTP status check
            if status_code == 999 and platform == "linkedin":
                # HTTP 999 is LinkedIn's bot challenge response for valid URLs
                return SocialValidationResult(
                    url=clean_url,
                    normalized_url=normalized,
                    platform=platform,
                    is_personal_profile=True,
                    is_live=True,
                    status_code=status_code,
                )

            if status_code in (404, 410):
                return SocialValidationResult(
                    url=clean_url,
                    normalized_url=normalized,
                    platform=platform,
                    is_personal_profile=True,
                    is_live=False,
                    status_code=status_code,
                    error_message=f"Profile URL returned HTTP {status_code} (Not Found)",
                )

            return SocialValidationResult(
                url=clean_url,
                normalized_url=normalized,
                platform=platform,
                is_personal_profile=True,
                is_live=False,
                status_code=status_code,
                error_message=f"HTTP response status: {status_code}",
            )

        except (httpx.TimeoutException, httpx.NetworkError) as net_err:
            logger.warning(f"Network error checking profile URL {normalized}: {net_err}")
            return SocialValidationResult(
                url=clean_url,
                normalized_url=normalized,
                platform=platform,
                is_personal_profile=True,
                is_live=False,
                error_message=f"Network error: {net_err}",
            )
        except Exception as exc:
            logger.error(f"Unexpected error validating profile URL {normalized}: {exc}")
            return SocialValidationResult(
                url=clean_url,
                normalized_url=normalized,
                platform=platform,
                is_personal_profile=True,
                is_live=False,
                error_message=f"Validation error: {exc}",
            )
        finally:
            if should_close:
                await client.aclose()
