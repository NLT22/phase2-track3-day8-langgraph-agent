"""Smoke tests for the full LangGraph workflow."""

from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None,
    reason="langgraph not installed in local environment",
)

from langgraph_agent_lab.graph import build_graph  # noqa: E402
from langgraph_agent_lab.persistence import build_checkpointer  # noqa: E402
from langgraph_agent_lab.state import Route, Scenario, initial_state  # noqa: E402


def _run(query: str, expected_route: str, max_attempts: int = 3) -> dict:
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="smoke",
        query=query,
        expected_route=Route(expected_route),
        max_attempts=max_attempts,
    )
    state = initial_state(scenario)
    return graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})


@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("How do I reset my password?", "simple"),
        ("Please lookup order status for order 123", "tool"),
        ("Refund this customer", "risky"),
        ("Can you fix it?", "missing_info"),
        ("Timeout failure while processing request", "error"),
        ("Delete customer account after support verification", "risky"),
    ],
)
def test_graph_runs_basic_routes(query: str, expected_route: str) -> None:
    result = _run(query, expected_route)
    assert result["route"] == expected_route
    assert result.get("final_answer") or result.get("pending_question")


def test_all_paths_set_final_answer_or_question() -> None:
    """Every route must produce a non-null final_answer or pending_question."""
    scenarios = [
        ("How do I reset my password?", "simple"),
        ("Track my package 98765", "tool"),
        ("Can you fix it?", "missing_info"),
        ("Refund this customer and send confirmation email", "risky"),
        ("Timeout failure while processing request", "error"),
    ]
    for query, route in scenarios:
        result = _run(query, route)
        assert result.get("final_answer") or result.get("pending_question"), (
            f"No output produced for route={route!r}"
        )


def test_dead_letter_terminates() -> None:
    """S07: max_attempts=1 must reach dead_letter node and set final_answer."""
    result = _run("System failure cannot recover after multiple attempts", "error", max_attempts=1)
    assert result.get("final_answer") is not None
    nodes_visited = [e["node"] for e in result.get("events", [])]
    assert "dead_letter" in nodes_visited, f"dead_letter not in nodes: {nodes_visited}"


def test_risky_route_sets_approval() -> None:
    """Risky path must pass through approval_node and set approval dict."""
    result = _run("Delete customer account after support verification", "risky")
    assert result.get("approval") is not None
    assert result["approval"]["approved"] is True


def test_error_route_retries_then_succeeds() -> None:
    """Error route should retry at least once before producing a final_answer."""
    result = _run("Timeout failure while processing request", "error")
    assert result.get("final_answer") is not None
    retry_events = [e for e in result.get("events", []) if e["node"] == "retry"]
    assert len(retry_events) >= 1, "Expected at least one retry event"


def test_missing_info_sets_pending_question() -> None:
    """missing_info route must set pending_question."""
    result = _run("Can you fix it?", "missing_info")
    assert result.get("pending_question") is not None


def test_persistence_state_retrieval() -> None:
    """After invoke with MemorySaver, get_state must return the persisted state."""
    checkpointer = build_checkpointer("memory")
    graph = build_graph(checkpointer=checkpointer)
    scenario = Scenario(id="persist-test", query="lookup order 999", expected_route=Route.TOOL)
    state = initial_state(scenario)
    cfg: dict = {"configurable": {"thread_id": state["thread_id"]}}
    graph.invoke(state, config=cfg)
    saved = graph.get_state(cfg)
    assert saved.values.get("scenario_id") == "persist-test"
    assert saved.values.get("route") == "tool"


def test_events_audit_trail_non_empty() -> None:
    """Every completed run must have a non-empty events list."""
    result = _run("How do I reset my password?", "simple")
    assert len(result.get("events", [])) > 0


def test_finalize_always_last_event() -> None:
    """'finalize' must be the last node in the events audit trail."""
    result = _run("How do I reset my password?", "simple")
    events = result.get("events", [])
    assert events, "No events recorded"
    assert events[-1]["node"] == "finalize", (
        f"Last event was {events[-1]['node']!r}, expected 'finalize'"
    )
