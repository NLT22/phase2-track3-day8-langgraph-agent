"""Node implementations for the LangGraph workflow.

Each function should be small, testable, and return a partial state update. Avoid mutating the
input state in place.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .state import AgentState, ApprovalDecision, Route, make_event

# ---------------------------------------------------------------------------
# Keyword sets for classify_node — priority: risky > tool > missing_info > error > simple
# ---------------------------------------------------------------------------

RISKY_KEYWORDS: frozenset[str] = frozenset(
    {"refund", "delete", "send", "cancel", "remove", "revoke"}
)
TOOL_KEYWORDS: frozenset[str] = frozenset(
    {"status", "order", "lookup", "check", "track", "find", "search"}
)
ERROR_KEYWORDS: frozenset[str] = frozenset(
    {"timeout", "fail", "error", "crash", "unavailable"}
)


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields."""
    query = state.get("query", "").strip()
    word_count = len(query.split())
    return {
        "query": query,
        "messages": [f"intake:{query[:40]}"],
        "events": [
            make_event(
                "intake",
                "completed",
                "query normalized",
                word_count=word_count,
                char_count=len(query),
            )
        ],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using priority-ordered keyword matching.

    Priority: risky > tool > missing_info > error > simple.
    Uses substring-within-word matching so 'failure' triggers error and
    'it' is matched as an exact whole word to avoid false positives like 'iteration'.
    """
    query = state.get("query", "").lower()
    clean_words = [w.strip("?!.,;:'\"") for w in query.split()]
    word_set = set(clean_words)

    if any(kw in word for kw in RISKY_KEYWORDS for word in clean_words):
        route, risk_level = Route.RISKY, "high"
    elif any(kw in word for kw in TOOL_KEYWORDS for word in clean_words):
        route, risk_level = Route.TOOL, "low"
    elif len(clean_words) < 5 and "it" in word_set:
        route, risk_level = Route.MISSING_INFO, "low"
    elif any(kw in word for kw in ERROR_KEYWORDS for word in clean_words):
        route, risk_level = Route.ERROR, "low"
    else:
        route, risk_level = Route.SIMPLE, "low"

    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [make_event("classify", "completed", f"route={route.value}")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating."""
    query = state.get("query", "")
    question = (
        f"Your request '{query[:60]}' is missing details. "
        "Could you please provide more context, such as an order ID or account number?"
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "missing information requested")],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool.

    Simulates transient failures for error-route scenarios to demonstrate retry loops.
    Idempotent: the same attempt number always yields the same result.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get("scenario_id", "unknown")
    query = state.get("query", "")
    if state.get("route") == Route.ERROR.value and attempt < 2:
        result = (
            f"ERROR: transient failure attempt={attempt} scenario={scenario_id}"
        )
    else:
        result = (
            f"SUCCESS: tool executed for scenario={scenario_id} "
            f"query='{query[:40]}' attempt={attempt}"
        )
    return {
        "tool_results": [result],
        "events": [
            make_event("tool", "completed", f"tool executed attempt={attempt}")
        ],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval."""
    query = state.get("query", "")
    risk_level = state.get("risk_level", "high")
    proposed = (
        f"Proposed action for: '{query[:80]}' — "
        f"risk_level={risk_level}. Requires human approval before execution."
    )
    return {
        "proposed_action": proposed,
        "events": [make_event("risky_action", "pending_approval", "awaiting human approval")],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt().

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock approval so tests and CI run offline.
    """
    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt  # type: ignore[import-untyped]

        value = interrupt(
            {
                "proposed_action": state.get("proposed_action"),
                "risk_level": state.get("risk_level"),
            }
        )
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        decision = ApprovalDecision(approved=True, comment="mock approval for lab")

    return {
        "approval": decision.model_dump(),
        "events": [
            make_event("approval", "completed", f"approved={decision.approved}")
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt with bounded counter and backoff metadata."""
    attempt = int(state.get("attempt", 0)) + 1
    backoff_ms = min(100 * (2 ** (attempt - 1)), 2000)
    errors = [f"transient failure attempt={attempt}"]
    return {
        "attempt": attempt,
        "errors": errors,
        "events": [
            make_event(
                "retry",
                "completed",
                "retry attempt recorded",
                attempt=attempt,
                backoff_ms=backoff_ms,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response grounded in tool_results and approval state."""
    tool_results = state.get("tool_results", [])
    approval = state.get("approval") or {}
    route = state.get("route", "")

    if tool_results:
        latest = tool_results[-1]
        if approval.get("approved"):
            answer = (
                f"Action completed with approval from {approval.get('reviewer', 'reviewer')}. "
                f"Result: {latest}"
            )
        else:
            answer = f"Tool result: {latest}"
    elif route == Route.SIMPLE.value:
        answer = (
            f"Here is the information for your request: "
            f"'{state.get('query', '')[:80]}'. "
            "Please contact support if you need further assistance."
        )
    else:
        answer = "Your request has been processed successfully."

    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops."""
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""
    if latest.startswith("ERROR"):
        return {
            "evaluation_result": "needs_retry",
            "events": [
                make_event(
                    "evaluate", "completed", "tool result indicates failure, retry needed"
                )
            ],
        }
    return {
        "evaluation_result": "success",
        "events": [
            make_event("evaluate", "completed", "tool result satisfactory")
        ],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures to dead-letter queue and mark for manual review."""
    scenario_id = state.get("scenario_id", "unknown")
    attempt = state.get("attempt", 0)
    errors = state.get("errors", [])

    # Persist to dead-letter log file
    record = {
        "scenario_id": scenario_id,
        "attempt": attempt,
        "errors": list(errors),
        "query": state.get("query", ""),
    }
    try:
        dl_path = Path("outputs/dead_letters.jsonl")
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        with dl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass

    return {
        "final_answer": (
            f"Request for scenario '{scenario_id}' could not be completed after "
            f"{attempt} attempt(s). Logged to dead-letter queue for manual review."
        ),
        "events": [
            make_event(
                "dead_letter",
                "completed",
                f"max retries exceeded, attempt={attempt}",
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
