"""DNS MX Record Resolver (Task 5.2).

Asynchronously resolves DNS Mail Exchange (MX) records using dnspython,
sorts hosts by preference priority, detects RFC 7505 Null MX, and handles DNS failures.
"""

from __future__ import annotations

import asyncio
from typing import Optional
import dns.asyncresolver
import dns.exception
import dns.resolver
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field


class MXRecord(BaseModel):
    """Individual DNS MX record entry."""
    model_config = ConfigDict(extra="ignore")

    host: str = Field(..., description="Fully qualified domain name of mail exchange server")
    preference: int = Field(..., description="Priority preference number (lower = higher priority)")


class MXResolutionResult(BaseModel):
    """Result of DNS MX record resolution."""
    model_config = ConfigDict(extra="ignore")

    domain: str = Field(..., description="Queried domain name")
    has_mx: bool = Field(default=False, description="True if valid, reachable MX records exist")
    records: list[MXRecord] = Field(
        default_factory=list, description="List of sorted MX records by priority"
    )
    primary_host: Optional[str] = Field(
        default=None, description="Primary (lowest preference) MX server host"
    )
    is_null_mx: bool = Field(
        default=False, description="True if domain advertises RFC 7505 Null MX (no mail accepted)"
    )
    error_message: Optional[str] = Field(
        default=None, description="Detailed error description if query failed"
    )


class DNSMXResolver:
    """Asynchronous DNS MX resolver with caching and null MX detection."""

    def __init__(
        self,
        timeout: float = 5.0,
        nameservers: Optional[list[str]] = None,
    ) -> None:
        self.timeout = timeout
        self.resolver = dns.asyncresolver.Resolver()
        self.resolver.lifetime = timeout
        if nameservers:
            self.resolver.nameservers = nameservers
        self._cache: dict[str, MXResolutionResult] = {}

    async def resolve_mx(
        self, domain: str, use_cache: bool = True
    ) -> MXResolutionResult:
        """Asynchronously queries MX records for a target domain.

        Args:
            domain: Domain name (e.g., 'acme.com').
            use_cache: If True, uses cached result if previously resolved.

        Returns:
            MXResolutionResult with sorted records and primary host.
        """
        clean_domain = domain.strip().lower().rstrip(".")
        if not clean_domain:
            return MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message="Domain name is empty",
            )

        if use_cache and clean_domain in self._cache:
            return self._cache[clean_domain]

        try:
            answers = await self.resolver.resolve(clean_domain, "MX")
            records: list[MXRecord] = []

            for rdata in answers:
                host_str = str(rdata.exchange).rstrip(".")
                preference = int(rdata.preference)

                # RFC 7505 Null MX check: exchange is '.' (or empty) indicating domain rejects all mail
                if host_str in (".", ""):
                    logger.warning(
                        f"RFC 7505 Null MX record detected for domain '{clean_domain}'"
                    )
                    res = MXResolutionResult(
                        domain=clean_domain,
                        has_mx=False,
                        is_null_mx=True,
                        error_message="Domain explicitly specifies RFC 7505 Null MX (accepts no email)",
                    )
                    self._cache[clean_domain] = res
                    return res

                records.append(MXRecord(host=host_str, preference=preference))

            if not records:
                res = MXResolutionResult(
                    domain=clean_domain,
                    has_mx=False,
                    error_message="No MX records found for domain",
                )
                self._cache[clean_domain] = res
                return res

            # Sort by preference ascending (lowest number = highest priority)
            records.sort(key=lambda r: r.preference)
            primary = records[0].host

            res = MXResolutionResult(
                domain=clean_domain,
                has_mx=True,
                records=records,
                primary_host=primary,
            )
            self._cache[clean_domain] = res
            return res

        except dns.resolver.NXDOMAIN:
            logger.debug(f"DNS NXDOMAIN: Domain does not exist: '{clean_domain}'")
            res = MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message=f"Domain does not exist (NXDOMAIN): {clean_domain}",
            )
            self._cache[clean_domain] = res
            return res

        except dns.resolver.NoAnswer:
            logger.debug(f"DNS NoAnswer: No MX records for domain '{clean_domain}'")
            res = MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message=f"No MX record found for domain: {clean_domain}",
            )
            self._cache[clean_domain] = res
            return res

        except (dns.resolver.LifetimeTimeout, dns.exception.Timeout, asyncio.TimeoutError):
            logger.warning(f"DNS MX resolution timed out for domain '{clean_domain}'")
            return MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message=f"DNS lookup timed out for {clean_domain}",
            )

        except dns.exception.DNSException as exc:
            logger.warning(f"DNS query error for domain '{clean_domain}': {exc}")
            return MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message=f"DNS error: {exc}",
            )

        except Exception as exc:
            logger.error(f"Unexpected error resolving MX for '{clean_domain}': {exc}")
            return MXResolutionResult(
                domain=clean_domain,
                has_mx=False,
                error_message=f"Resolution error: {exc}",
            )

