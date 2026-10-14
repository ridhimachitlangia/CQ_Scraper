"""Conditional routing edges and state transition logic (Task 6.2).

Enforces self-healing cyclical loops:
1. route_after_crawl: Pivots to dead_link_recovery on 404/500/timeout without failing run.
2. route_after_extraction: Pivots to social_dork_search if corporate website has no personal names.
3. route_after_verification: Loops back to expand_targets for the next organization,
   or terminates at sync_sheet when target quota or queue completion is reached.
"""

from __future__ import annotations

from loguru import logger
from src.models.state import AgentState


def route_after_crawl(state: AgentState) -> str:
    """Routes execution after page crawl: dead page recovery vs extraction."""
    is_dead = state.get("current_page_dead", False)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if is_dead and retry_count < max_retries:
        logger.info(
            f"Edge routing -> 'dead_link_recovery' (Attempt {retry_count + 1}/{max_retries})"
        )
        return "dead_link_recovery"

    return "extract_decision_maker"


def route_after_extraction(state: AgentState) -> str:
    """Routes execution after extraction: social dork fallback vs verification."""
    needs_dork = state.get("needs_social_dork", False)
    candidates = state.get("discovered_candidates", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if not candidates and needs_dork and retry_count < max_retries:
        logger.info(
            f"Edge routing -> 'social_dork_search' (Attempt {retry_count + 1}/{max_retries})"
        )
        return "social_dork_search"

    return "verify_contact"


def route_after_verification(state: AgentState) -> str:
    """Routes execution after contact verification: loop to next target vs complete."""
    verified_leads = state.get("verified_leads", [])
    max_target_count = state.get("max_target_count", 15)
    active_org_index = state.get("active_org_index", 0)
    target_organizations = state.get("target_organizations", [])

    # Termination conditions: quota reached or all targets in queue processed
    if len(verified_leads) >= max_target_count:
        logger.info(
            f"Target quota met ({len(verified_leads)}/{max_target_count}). Edge routing -> 'sync_sheet'"
        )
        return "sync_sheet"

    if active_org_index >= len(target_organizations):
        logger.info(
            f"All {len(target_organizations)} targets processed. Edge routing -> 'sync_sheet'"
        )
        return "sync_sheet"

    logger.info(
        f"Processing next target organization ({active_org_index + 1}/{len(target_organizations)}). Edge routing -> 'expand_targets'"
    )
    return "expand_targets"
