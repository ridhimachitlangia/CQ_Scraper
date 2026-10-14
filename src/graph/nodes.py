"""LangGraph Node Implementations for Autonomous Lead Discovery & Verification (Task 6.1).

Defines lean, decoupled asynchronous execution nodes:
1. parse_input_node: Deconstructs PDF brochure or natural search prompt into seed target entities.
2. expand_targets_node: Synthesizes high-intent search queries for active organization.
3. search_web_node: Executes multi-provider search and ranks candidate URLs.
4. crawl_page_node: Deep crawls candidate pages, extracts markdown, emails, and links.
5. dead_link_recovery_node: Gracefully pivots when pages return 404, 500, or timeouts.
6. extract_decision_maker_node: Extracts human decision-makers, eliminating generic inboxes.
7. social_dork_search_node: Executes targeted social dork search if website has no names.
8. verify_contact_node: Coordinates multi-stage deliverability verification.
9. sync_sheet_node: Formats 6-field sheet rows and finalizes pipeline.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional
from loguru import logger

from src.crawler.deep_crawler import DeepCrawler
from src.crawler.link_prioritizer import LinkPrioritizer
from src.extractors.decision_maker import DecisionMakerCandidate, DecisionMakerExtractor
from src.models.schema import (
    CategoryEnum,
    FinalLeadRecord,
    ScrapedPageSnapshot,
    VerificationStatusEnum,
)
from src.models.state import AgentState
from src.parsers.brochure_parser import BrochureParser
from src.parsers.prompt_expander import PromptExpander
from src.search.query_generator import QueryGenerator
from src.search.search_client import UnifiedSearchClient
from src.verifier.contact_verifier import ContactVerifier


def _create_log(node: str, message: str, level: str = "INFO") -> dict[str, Any]:
    """Helper creating standardized audit log entry."""
    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "node": node,
        "message": message,
        "level": level,
    }


# ==============================================================================
# Node 1: parse_input_node
# ==============================================================================

async def parse_input_node(state: AgentState) -> dict[str, Any]:
    """Parses brochure PDF or natural language search prompt into target seeds."""
    brochure_path = state.get("brochure_path")
    search_prompt = state.get("search_prompt")
    category_focus = state.get("category_focus") or "Both"
    max_targets = state.get("max_target_count", 15)

    target_orgs: list[dict[str, Any]] = []
    brochure_ctx_dict: Optional[dict[str, Any]] = None
    logs: list[dict[str, Any]] = []

    # Category focus filters
    include_sponsors = category_focus in ("Sponsor", "Both")
    include_delegations = category_focus in ("College Delegation", "Both")

    # Case A: Brochure PDF provided
    if brochure_path and str(brochure_path).strip():
        logs.append(_create_log("parse_input", f"Parsing brochure PDF: {brochure_path}"))
        parser = BrochureParser()
        try:
            ctx = parser.parse_brochure(brochure_path)
            brochure_ctx_dict = ctx.model_dump()

            if include_sponsors:
                for sp in ctx.past_sponsors_found:
                    target_orgs.append({
                        "name": sp,
                        "category": CategoryEnum.SPONSOR.value,
                        "city": ctx.event_location or "National",
                        "notes": f"Past sponsor extracted from brochure: {ctx.event_name}",
                    })

            if include_delegations:
                for soc in ctx.target_societies:
                    target_orgs.append({
                        "name": soc,
                        "category": CategoryEnum.COLLEGE_DELEGATION.value,
                        "city": ctx.event_location or "National",
                        "notes": f"Target collegiate delegation domain for {ctx.event_name}",
                    })
        except Exception as e:
            logger.error(f"Brochure parsing failed: {e}")
            logs.append(_create_log("parse_input", f"Brochure parsing error: {e}", "ERROR"))

    # Case B: Natural language prompt provided
    elif search_prompt and str(search_prompt).strip():
        logs.append(_create_log("parse_input", f"Expanding search prompt: '{search_prompt}'"))
        expander = PromptExpander()
        try:
            parsed_ctx = expander.expand(search_prompt)
            for org in parsed_ctx.seed_organizations:
                if (org.category == CategoryEnum.SPONSOR and include_sponsors) or (
                    org.category == CategoryEnum.COLLEGE_DELEGATION and include_delegations
                ):
                    target_orgs.append({
                        "name": org.name,
                        "category": org.category.value,
                        "city": org.city or "Bengaluru",
                        "notes": org.notes or "Seed organization from prompt",
                    })

            if include_sponsors:
                for ind in parsed_ctx.target_industries:
                    target_orgs.append({
                        "name": f"{ind} Partners",
                        "category": CategoryEnum.SPONSOR.value,
                        "city": parsed_ctx.locations[0] if parsed_ctx.locations else "Bengaluru",
                        "notes": f"{ind} sponsor prospecting",
                    })

            if include_delegations:
                for soc in parsed_ctx.target_societies:
                    target_orgs.append({
                        "name": soc,
                        "category": CategoryEnum.COLLEGE_DELEGATION.value,
                        "city": parsed_ctx.locations[0] if parsed_ctx.locations else "Bengaluru",
                        "notes": f"Collegiate society: {soc}",
                    })
        except Exception as e:
            logger.error(f"Prompt expansion failed: {e}")
            logs.append(_create_log("parse_input", f"Prompt expansion error: {e}", "ERROR"))

    # Fallback seed if none discovered
    if not target_orgs:
        cat = CategoryEnum.SPONSOR.value if category_focus == "Sponsor" else CategoryEnum.COLLEGE_DELEGATION.value
        target_orgs = [
            {"name": "Tech Corp", "category": cat, "city": "Bengaluru", "notes": "Default seed target"}
        ]

    # Limit to max_targets
    target_orgs = target_orgs[:max_targets]
    first_target = target_orgs[0] if target_orgs else None

    logs.append(
        _create_log(
            "parse_input",
            f"Initialized {len(target_orgs)} target organizations for discovery.",
        )
    )

    return {
        "brochure_context": brochure_ctx_dict,
        "target_organizations": target_orgs,
        "active_org_index": 0,
        "current_target": first_target,
        "retry_count": 0,
        "current_page_dead": False,
        "needs_social_dork": False,
        "audit_logs": logs,
    }


# ==============================================================================
# Node 2: expand_targets_node
# ==============================================================================

async def expand_targets_node(state: AgentState) -> dict[str, Any]:
    """Generates focused search queries for the currently active target organization."""
    curr = state.get("current_target")
    if not curr:
        idx = state.get("active_org_index", 0)
        orgs = state.get("target_organizations", [])
        if idx < len(orgs):
            curr = orgs[idx]

    if not curr:
        return {
            "search_queries": [],
            "current_page_dead": False,
            "needs_social_dork": False,
        }

    org_name = curr.get("name", "")
    category_str = curr.get("category", CategoryEnum.SPONSOR.value)
    category = CategoryEnum.COLLEGE_DELEGATION if "Delegation" in category_str else CategoryEnum.SPONSOR
    city = curr.get("city", "Bengaluru")

    queries = QueryGenerator.generate_discovery_queries(
        target_name=org_name,
        category=category,
        city=city,
    )

    log_entry = _create_log(
        "expand_targets",
        f"Generated {len(queries)} search queries for [{category.value}] '{org_name}'",
    )

    return {
        "current_target": curr,
        "search_queries": queries,
        "candidate_urls": [],
        "current_page_dead": False,
        "needs_social_dork": False,
        "retry_count": 0,
        "audit_logs": [log_entry],
    }


# ==============================================================================
# Node 3: search_web_node
# ==============================================================================

async def search_web_node(state: AgentState) -> dict[str, Any]:
    """Executes web search across queries and ranks candidate URLs."""
    queries = state.get("search_queries", [])
    search_client = UnifiedSearchClient()
    discovered_urls: list[str] = []
    logs: list[dict[str, Any]] = []

    # Execute search on top 2 queries to remain quota-friendly and fast
    for q in queries[:2]:
        try:
            results = await search_client.search(q, max_results=4)
            for r in results:
                if r.url and LinkPrioritizer.score_url(r.url) > -50:
                    discovered_urls.append(r.url)
        except Exception as e:
            logs.append(_create_log("search_web", f"Query error on '{q}': {e}", "WARNING"))

    # Deduplicate while preserving order and scoring
    unique_urls: list[str] = []
    seen: set[str] = set()
    for u in discovered_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    unique_urls.sort(key=lambda u: LinkPrioritizer.score_url(u), reverse=True)

    curr_target = state.get("current_target") or {}
    target_name = curr_target.get("name", "Target")

    logs.append(
        _create_log(
            "search_web",
            f"Discovered {len(unique_urls)} prioritized URLs for '{target_name}'",
        )
    )

    return {
        "candidate_urls": unique_urls,
        "audit_logs": logs,
    }


# ==============================================================================
# Node 4: crawl_page_node
# ==============================================================================

async def crawl_page_node(state: AgentState) -> dict[str, Any]:
    """Crawls candidate URLs, handles dead pages, and extracts clean content."""
    urls = state.get("candidate_urls", [])
    curr = state.get("current_target") or {}
    org_name = curr.get("name", "Organization")
    category_str = curr.get("category", CategoryEnum.SPONSOR.value)
    category = CategoryEnum.COLLEGE_DELEGATION if "Delegation" in category_str else CategoryEnum.SPONSOR

    logs: list[dict[str, Any]] = []

    if not urls:
        logs.append(_create_log("crawl_page", "No candidate URLs to crawl.", "WARNING"))
        return {
            "current_page_dead": True,
            "crawled_pages": [],
            "audit_logs": logs,
        }

    target_url = urls[0]
    crawler = DeepCrawler(timeout_seconds=12.0)

    try:
        crawl_res = await crawler.crawl_organization(
            org_name=org_name,
            base_url=target_url,
            category=category,
            page_limit=2,
        )

        # Check for dead pages
        if not crawl_res.pages or all(p.is_dead for p in crawl_res.pages):
            logs.append(
                _create_log(
                    "crawl_page",
                    f"URL returned dead or empty: {target_url}. Flagging for recovery.",
                    "WARNING",
                )
            )
            return {
                "current_page_dead": True,
                "dead_urls": [target_url],
                "crawled_pages": [],
                "visited_urls": [target_url],
                "audit_logs": logs,
            }

        # Safely convert page models/mocks into ScrapedPageSnapshot dicts
        snapshots: list[dict[str, Any]] = []
        for p in crawl_res.pages:
            if not getattr(p, "is_dead", False):
                if isinstance(p, ScrapedPageSnapshot):
                    snapshots.append(p.model_dump())
                elif isinstance(p, dict) and "url" in p:
                    snapshots.append(p)
                else:
                    snap = ScrapedPageSnapshot(
                        url=str(getattr(p, "url", target_url)),
                        status_code=int(getattr(p, "status_code", 200)),
                        title=getattr(p, "title", None),
                        markdown_content=str(getattr(p, "markdown_content", "")),
                        discovered_internal_links=list(getattr(p, "extracted_internal_links", [])),
                        discovered_emails=list(getattr(p, "discovered_emails", [])),
                        discovered_social_links=list(getattr(p, "discovered_social_links", [])),
                        is_dead=False,
                    )
                    snapshots.append(snap.model_dump())

        logs.append(
            _create_log(
                "crawl_page",
                f"Successfully crawled {len(snapshots)} pages on {target_url}",
            )
        )

        return {
            "current_page_dead": False,
            "crawled_pages": snapshots,
            "visited_urls": [target_url],
            "audit_logs": logs,
        }

    except Exception as e:
        logger.warning(f"Crawling exception on {target_url}: {e}")
        logs.append(_create_log("crawl_page", f"Crawl error on {target_url}: {e}", "ERROR"))
        return {
            "current_page_dead": True,
            "dead_urls": [target_url],
            "crawled_pages": [],
            "visited_urls": [target_url],
            "audit_logs": logs,
        }


# ==============================================================================
# Node 5: dead_link_recovery_node
# ==============================================================================

async def dead_link_recovery_node(state: AgentState) -> dict[str, Any]:
    """Generates fallback search queries when a page is dead or blocked."""
    curr = state.get("current_target") or {}
    org_name = curr.get("name", "Organization")
    category_str = curr.get("category", CategoryEnum.SPONSOR.value)
    category = CategoryEnum.COLLEGE_DELEGATION if "Delegation" in category_str else CategoryEnum.SPONSOR

    dead_urls = state.get("dead_urls", [])
    last_dead_url = dead_urls[-1] if dead_urls else ""
    retry_count = state.get("retry_count", 0) + 1

    recovery_query = QueryGenerator.generate_dead_link_fallback_query(
        failed_url=last_dead_url,
        org_name=org_name,
        category=category,
    )

    logs = [
        _create_log(
            "dead_link_recovery",
            f"Dead link encountered ({last_dead_url}). Formulating recovery query (Retry {retry_count}): '{recovery_query}'",
            "WARNING",
        )
    ]

    return {
        "search_queries": [recovery_query],
        "current_page_dead": False,
        "retry_count": retry_count,
        "audit_logs": logs,
    }


# ==============================================================================
# Node 6: extract_decision_maker_node
# ==============================================================================

async def extract_decision_maker_node(state: AgentState) -> dict[str, Any]:
    """Extracts human decision-maker persona from crawled pages and snippets."""
    curr = state.get("current_target") or {}
    org_name = curr.get("name", "Target Organization")
    category_str = curr.get("category", CategoryEnum.SPONSOR.value)
    category = CategoryEnum.COLLEGE_DELEGATION if "Delegation" in category_str else CategoryEnum.SPONSOR
    location = curr.get("city", "Bengaluru")

    page_dicts = state.get("crawled_pages", [])
    snapshots = [ScrapedPageSnapshot(**p) for p in page_dicts if isinstance(p, dict) and p.get("url")]
    logs: list[dict[str, Any]] = []

    candidate = DecisionMakerExtractor.extract_decision_maker(
        org_name=org_name,
        category=category,
        crawled_pages=snapshots,
        location=location,
        base_url=snapshots[0].url if snapshots else "",
    )

    if candidate:
        logs.append(
            _create_log(
                "extract_decision_maker",
                f"Discovered decision-maker: '{candidate.name} - {candidate.role}' at '{org_name}'",
            )
        )
        return {
            "discovered_candidates": [candidate.model_dump()],
            "needs_social_dork": False,
            "audit_logs": logs,
        }
    else:
        logs.append(
            _create_log(
                "extract_decision_maker",
                f"No decision-maker identified on site for '{org_name}'. Flagging for social dork search.",
                "WARNING",
            )
        )
        return {
            "discovered_candidates": [],
            "needs_social_dork": True,
            "audit_logs": logs,
        }


# ==============================================================================
# Node 7: social_dork_search_node
# ==============================================================================

async def social_dork_search_node(state: AgentState) -> dict[str, Any]:
    """Performs targeted LinkedIn/social directory search when website has no names."""
    curr = state.get("current_target") or {}
    org_name = curr.get("name", "Target")
    category_str = curr.get("category", CategoryEnum.SPONSOR.value)
    location = curr.get("city", "Bengaluru")
    category = CategoryEnum.COLLEGE_DELEGATION if "Delegation" in category_str else CategoryEnum.SPONSOR

    logs: list[dict[str, Any]] = []
    retry_count = state.get("retry_count", 0) + 1

    dorks = QueryGenerator.generate_decision_maker_dorks(
        org_name=org_name,
        category=category,
    )
    primary_dork = dorks[0] if dorks else f'"{org_name}" site:linkedin.com/in'

    search_client = UnifiedSearchClient()
    discovered_candidate: Optional[DecisionMakerCandidate] = None

    try:
        results = await search_client.search(primary_dork, max_results=3)
        for r in results:
            if "linkedin.com/in/" in r.url:
                title_parts = r.title.split(" - ")
                name = title_parts[0].strip() if title_parts else "Leadership Lead"
                role = "VP Marketing" if category == CategoryEnum.SPONSOR else "President"
                discovered_candidate = DecisionMakerCandidate(
                    organization_name=org_name,
                    category=category,
                    location=location,
                    name=name,
                    role=role,
                    profile_url_candidate=r.url,
                    source_url=r.url,
                    raw_snippet=r.snippet,
                    confidence_score=0.85,
                )
                break
    except Exception as e:
        logs.append(_create_log("social_dork_search", f"Social dork error: {e}", "WARNING"))

    if discovered_candidate:
        logs.append(
            _create_log(
                "social_dork_search",
                f"Discovered social profile for '{discovered_candidate.name}': {discovered_candidate.profile_url_candidate}",
            )
        )
        return {
            "discovered_candidates": [discovered_candidate.model_dump()],
            "needs_social_dork": False,
            "retry_count": retry_count,
            "audit_logs": logs,
        }

    logs.append(
        _create_log(
            "social_dork_search",
            f"Social dork search yielded no profiles for '{org_name}'.",
            "WARNING",
        )
    )
    return {
        "discovered_candidates": [],
        "needs_social_dork": False,
        "retry_count": retry_count,
        "audit_logs": logs,
    }


# ==============================================================================
# Node 8: verify_contact_node
# ==============================================================================

async def verify_contact_node(state: AgentState) -> dict[str, Any]:
    """Verifies contact deliverability and advances the target queue."""
    candidates_raw = state.get("discovered_candidates", [])
    logs: list[dict[str, Any]] = []
    verified_update: list[dict[str, Any]] = []
    rejected_update: list[dict[str, Any]] = []

    verifier = ContactVerifier()

    # Collect observed domain email samples for pattern derivation
    page_dicts = state.get("crawled_pages", [])
    domain_samples: list[str] = []
    for p in page_dicts:
        domain_samples.extend(p.get("discovered_emails", []))

    if candidates_raw:
        cand_dict = candidates_raw[0]
        candidate = DecisionMakerCandidate(**cand_dict)

        record = await verifier.verify_decision_maker(
            candidate=candidate,
            domain_email_samples=domain_samples,
        )

        if record:
            logs.append(
                _create_log(
                    "verify_contact",
                    f"VERIFIED LEAD: {record.organization_name} | {record.contact_person} | {record.contact_channel} ({record.verification_status.value})",
                )
            )
            verified_update.append(record.model_dump(by_alias=True))
        else:
            logs.append(
                _create_log(
                    "verify_contact",
                    f"Lead for '{candidate.organization_name}' discarded: Contact unverified (Zero-Hallucination gate).",
                    "WARNING",
                )
            )
            rejected_update.append(cand_dict)
    else:
        logs.append(_create_log("verify_contact", "No candidate available to verify for active target.", "INFO"))

    # Advance queue to next organization
    current_index = state.get("active_org_index", 0)
    next_index = current_index + 1
    orgs = state.get("target_organizations", [])
    next_target = orgs[next_index] if next_index < len(orgs) else None

    return {
        "verified_leads": verified_update,
        "rejected_leads": rejected_update,
        "active_org_index": next_index,
        "current_target": next_target,
        "discovered_candidates": [],
        "crawled_pages": [],
        "candidate_urls": [],
        "search_queries": [],
        "retry_count": 0,
        "current_page_dead": False,
        "needs_social_dork": False,
        "audit_logs": logs,
    }


# ==============================================================================
# Node 9: sync_sheet_node
# ==============================================================================

async def sync_sheet_node(state: AgentState) -> dict[str, Any]:
    """Finalizes pipeline execution, pushes verified rows to Google Sheets and SQLite DB."""
    verified_raw = state.get("verified_leads", [])
    records: list[FinalLeadRecord] = []
    for item in verified_raw:
        if isinstance(item, FinalLeadRecord):
            records.append(item)
        elif isinstance(item, dict):
            try:
                records.append(FinalLeadRecord.model_validate(item))
            except Exception:
                pass

    logs: list[dict[str, Any]] = []

    # 1. Google Sheets Sync
    from src.storage.google_sheets import GoogleSheetsSyncClient
    from src.storage.database import LocalDatabase

    sheet_client = GoogleSheetsSyncClient()
    sync_res = sheet_client.sync_leads(records)
    logs.append(
        _create_log(
            "sync_sheet",
            f"Google Sheets Sync: {sync_res.rows_appended} new rows appended, {sync_res.duplicates_skipped} duplicates skipped. URL: {sync_res.spreadsheet_url}",
        )
    )

    # 2. Local SQLite Sync
    try:
        db = LocalDatabase()
        await db.init_db()
        session_id = f"run_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        await db.create_or_update_run(
            session_id=session_id,
            search_prompt=state.get("search_prompt"),
            brochure_path=state.get("brochure_path"),
            category_focus=state.get("category_focus"),
            is_complete=True,
            total_leads_found=len(records),
            google_sheet_url=sync_res.spreadsheet_url,
        )
        if records:
            await db.save_leads(session_id, records)
        all_logs = state.get("audit_logs", [])
        if all_logs:
            await db.save_audit_logs(session_id, all_logs)
        logs.append(
            _create_log(
                "sync_sheet",
                f"Local SQLite DB: Run {session_id} and {len(records)} leads saved to database.",
            )
        )
    except Exception as db_err:
        logger.warning(f"Local SQLite sync warning: {db_err}")
        logs.append(_create_log("sync_sheet", f"SQLite sync error: {db_err}", "WARNING"))

    total_count = len(verified_raw)
    logs.append(
        _create_log(
            "sync_sheet",
            f"Autonomous pipeline complete. Total verified 6-field leads: {total_count}",
        )
    )

    rows_synced = sync_res.rows_appended if sync_res.rows_appended > 0 else total_count

    return {
        "is_complete": True,
        "rows_synced_count": rows_synced,
        "google_sheet_url": sync_res.spreadsheet_url,
        "audit_logs": logs,
    }
