"""Tests for classify_node keyword routing and priority rules."""

from __future__ import annotations

import pytest

from langgraph_agent_lab.nodes import classify_node


@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        # Original 7 scenarios
        ("How do I reset my password?", "simple"),
        ("Please lookup order status for order 12345", "tool"),
        ("Can you fix it?", "missing_info"),
        ("Refund this customer and send confirmation email", "risky"),
        ("Timeout failure while processing request", "error"),
        ("Delete customer account after support verification", "risky"),
        ("System failure cannot recover after multiple attempts", "error"),
        # Custom easy — single obvious keyword
        ("What are your business hours?", "simple"),
        ("Track my package 98765", "tool"),
        ("Fix it now", "missing_info"),
        # Custom medium
        ("Cancel my subscription immediately", "risky"),
        ("Service is unavailable right now", "error"),
        # Custom complex — keyword priority conflicts
        ("Delete order 12345 and send confirmation", "risky"),
        ("Search for crash logs in the database", "tool"),
        ("Remove all permissions and revoke user access", "risky"),
        # Extra keyword coverage
        ("Revoke API token for user account", "risky"),
        ("Remove expired user records", "risky"),
        ("Find customer account by email", "tool"),
        ("Check the status of my claim", "tool"),
        ("Service crashed and is unavailable", "error"),
        ("Database error on login page", "error"),
    ],
)
def test_classify_all_routes(query: str, expected_route: str) -> None:
    result = classify_node({"query": query})
    assert result["route"] == expected_route, (
        f"query={query!r}: expected {expected_route!r}, got {result['route']!r}"
    )


def test_risky_priority_over_tool() -> None:
    """'delete order' has both risky and tool keywords — risky must win."""
    result = classify_node({"query": "delete order 12345"})
    assert result["route"] == "risky"


def test_risky_priority_over_error() -> None:
    """'cancel' (risky) beats 'error' (error) in priority."""
    result = classify_node({"query": "cancel request due to system error"})
    assert result["route"] == "risky"


def test_tool_priority_over_error() -> None:
    """'search' (tool) beats 'crash' (error) in priority."""
    result = classify_node({"query": "search for crash logs"})
    assert result["route"] == "tool"


def test_missing_info_it_word_boundary() -> None:
    """'it' inside 'iteration' must NOT trigger missing_info."""
    result = classify_node({"query": "how does iteration work"})
    assert result["route"] != "missing_info"


def test_missing_info_exact_it_word() -> None:
    """'Fix it now' — exact 'it' word should trigger missing_info."""
    result = classify_node({"query": "Fix it now"})
    assert result["route"] == "missing_info"


def test_error_substring_fail_in_failure() -> None:
    """'failure' contains 'fail' — must trigger error route."""
    result = classify_node({"query": "system failure"})
    assert result["route"] == "error"


def test_classify_sets_high_risk_for_risky() -> None:
    """Risky route must set risk_level=high."""
    result = classify_node({"query": "refund customer"})
    assert result["risk_level"] == "high"


def test_classify_emits_event() -> None:
    """classify_node must emit at least one event."""
    result = classify_node({"query": "lookup order"})
    assert len(result.get("events", [])) >= 1
    assert result["events"][0]["node"] == "classify"


def test_empty_query_defaults_to_simple() -> None:
    """Empty query should not raise and defaults to simple."""
    result = classify_node({"query": ""})
    assert result["route"] == "simple"
