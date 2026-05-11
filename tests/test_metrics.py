"""Tests for metrics schema, aggregation, and latency tracking."""

from __future__ import annotations

from langgraph_agent_lab.metrics import metric_from_state, summarize_metrics
from langgraph_agent_lab.state import make_event


def test_metric_from_state_success() -> None:
    state = {
        "scenario_id": "S",
        "route": "simple",
        "final_answer": "ok",
        "events": [
            make_event("intake", "completed", "ok"),
            make_event("answer", "completed", "ok"),
        ],
        "errors": [],
    }
    metric = metric_from_state(state, expected_route="simple", approval_required=False)
    assert metric.success is True
    assert metric.nodes_visited == 2


def test_summarize_metrics() -> None:
    m1 = metric_from_state(
        {"scenario_id": "1", "route": "simple", "final_answer": "ok", "events": [], "errors": []},
        "simple",
        False,
    )
    m2 = metric_from_state(
        {"scenario_id": "2", "route": "tool", "final_answer": None, "events": [], "errors": []},
        "tool",
        False,
    )
    report = summarize_metrics([m1, m2])
    assert report.total_scenarios == 2
    assert 0 <= report.success_rate <= 1


def test_latency_ms_preserved() -> None:
    """metric_from_state must pass latency_ms through to ScenarioMetric."""
    state = {
        "scenario_id": "S",
        "route": "simple",
        "final_answer": "ok",
        "events": [make_event("answer", "completed", "ok")],
        "errors": [],
    }
    metric = metric_from_state(state, "simple", False, latency_ms=42)
    assert metric.latency_ms == 42


def test_error_list_propagated() -> None:
    """Errors from state must appear in ScenarioMetric.errors."""
    state = {
        "scenario_id": "S",
        "route": "error",
        "final_answer": "retried",
        "events": [],
        "errors": ["transient failure attempt=1", "transient failure attempt=2"],
    }
    metric = metric_from_state(state, "error", False)
    assert len(metric.errors) == 2


def test_retry_count_from_events() -> None:
    """retry_count must equal the number of 'retry' node events."""
    state = {
        "scenario_id": "S",
        "route": "error",
        "final_answer": "ok",
        "events": [
            make_event("retry", "completed", "attempt 1"),
            make_event("retry", "completed", "attempt 2"),
            make_event("answer", "completed", "ok"),
        ],
        "errors": [],
    }
    metric = metric_from_state(state, "error", False)
    assert metric.retry_count == 2


def test_approval_required_fails_without_approval() -> None:
    """Risky scenario without approval dict must not be success."""
    state = {
        "scenario_id": "S",
        "route": "risky",
        "final_answer": "done",
        "events": [],
        "errors": [],
        "approval": None,
    }
    metric = metric_from_state(state, "risky", approval_required=True)
    assert metric.success is False


def test_approval_required_succeeds_with_approval() -> None:
    """Risky scenario with approval must succeed."""
    state = {
        "scenario_id": "S",
        "route": "risky",
        "final_answer": "done",
        "events": [],
        "errors": [],
        "approval": {"approved": True, "reviewer": "mock", "comment": "ok"},
    }
    metric = metric_from_state(state, "risky", approval_required=True)
    assert metric.success is True
    assert metric.approval_observed is True


def test_summarize_resume_success_flag() -> None:
    """summarize_metrics must propagate resume_success flag."""
    m = metric_from_state(
        {"scenario_id": "1", "route": "simple", "final_answer": "ok", "events": [], "errors": []},
        "simple",
        False,
    )
    report = summarize_metrics([m], resume_success=True)
    assert report.resume_success is True
