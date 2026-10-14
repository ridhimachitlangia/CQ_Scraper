"""Master LangGraph Cyclical State Machine Assembly & Compilation (Task 6.3).

Assembles isolated nodes and conditional routing edges into a robust, cyclical
StateGraph with MemorySaver checkpointer for state auditability, pause/resume, and replayability.
"""

from __future__ import annotations

from typing import Any, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.graph.edges import (
    route_after_crawl,
    route_after_extraction,
    route_after_verification,
)
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
from src.models.state import AgentState


def build_lead_discovery_graph(checkpointer: Optional[Any] = None) -> Any:
    """Constructs, connects, and compiles the master LangGraph workflow.

    Args:
        checkpointer: Optional LangGraph checkpointer (defaults to MemorySaver).

    Returns:
        CompiledStateGraph instance ready for .invoke() or .astream_events().
    """
    workflow = StateGraph(AgentState)

    # 1. Register Execution Nodes
    workflow.add_node("parse_input", parse_input_node)
    workflow.add_node("expand_targets", expand_targets_node)
    workflow.add_node("search_web", search_web_node)
    workflow.add_node("crawl_page", crawl_page_node)
    workflow.add_node("dead_link_recovery", dead_link_recovery_node)
    workflow.add_node("extract_decision_maker", extract_decision_maker_node)
    workflow.add_node("social_dork_search", social_dork_search_node)
    workflow.add_node("verify_contact", verify_contact_node)
    workflow.add_node("sync_sheet", sync_sheet_node)

    # 2. Sequential Startup Edges
    workflow.add_edge(START, "parse_input")
    workflow.add_edge("parse_input", "expand_targets")
    workflow.add_edge("expand_targets", "search_web")
    workflow.add_edge("search_web", "crawl_page")

    # 3. Conditional Edge 1: Dead Link Resilience
    workflow.add_conditional_edges(
        "crawl_page",
        route_after_crawl,
        {
            "dead_link_recovery": "dead_link_recovery",
            "extract_decision_maker": "extract_decision_maker",
        },
    )
    workflow.add_edge("dead_link_recovery", "search_web")

    # 4. Conditional Edge 2: Social Dork Fallback
    workflow.add_conditional_edges(
        "extract_decision_maker",
        route_after_extraction,
        {
            "social_dork_search": "social_dork_search",
            "verify_contact": "verify_contact",
        },
    )
    workflow.add_edge("social_dork_search", "verify_contact")

    # 5. Conditional Edge 3: Cyclical Queue Completion Loop
    workflow.add_conditional_edges(
        "verify_contact",
        route_after_verification,
        {
            "expand_targets": "expand_targets",
            "sync_sheet": "sync_sheet",
        },
    )
    workflow.add_edge("sync_sheet", END)

    # 6. Compilation with Checkpointer
    saver = checkpointer if checkpointer is not None else MemorySaver()
    compiled_app = workflow.compile(checkpointer=saver)

    return compiled_app


# Default singleton instance
lead_graph = build_lead_discovery_graph()

