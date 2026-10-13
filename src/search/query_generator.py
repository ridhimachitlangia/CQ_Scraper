"""Contextual Search Query and Dork Generator.

Builds targeted Google/Tavily search dorks to pinpoint corporate leadership
and collegiate society executive boards while providing dead-page fallback queries.
"""

from __future__ import annotations

import re
from typing import Optional
from src.models.schema import CategoryEnum


class QueryGenerator:
    """Generates focused search queries and fallback dorks for leads."""

    @staticmethod
    def generate_discovery_queries(
        target_name: str,
        category: CategoryEnum,
        city: Optional[str] = None,
    ) -> list[str]:
        """Generates initial seed queries to discover company/society domains and team pages."""
        clean_name = re.sub(r'["\']', '', target_name).strip()
        loc_clause = f" {city}" if city and city.lower() != "national" else ""

        if category == CategoryEnum.SPONSOR:
            return [
                f'"{clean_name}"{loc_clause} official website',
                f'"{clean_name}" ("leadership" OR "team" OR "about us")',
                f'"{clean_name}" ("VP Marketing" OR "Head of Marketing" OR "CSR Head")',
                f'"{clean_name}" site:linkedin.com/in ("marketing" OR "brand" OR "partnerships")',
            ]
        else:  # COLLEGE_DELEGATION
            return [
                f'"{clean_name}"{loc_clause} student society website',
                f'"{clean_name}" ("President" OR "Convenor" OR "Secretary" OR "Council")',
                f'"{clean_name}" site:instagram.com',
                f'"{clean_name}" site:linkedin.com/company OR site:linkedin.com/in',
            ]

    @staticmethod
    def generate_decision_maker_dorks(
        org_name: str,
        category: CategoryEnum,
    ) -> list[str]:
        """Generates targeted LinkedIn and web dorks when direct website team page has no names."""
        clean_name = re.sub(r'["\']', '', org_name).strip()

        if category == CategoryEnum.SPONSOR:
            return [
                f'site:linkedin.com/in "{clean_name}" ("Head of Marketing" OR "VP Marketing" OR "CMO")',
                f'site:linkedin.com/in "{clean_name}" ("Head of CSR" OR "CSR Lead" OR "Brand Director")',
                f'"{clean_name}" ("press release" OR "spokesperson") "marketing"',
            ]
        else:
            return [
                f'site:linkedin.com/in "{clean_name}" ("President" OR "General Secretary" OR "Convenor")',
                f'site:instagram.com "{clean_name}" ("president" OR "convenor" OR "contact")',
                f'"{clean_name}" ("executive board" OR "core team" OR "office bearers")',
            ]

    @staticmethod
    def generate_dead_link_fallback_query(
        failed_url: str,
        org_name: str,
        category: CategoryEnum,
    ) -> str:
        """Generates an alternate search dork when a target page returns 404, 500, or is dead."""
        clean_name = re.sub(r'["\']', '', org_name).strip()
        if category == CategoryEnum.SPONSOR:
            return f'"{clean_name}" official website linkedin marketing contact'
        return f'"{clean_name}" student council president instagram linkedin'

