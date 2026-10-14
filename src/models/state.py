"""LangGraph State definition for CQ Scraper.

Implements immutable TypedDict state architecture with typed reducers
to support cyclical agent workflows, resilient error handling, and state checkpointing.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict
from src.models.schema import FinalLeadRecord, TargetOrganization


class AgentState(TypedDict, total=False):
    """The master LangGraph state passed between all graph nodes."""

    # --- Initial User Inputs ---
    search_prompt: Optional[str]
    brochure_path: Optional[str]
    category_focus: Optional[str]  # "Sponsor" | "College Delegation" | "Both"
    max_target_count: int

    # --- Brochure Analysis & Intent Extraction ---
    brochure_context: Optional[dict[str, Any]]
    
    # --- Target Discovery Queue ---
    target_organizations: list[dict[str, Any]]
    active_org_index: int
    current_target: Optional[dict[str, Any]]

    # --- Search & Crawl Queues ---
    search_queries: list[str]
    candidate_urls: list[str]
    visited_urls: Annotated[list[str], operator.add]
    dead_urls: Annotated[list[str], operator.add]
    crawled_pages: list[dict[str, Any]]

    # --- Candidate Extraction ---
    discovered_candidates: list[dict[str, Any]]

    # --- Verification & Lead Accumulation ---
    verified_leads: Annotated[list[dict[str, Any]], operator.add]
    rejected_leads: Annotated[list[dict[str, Any]], operator.add]

    # --- Resilience & Cycle Controls ---
    retry_count: int
    max_retries: int
    is_complete: bool
    current_page_dead: bool
    needs_social_dork: bool

    # --- Export & External Sync ---
    google_sheet_url: Optional[str]
    rows_synced_count: int

    # --- Audit & Real-time Logs ---
    audit_logs: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


def create_initial_state(
    search_prompt: Optional[str] = None,
    brochure_path: Optional[str] = None,
    category_focus: Optional[str] = "Both",
    max_target_count: int = 15,
    max_retries: int = 3,
) -> AgentState:
    """Factory creating a sanitized, pristine initial AgentState."""
    return AgentState(
        search_prompt=search_prompt,
        brochure_path=brochure_path,
        category_focus=category_focus,
        max_target_count=max_target_count,
        brochure_context=None,
        target_organizations=[],
        active_org_index=0,
        current_target=None,
        search_queries=[],
        candidate_urls=[],
        visited_urls=[],
        dead_urls=[],
        crawled_pages=[],
        discovered_candidates=[],
        verified_leads=[],
        rejected_leads=[],
        retry_count=0,
        max_retries=max_retries,
        is_complete=False,
        current_page_dead=False,
        needs_social_dork=False,
        google_sheet_url=None,
        rows_synced_count=0,
        audit_logs=[],
        errors=[],
    )

