"""Unit and integration tests for LangGraph State Machine (Phase 6).

Tests:
- Task 6.1: Node execution (parse_input, expand_targets, search_web, crawl_page,
  extract_decision_maker, social_dork_search, verify_contact, sync_sheet).
- Task 6.2: Conditional routing edges (route_after_crawl, route_after_extraction,
  route_after_verification).
- Task 6.3: StateGraph compilation, checkpointing, and end-to-end execution flow.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.graph.edges import (
    route_after_crawl,
    route_after_extraction,
    route_after_verification,
)
from src.graph.lead_graph import build_lead_discovery_graph
from src.graph.nodes import (
    crawl_page_node,
    dead_link_recovery_node,
    expand_targets_node,
    extract_decision_maker_node,
    parse_input_node,
    search_web_node,
    social_dork_search_node,
    sync_sheet_node,
    verify_contact_node,
)
from src.models.schema import (
    CategoryEnum,
    DecisionMakerCandidate,
    FinalLeadRecord,
    ScrapedPageSnapshot,
    VerificationStatusEnum,
)
from src.models.state import AgentState, create_initial_state


# ==============================================================================
# Task 6.1: Node Tests
# ==============================================================================

class TestGraphNodes:
    @pytest.mark.asyncio
    async def test_parse_input_node_prompt(self):
        """parse_input_node extracts target organization seeds from search prompt."""
        state = create_initial_state(
            search_prompt="Find AI startup sponsors in Bengaluru",
            category_focus="Sponsor",
            max_target_count=5,
        )
        res = await parse_input_node(state)
        assert "target_organizations" in res
        assert len(res["target_organizations"]) > 0
        assert res["active_org_index"] == 0
        assert res["current_target"] is not None
        assert res["current_target"]["name"] is not None

    @pytest.mark.asyncio
    async def test_expand_targets_node(self):
        """expand_targets_node generates queries for active organization."""
        state = create_initial_state()
        state["current_target"] = {
            "name": "Acme Technologies",
            "category": "Sponsor",
            "city": "Bengaluru",
            "notes": "Cloud & AI",
        }
        res = await expand_targets_node(state)
        assert len(res["search_queries"]) > 0
        assert any("Acme Technologies" in q for q in res["search_queries"])

    @pytest.mark.asyncio
    async def test_search_web_node(self):
        """search_web_node queries search client and filters blacklisted URLs."""
        state = create_initial_state()
        state["search_queries"] = ["Acme Technologies leadership team"]

        mock_search_results = [
            MagicMock(url="https://acme.com/team", title="Team", snippet="Our leaders"),
            MagicMock(url="https://acme.com/privacy-policy", title="Privacy", snippet="Terms"),
        ]

        with patch("src.graph.nodes.UnifiedSearchClient.search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_search_results
            res = await search_web_node(state)
            assert "candidate_urls" in res
            # Privacy policy should be filtered out by LinkPrioritizer
            assert "https://acme.com/team" in res["candidate_urls"]
            assert "https://acme.com/privacy-policy" not in res["candidate_urls"]

    @pytest.mark.asyncio
    async def test_crawl_page_node_success(self):
        """crawl_page_node crawls candidate URL and populates crawled_pages."""
        state = create_initial_state()
        state["candidate_urls"] = ["https://acme.com/team"]

        mock_page = MagicMock(
            url="https://acme.com/team",
            status_code=200,
            title="Leadership",
            markdown_content="Sarah Connor, VP Marketing. Contact: sarah.c@acme.com",
            extracted_internal_links=[],
            discovered_emails=["sarah.c@acme.com"],
            discovered_social_links=["https://linkedin.com/in/sarah-connor"],
            is_dead=False,
        )
        mock_crawl_res = MagicMock(pages=[mock_page])

        with patch("src.graph.nodes.DeepCrawler.crawl_organization", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = mock_crawl_res
            res = await crawl_page_node(state)
            assert res["current_page_dead"] is False
            assert len(res["crawled_pages"]) == 1
            assert res["crawled_pages"][0]["url"] == "https://acme.com/team"
            assert "https://acme.com/team" in res["visited_urls"]

    @pytest.mark.asyncio
    async def test_crawl_page_node_dead_link_detection(self):
        """crawl_page_node flags dead links and appends to dead_urls."""
        state = create_initial_state()
        state["candidate_urls"] = ["https://broken-link.com/team"]

        # Crawler returns empty or dead pages
        mock_crawl_res = MagicMock(pages=[])

        with patch("src.graph.nodes.DeepCrawler.crawl_organization", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = mock_crawl_res
            res = await crawl_page_node(state)
            assert res["current_page_dead"] is True
            assert "https://broken-link.com/team" in res["dead_urls"]

    @pytest.mark.asyncio
    async def test_dead_link_recovery_node(self):
        """dead_link_recovery_node reformulates search query and increments retry count."""
        state = create_initial_state()
        state["current_target"] = {"name": "Acme Corp", "category": "Sponsor"}
        state["dead_urls"] = ["https://broken-link.com"]
        state["retry_count"] = 0

        res = await dead_link_recovery_node(state)
        assert res["retry_count"] == 1
        assert res["current_page_dead"] is False
        assert len(res["search_queries"]) > 0
        assert "Acme Corp" in res["search_queries"][0]

    @pytest.mark.asyncio
    async def test_extract_decision_maker_node_found(self):
        """extract_decision_maker_node extracts human persona and sets discovered_candidates."""
        state = create_initial_state()
        state["current_target"] = {
            "name": "Acme Technologies",
            "category": "Sponsor",
            "city": "Bengaluru",
        }
        page = ScrapedPageSnapshot(
            url="https://acme.com/team",
            markdown_content="Sarah Connor, VP Marketing\nContact: sarah.connor@acme.com",
            discovered_emails=["sarah.connor@acme.com"],
            discovered_social_links=["https://linkedin.com/in/sarah-connor"],
        )
        state["crawled_pages"] = [page.model_dump()]

        res = await extract_decision_maker_node(state)
        assert len(res["discovered_candidates"]) == 1
        cand = res["discovered_candidates"][0]
        assert cand["name"] == "Sarah Connor"
        assert cand["role"] == "VP Marketing"
        assert res["needs_social_dork"] is False

    @pytest.mark.asyncio
    async def test_social_dork_search_node(self):
        """social_dork_search_node recovers candidate from LinkedIn search snippet."""
        state = create_initial_state()
        state["current_target"] = {
            "name": "Stealth Corp",
            "category": "Sponsor",
            "city": "Mumbai",
        }
        state["retry_count"] = 0

        mock_search_results = [
            MagicMock(
                url="https://www.linkedin.com/in/vikram-patel",
                title="Vikram Patel - Head of Marketing - Stealth Corp",
                snippet="Leading global brand sponsorships at Stealth Corp.",
            )
        ]

        with patch("src.graph.nodes.UnifiedSearchClient.search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_search_results
            res = await social_dork_search_node(state)
            assert len(res["discovered_candidates"]) == 1
            cand = res["discovered_candidates"][0]
            assert cand["name"] == "Vikram Patel"
            assert cand["profile_url_candidate"] == "https://www.linkedin.com/in/vikram-patel"
            assert res["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_verify_contact_node_deliverable(self):
        """verify_contact_node validates deliverability and increments active_org_index."""
        state = create_initial_state()
        state["target_organizations"] = [
            {"name": "Org 1", "category": "Sponsor"},
            {"name": "Org 2", "category": "Sponsor"},
        ]
        state["active_org_index"] = 0
        state["current_target"] = state["target_organizations"][0]

        cand = DecisionMakerCandidate(
            organization_name="Org 1",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            name="Sarah Connor",
            role="VP Marketing",
            email_candidate="sarah.connor@acme.com",
            source_url="https://acme.com",
        )
        state["discovered_candidates"] = [cand.model_dump()]

        mock_record = FinalLeadRecord(
            organization_name="Org 1",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            contact_person="Sarah Connor - VP Marketing",
            contact_channel="sarah.connor@acme.com",
            verification_status=VerificationStatusEnum.VERIFIED,
        )

        with patch("src.graph.nodes.ContactVerifier.verify_decision_maker", new_callable=AsyncMock) as mock_v:
            mock_v.return_value = mock_record
            res = await verify_contact_node(state)
            assert len(res["verified_leads"]) == 1
            assert res["active_org_index"] == 1
            assert res["current_target"] == state["target_organizations"][1]

    @pytest.mark.asyncio
    async def test_sync_sheet_node(self):
        """sync_sheet_node marks state complete and reports verified row count."""
        state = create_initial_state()
        record = FinalLeadRecord(
            organization_name="Org 1",
            category=CategoryEnum.SPONSOR,
            location="Bengaluru",
            contact_person="Sarah Connor - VP Marketing",
            contact_channel="sarah@acme.com",
            verification_status=VerificationStatusEnum.VERIFIED,
        )
        state["verified_leads"] = [record.model_dump(by_alias=True)]
        res = await sync_sheet_node(state)
        assert res["is_complete"] is True
        assert res["rows_synced_count"] == 1


# ==============================================================================
# Task 6.2: Conditional Edges Tests
# ==============================================================================

class TestGraphEdges:
    def test_route_after_crawl_dead_page(self):
        """Dead page triggers route to dead_link_recovery if retry_count < max_retries."""
        state = create_initial_state()
        state["current_page_dead"] = True
        state["retry_count"] = 0
        state["max_retries"] = 3
        assert route_after_crawl(state) == "dead_link_recovery"

        # Max retries exceeded -> proceeds to extraction
        state["retry_count"] = 3
        assert route_after_crawl(state) == "extract_decision_maker"

    def test_route_after_crawl_live_page(self):
        """Live page proceeds directly to extract_decision_maker."""
        state = create_initial_state()
        state["current_page_dead"] = False
        assert route_after_crawl(state) == "extract_decision_maker"

    def test_route_after_extraction_needs_social_dork(self):
        """Missing candidate triggers route to social_dork_search."""
        state = create_initial_state()
        state["needs_social_dork"] = True
        state["discovered_candidates"] = []
        state["retry_count"] = 0
        assert route_after_extraction(state) == "social_dork_search"

        # Candidate present -> proceeds to verify_contact
        state["discovered_candidates"] = [{"name": "Lead"}]
        assert route_after_extraction(state) == "verify_contact"

    def test_route_after_verification_completion_vs_loop(self):
        """Loops to next target if queue remains; finishes to sync_sheet if queue exhausted."""
        state = create_initial_state()
        state["target_organizations"] = [{"name": "Org 1"}, {"name": "Org 2"}]
        state["active_org_index"] = 1
        state["verified_leads"] = []
        state["max_target_count"] = 5
        # Index 1 < len(target_organizations) -> loops
        assert route_after_verification(state) == "expand_targets"

        # Queue exhausted -> sync_sheet
        state["active_org_index"] = 2
        assert route_after_verification(state) == "sync_sheet"

        # Quota met -> sync_sheet
        state["active_org_index"] = 0
        state["verified_leads"] = [{"lead": i} for i in range(5)]
        assert route_after_verification(state) == "sync_sheet"


# ==============================================================================
# Task 6.3: StateGraph Compilation & End-to-End Flow Tests
# ==============================================================================

class TestStateGraphCompilationAndFlow:
    def test_graph_compilation_with_checkpointer(self):
        """Graph compiles successfully with MemorySaver checkpointer."""
        saver = MemorySaver()
        app = build_lead_discovery_graph(checkpointer=saver)
        assert app is not None
        # Verify nodes exist in compiled graph
        node_keys = app.nodes.keys()
        for expected in [
            "parse_input",
            "expand_targets",
            "search_web",
            "crawl_page",
            "dead_link_recovery",
            "extract_decision_maker",
            "social_dork_search",
            "verify_contact",
            "sync_sheet",
        ]:
            assert expected in node_keys

    @pytest.mark.asyncio
    async def test_full_graph_execution_end_to_end(self):
        """Runs the compiled LangGraph workflow end-to-end with mocked web network calls."""
        app = build_lead_discovery_graph(checkpointer=MemorySaver())

        # Mock Search
        mock_search_results = [
            MagicMock(
                url="https://acme-robotics.org/council",
                title="Robotics Society Council",
                snippet="President: Devika Sen, Vice President: Rohan Gupta",
            )
        ]

        # Mock Crawler
        mock_page = MagicMock(
            url="https://acme-robotics.org/council",
            status_code=200,
            title="Council",
            markdown_content="Executive Council 2025:\nPresident: Devika Sen\nContact: devika.sen@acme-robotics.org",
            extracted_internal_links=[],
            discovered_emails=["devika.sen@acme-robotics.org"],
            discovered_social_links=["https://linkedin.com/in/devika-sen"],
            is_dead=False,
        )
        mock_crawl_res = MagicMock(pages=[mock_page])

        # Mock Verifier
        mock_lead_record = FinalLeadRecord(
            organization_name="Robotics Society IIT Bombay",
            category=CategoryEnum.COLLEGE_DELEGATION,
            location="Mumbai",
            contact_person="Devika Sen - President",
            contact_channel="devika.sen@acme-robotics.org",
            verification_status=VerificationStatusEnum.VERIFIED,
        )

        with patch("src.graph.nodes.UnifiedSearchClient.search", new_callable=AsyncMock) as mock_s, \
             patch("src.graph.nodes.DeepCrawler.crawl_organization", new_callable=AsyncMock) as mock_c, \
             patch("src.graph.nodes.ContactVerifier.verify_decision_maker", new_callable=AsyncMock) as mock_v:

            mock_s.return_value = mock_search_results
            mock_c.return_value = mock_crawl_res
            mock_v.return_value = mock_lead_record

            initial_state = create_initial_state(
                search_prompt="Find robotics student societies in Mumbai",
                category_focus="College Delegation",
                max_target_count=1,
            )

            config = {"configurable": {"thread_id": "test_session_101"}}
            final_state = await app.ainvoke(initial_state, config=config)

            assert final_state["is_complete"] is True
            assert len(final_state["verified_leads"]) >= 1
            lead = final_state["verified_leads"][0]
            assert lead["Verification Status"] == "Verified"
            assert "Devika Sen - President" == lead["Contact Person"]
            assert len(final_state["audit_logs"]) > 0
